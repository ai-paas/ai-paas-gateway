"""생성 시도 레코드·자동 복구·자동 정리 회귀 테스트."""
import pytest

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import settings
from app.cruds.knowledge_base import knowledge_base_crud as crud
from app.database import get_db
from app.main import app
from app.models import AttemptState, AuditLog, KnowledgeBase, KnowledgeBaseCreateAttempt
from app.schemas.knowledge_base import (
    ExternalKnowledgeBaseBriefResponse,
    ExternalKnowledgeBaseDetailResponse,
    KnowledgeBaseFileReadSchema,
)
from app.scheduler import job_cleanup_orphan_knowledge_bases
from app.services.knowledge_base_service import knowledge_base_service

KB_LIST = "/api/v1/knowledge-bases"

NOW = datetime.now(timezone.utc)
T0 = NOW - timedelta(hours=2)
MAX_INGEST = timedelta(seconds=settings.KB_MAX_INGEST_SECONDS)

NAME = "사내규정_2026"
FILENAME = "규정.pdf"


class _NoCloseSession:
    """시도 레코드 CRUD 는 의도적으로 SessionLocal() 을 쓴다 — 매핑 롤백에 휩쓸리지 않기 위함.

    테스트에서는 그 별도 세션이 운영 DB 를 가리키므로, 같은 테스트 세션을 넘기되 close() 만
    막아 fixture 의 트랜잭션 격리를 유지한다.
    """

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def _attempt_session(db, monkeypatch):
    import app.cruds.knowledge_base as crud_module

    monkeypatch.setattr(crud_module, "SessionLocal", lambda: _NoCloseSession(db))
    yield


def _brief(kb_id, name=NAME, created_at=None):
    return ExternalKnowledgeBaseBriefResponse(
        id=kb_id, name=name, description=None, collection_name=f"col_{kb_id}",
        chunk_size=500, chunk_overlap=50, top_k=3, threshold=0.4,
        created_at=created_at if created_at is not None else T0 + timedelta(minutes=10),
    )


def _detail(kb_id, name=NAME, filename=FILENAME):
    files = []
    if filename is not None:
        files.append(KnowledgeBaseFileReadSchema(
            id=1, knowledge_base_id=kb_id, name=filename, partition_name="p", chunk_number=3,
        ))
    return ExternalKnowledgeBaseDetailResponse(
        id=kb_id, name=name, description=None, collection_name=f"col_{kb_id}",
        embedding_model_id=13, language_id=1, chunk_size=500, chunk_overlap=50,
        chunk_type_id=1, search_method_id=1, top_k=3, threshold=0.4, files=files,
    )


@contextmanager
def _client(db, user, upstream, detail=None, on_detail=None):
    """`on_detail` 은 파일명 대조용 상세 조회를 await 하는 동안 다른 요청이 끼어드는 상황을
    재현한다 — 복구가 그 await 이후 락 안에서 판정을 다시 하는지 검증하는 용도다."""
    async def fake_list(*args, **kwargs):
        return upstream

    async def fake_detail(knowledge_base_id, user_info=None):
        if on_detail is not None:
            on_detail()
        return detail

    originals = (knowledge_base_service.get_knowledge_bases,
                 knowledge_base_service.get_knowledge_base)
    knowledge_base_service.get_knowledge_bases = fake_list
    knowledge_base_service.get_knowledge_base = fake_detail

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        (knowledge_base_service.get_knowledge_bases,
         knowledge_base_service.get_knowledge_base) = originals


def _attempt(db, member_id, snapshot, state=AttemptState.ORPHAN_SUSPECT,
             started_at=T0, name=NAME, filename=FILENAME, resolved=None, request_id="req-1"):
    a = KnowledgeBaseCreateAttempt(
        member_id=member_id, name=name, filename=filename, request_id=request_id,
        upstream_snapshot=snapshot, state=state, started_at=started_at,
        resolved_surro_id=resolved,
    )
    db.add(a)
    db.flush()
    return a


def _mapping(db, member_id, surro_id, active=True):
    kb = KnowledgeBase(
        name=NAME, collection_name=f"col_{surro_id}", created_by=member_id,
        surro_knowledge_id=surro_id, is_active=active,
        deleted_at=None if active else datetime.utcnow(),
    )
    db.add(kb)
    db.flush()
    return kb


# ---------- 실패 분류와 시도 기록 ----------

def test_classify_failure_maps_status_to_state():
    from app.routes.knowledge_base import _classify_failure

    assert _classify_failure(504) == AttemptState.ORPHAN_SUSPECT, "타임아웃은 고아 가능"
    assert _classify_failure(502) == AttemptState.ORPHAN_SUSPECT
    assert _classify_failure(500) == AttemptState.ORPHAN_SUSPECT
    assert _classify_failure(503) == AttemptState.ABANDONED, "연결 실패는 요청이 닿지 않았다"
    assert _classify_failure(400) == AttemptState.ABANDONED
    assert _classify_failure(404) == AttemptState.ABANDONED


def test_attempt_is_recorded_before_upstream_call(db, sample_member):
    """시도는 pending 으로 먼저 기록되고, 종료 시 상태·시각이 갱신된다."""
    attempt_id = crud.create_attempt(
        member_id=sample_member.member_id, name=NAME, filename=FILENAME,
        request_id="req-x", upstream_snapshot=[1, 2],
    )
    row = db.get(KnowledgeBaseCreateAttempt, attempt_id)
    assert row.state == AttemptState.PENDING
    assert row.upstream_snapshot == [1, 2]

    crud.finish_attempt(attempt_id, state=AttemptState.ORPHAN_SUSPECT, failure_kind="504")
    db.refresh(row)
    assert row.state == AttemptState.ORPHAN_SUSPECT
    assert row.failure_kind == "504"
    assert row.finished_at is not None


def test_cancelled_create_closes_attempt_as_orphan_suspect(db, sample_member, monkeypatch):
    """클라이언트가 연결을 끊어도 시도가 pending 으로 남지 않아야 한다.

    CancelledError 는 BaseException 직속이라 라우트의 except Exception 에 걸리지 않는다.
    pending 이 남으면 ATTEMPT_TTL 동안 무관한 KB 를 보호해 남의 복구를 막는다. MLOps 는
    요청을 이미 받았을 수 있으므로 abandoned 가 아니라 orphan_suspect 로 닫는다.
    """
    import asyncio
    from io import BytesIO
    from types import SimpleNamespace

    from fastapi import UploadFile

    from app.routes import knowledge_base as route_module

    async def fake_snapshot(user_info):
        return [1, 2]

    async def cancelled(**kwargs):
        raise asyncio.CancelledError()

    monkeypatch.setattr(route_module, "_snapshot_upstream_ids", fake_snapshot)
    monkeypatch.setattr(knowledge_base_service, "create_knowledge_base", cancelled)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(route_module.create_knowledge_base(
            request=SimpleNamespace(state=SimpleNamespace(request_id="req-cancel")),
            name=NAME, description=None, language_id=1, embedding_model_id=13,
            chunk_size=500, chunk_overlap=50, chunk_type_id=1, search_method_id=1,
            top_k=3, threshold=0.4,
            file=UploadFile(BytesIO(b"doc"), filename=FILENAME),
            db=db, current_user=sample_member,
        ))

    row = db.query(KnowledgeBaseCreateAttempt).filter(
        KnowledgeBaseCreateAttempt.request_id == "req-cancel"
    ).one()
    assert row.state == AttemptState.ORPHAN_SUSPECT
    assert row.failure_kind == "cancelled"


# ---------- 자동 복구 ----------

def test_recovers_single_candidate(db, sample_member):
    attempt = _attempt(db, sample_member.member_id, snapshot=[1, 2])

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        body = client.get(KB_LIST).json()

    assert body["total"] == 1, "복구된 KB 가 같은 응답에 나타나야 한다"
    assert body["data"][0]["surro_knowledge_id"] == 407
    assert body["data"][0]["created_by"] == sample_member.member_id, "소유자는 시도 레코드로 고정"

    db.refresh(attempt)
    assert attempt.state == AttemptState.RECOVERED
    assert attempt.recovered_at is not None


def test_no_recovery_when_two_unknown_kbs_in_window(db, sample_member):
    """같은 이름의 후보가 2개면 복구하지 않는다.

    게이트웨이를 거치지 않은 직접 생성이 끼면 어느 쪽이 내 것인지 알 수 없어 스스로 멈춘다.
    이름이 다른 KB 는 애초에 후보가 아니므로, 구별 불가를 만들려면 이름이 같아야 한다.
    """
    attempt = _attempt(db, sample_member.member_id, snapshot=[1, 2])
    upstream = [_brief(407), _brief(408)]

    with _client(db, sample_member, upstream, detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    db.refresh(attempt)
    assert attempt.state == AttemptState.ORPHAN_SUSPECT


def test_no_recovery_when_filename_differs(db, sample_member):
    """업로드 파일명이 다르면 그 시도의 결과가 아니다."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2])

    with _client(db, sample_member, [_brief(407)], detail=_detail(407, filename="다른.pdf")) as client:
        assert client.get(KB_LIST).json()["total"] == 0


def test_no_recovery_when_name_differs(db, sample_member):
    """KB 이름이 다르면 그 시도의 결과가 아니다."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2])

    with _client(db, sample_member, [_brief(407, name="다른이름")], detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0


def test_no_recovery_for_kb_in_snapshot(db, sample_member):
    """시도 시점에 이미 있던 KB 는 그 시도의 결과일 수 없다 (surro_id 재사용 방어)."""
    _attempt(db, sample_member.member_id, snapshot=[407])

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0


def test_no_recovery_outside_max_ingest_window(db, sample_member):
    _attempt(db, sample_member.member_id, snapshot=[1, 2])
    late = _brief(407, created_at=T0 + MAX_INGEST + timedelta(minutes=1))

    with _client(db, sample_member, [late], detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0


def test_no_recovery_without_snapshot(db, sample_member):
    """스냅샷이 없으면 후보를 특정할 수 없어 복구 대상이 아니다."""
    _attempt(db, sample_member.member_id, snapshot=None)

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0


def test_no_recovery_when_two_attempts_share_the_window(db, sample_member, admin_member):
    """두 시도가 같은 KB 를 후보로 삼으면 — 동시 타임아웃. 오매칭 대신 양쪽 다 미복구."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2], request_id="req-a")
    _attempt(db, admin_member.member_id, snapshot=[1, 2],
             started_at=T0 + timedelta(minutes=5), request_id="req-b")

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0


def test_no_recovery_when_user_already_retried_successfully(db, sample_member):
    """같은 이름·파일로 재시도에 성공했으면 — 구분 불가능한 중복 대신, 원본은 정리 잡이 회수한다."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2])
    _attempt(db, sample_member.member_id, snapshot=[1, 2], state=AttemptState.SUCCEEDED,
             started_at=T0 + timedelta(minutes=5), resolved=500, request_id="req-retry")
    _mapping(db, sample_member.member_id, surro_id=500)

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        body = client.get(KB_LIST).json()

    assert body["total"] == 1, "재시도본만 보여야 한다"
    assert body["data"][0]["surro_knowledge_id"] == 500


def test_unrelated_concurrent_timeout_does_not_block_recovery(db, sample_member, admin_member):
    """이름·파일이 다른 동시 타임아웃은 서로의 복구를 막지 않는다.

    후보 선정이 시간 창만 보면 무관한 KB 까지 후보로 세어져, 생성이 몰리는 시간대에는
    아무도 복구되지 않는다. 이름은 목록 응답에 있으므로 거르는 데 비용이 들지 않는다.
    """
    attempt = _attempt(db, sample_member.member_id, snapshot=[1, 2], request_id="req-a")
    _attempt(db, admin_member.member_id, snapshot=[1, 2],
             started_at=T0 + timedelta(minutes=5),
             name="남의문서", filename="남의.pdf", request_id="req-b")
    upstream = [_brief(407), _brief(408, name="남의문서")]

    with _client(db, sample_member, upstream, detail=_detail(407)) as client:
        body = client.get(KB_LIST).json()

    assert body["total"] == 1, "무관한 타임아웃이 끼어도 자기 KB 는 복구돼야 한다"
    assert body["data"][0]["surro_knowledge_id"] == 407
    db.refresh(attempt)
    assert attempt.state == AttemptState.RECOVERED


def test_own_second_timeout_does_not_block_recovery(db, sample_member):
    """같은 사용자가 두 번 타임아웃해도 복구된다 — 어느 시도의 결과든 소유자가 같다."""
    a1 = _attempt(db, sample_member.member_id, snapshot=[1, 2], request_id="req-1")
    a2 = _attempt(db, sample_member.member_id, snapshot=[1, 2],
                  started_at=T0 + timedelta(minutes=5), request_id="req-2")

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        body = client.get(KB_LIST).json()

    assert body["total"] == 1
    assert body["data"][0]["created_by"] == sample_member.member_id
    db.refresh(a1)
    db.refresh(a2)
    assert a1.state == AttemptState.RECOVERED, "먼저 시작한 시도에 붙인다"
    assert a2.state == AttemptState.ORPHAN_SUSPECT, "나머지는 다음 조회를 기다린다"


def test_recovery_writes_audit_log(db, sample_member):
    """복구는 소유권을 부여하는 유일한 자동 경로이므로 감사 기록이 남아야 한다."""
    attempt = _attempt(db, sample_member.member_id, snapshot=[1, 2], request_id="req-orig")

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 1

    log = db.query(AuditLog).filter(AuditLog.resource_id == "407").one()
    assert log.action == "create"
    assert log.actor_member_id == "system:kb-orphan-recovery"
    assert log.target_member_id == sample_member.member_id
    assert log.metadata_json["recovered"] is True
    assert log.metadata_json["attempt_id"] == attempt.id
    assert log.request_id == "req-orig", "원래 생성 요청과 연결돼야 추적할 수 있다"


def test_no_recovery_while_another_users_create_is_pending(db, sample_member, admin_member):
    """다른 사용자가 같은 이름·파일로 생성 중이면 그 결과를 가로채지 않는다.

    B 의 시도는 pending 이라 아직 매핑이 없다. 여기서 A 가 복구해 버리면 created_by 가
    A 로 굳고, 이후 B 의 후처리는 기존 매핑을 갱신만 하므로 소유권이 되돌아오지 않는다.
    """
    _attempt(db, sample_member.member_id, snapshot=[1, 2], request_id="req-a")
    _attempt(db, admin_member.member_id, snapshot=[1, 2], state=AttemptState.PENDING,
             started_at=T0 + timedelta(minutes=5), request_id="req-b")

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    assert db.query(KnowledgeBase).filter(
        KnowledgeBase.surro_knowledge_id == 407
    ).first() is None, "A 의 매핑이 생기면 안 된다"

    # B 의 생성이 정상 완료되면 소유자는 B 여야 한다.
    kb = crud.create_knowledge_base(
        db=db, name=NAME, description=None, created_by=admin_member.member_id,
        surro_knowledge_id=407, collection_name="col_407",
    )
    assert kb.created_by == admin_member.member_id


def test_own_pending_retry_does_not_block_recovery(db, sample_member):
    """같은 사용자의 재시도는 충돌로 보지 않는다 — 어느 시도의 결과든 소유자가 같다.

    타임아웃을 본 사용자는 대개 곧바로 재시도한다. 이것까지 막으면 가장 흔한 경로에서
    자동 복구가 동작하지 않는다.
    """
    attempt = _attempt(db, sample_member.member_id, snapshot=[1, 2], request_id="req-1st")
    _attempt(db, sample_member.member_id, snapshot=[1, 2], state=AttemptState.PENDING,
             started_at=T0 + timedelta(minutes=5), request_id="req-retry")

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        body = client.get(KB_LIST).json()

    assert body["total"] == 1
    assert body["data"][0]["created_by"] == sample_member.member_id
    db.refresh(attempt)
    assert attempt.state == AttemptState.RECOVERED


def test_no_recovery_when_mapping_appeared_during_upstream_call(db, sample_member, admin_member):
    """상세 조회를 await 하는 사이 다른 요청이 먼저 복구를 끝낸 경우 — 중복 매핑 금지."""
    attempt = _attempt(db, sample_member.member_id, snapshot=[1, 2])

    def other_request_recovers_first():
        _mapping(db, admin_member.member_id, surro_id=407)

    with _client(db, sample_member, [_brief(407)], detail=_detail(407),
                 on_detail=other_request_recovers_first) as client:
        assert client.get(KB_LIST).status_code == 200

    db.refresh(attempt)
    assert attempt.state == AttemptState.ORPHAN_SUSPECT, "물러나야 한다"
    assert db.query(KnowledgeBase).filter(
        KnowledgeBase.surro_knowledge_id == 407
    ).count() == 1, "매핑이 두 개가 되면 안 된다"


def test_no_recovery_when_attempt_was_abandoned_during_upstream_call(db, sample_member):
    """상세 조회를 await 하는 사이 관리자가 force 삭제로 시도를 끊은 경우.

    그대로 복구하면 업스트림에서 사라진 KB 를 가리키는 매핑이 생긴다.
    """
    attempt = _attempt(db, sample_member.member_id, snapshot=[1, 2])

    def admin_force_deletes():
        attempt.state = AttemptState.ABANDONED
        db.flush()

    with _client(db, sample_member, [_brief(407)], detail=_detail(407),
                 on_detail=admin_force_deletes) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    assert db.query(KnowledgeBase).filter(
        KnowledgeBase.surro_knowledge_id == 407
    ).first() is None


def test_lock_is_noop_outside_postgresql(db):
    """SQLite 등 advisory lock 이 없는 백엔드에서는 아무 일도 하지 않아야 한다."""
    crud.lock_surro_knowledge_id(db, 407)


def test_lock_emits_transaction_scoped_advisory_lock_on_postgresql():
    """PostgreSQL 에서 거는 SQL 의 형태를 고정한다.

    테스트는 SQLite 로 돌아 실제 락 SQL 이 한 번도 실행되지 않는다. 직렬화 자체는 이
    테스트로 증명되지 않으며(PostgreSQL 실행이 필요하다), 여기서는 파라미터 이름이나
    함수명이 바뀌어 조용히 no-op 이 되는 회귀만 막는다.
    """
    captured = {}

    class _Session:
        class bind:
            class dialect:
                name = "postgresql"

        def execute(self, statement, params=None):
            captured["sql"] = str(statement)
            captured["params"] = params

    crud.lock_surro_knowledge_id(_Session(), 407)

    assert "pg_advisory_xact_lock" in captured["sql"], "세션 범위가 아니라 트랜잭션 범위여야 한다"
    assert captured["params"]["id"] == 407


def test_recoverable_attempts_are_id_ordered(db, sample_member):
    """호출자가 이 순서로 후보 KB 락을 잡는다 — 순서가 흔들리면 동시 요청이 데드락에 빠진다."""
    ids = [
        _attempt(db, sample_member.member_id, snapshot=[1], request_id=f"req-{i}").id
        for i in range(3)
    ]

    rows = crud.get_recoverable_attempts(db, sample_member.member_id, NOW)
    assert [r.id for r in rows] == sorted(ids)


def test_list_survives_recovery_failure(db, sample_member, monkeypatch):
    """부가 기능이 주 기능을 깨면 안 된다."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2])
    monkeypatch.setattr(
        crud, "get_recoverable_attempts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        assert client.get(KB_LIST).status_code == 200


# ---------- 자동 정리 ----------

def test_cleanup_targets_exclude_active_and_protected(db, sample_member):
    _mapping(db, sample_member.member_id, surro_id=100)
    _attempt(db, sample_member.member_id, snapshot=[1, 2])

    old = NOW - timedelta(minutes=settings.PROXY_KB_ORPHAN_TTL_MINUTES + 60)
    upstream = [
        _brief(100, created_at=old),   # active 매핑 있음
        _brief(407),                   # 보호 대상 (살아 있는 시도의 창 안)
        _brief(408, created_at=old),   # 정리 대상
        _brief(409),                   # TTL 미경과
    ]

    targets = crud.find_cleanup_targets(db, upstream, NOW)
    assert [kb.id for kb in targets] == [408]


class _FakeService:
    """스케줄러 잡이 쓰는 서비스 대역. 인스턴스 생성·close 를 기록한다."""

    instances = []

    def __init__(self):
        self.closed = False
        self.deleted = []
        type(self).instances.append(self)

    async def get_knowledge_bases(self, *args, **kwargs):
        return type(self).upstream

    async def delete_knowledge_base(self, knowledge_base_id, user_info=None):
        self.deleted.append(knowledge_base_id)
        return True

    async def close(self):
        self.closed = True


def _install_fake_service(monkeypatch, upstream):
    import app.services.knowledge_base_service as svc_mod

    _FakeService.instances = []
    _FakeService.upstream = upstream
    monkeypatch.setattr(svc_mod, "KnowledgeBaseService", _FakeService)
    return _FakeService


def test_cleanup_job_skips_on_empty_upstream(monkeypatch):
    """빈 응답을 '전부 고아'로 해석하면 업스트림 장애 한 번에 전체를 지운다."""
    _install_fake_service(monkeypatch, upstream=[])
    called = {"n": 0}
    monkeypatch.setattr(crud, "find_cleanup_targets",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or [])

    job_cleanup_orphan_knowledge_bases()
    assert called["n"] == 0, "대상 계산 자체에 도달하면 안 된다"


def test_cleanup_job_dry_run_does_not_delete(monkeypatch):
    fake = _install_fake_service(
        monkeypatch, upstream=[_brief(408, created_at=NOW - timedelta(days=365))]
    )
    monkeypatch.setattr(settings, "KB_ORPHAN_CLEANUP_DRY_RUN", True)

    job_cleanup_orphan_knowledge_bases()
    assert all(not inst.deleted for inst in fake.instances), "dry-run 은 삭제하지 않는다"


def test_cleanup_job_uses_a_fresh_client_and_closes_it(monkeypatch):
    """모듈 싱글턴의 AsyncClient 는 asyncio.run 이 만든 새 루프와 엇갈린다.

    기존 reconcile 잡들과 같이 호출마다 새 인스턴스를 만들고 닫아야 한다.
    """
    fake = _install_fake_service(
        monkeypatch, upstream=[_brief(408, created_at=NOW - timedelta(days=365))]
    )
    monkeypatch.setattr(settings, "KB_ORPHAN_CLEANUP_DRY_RUN", True)

    job_cleanup_orphan_knowledge_bases()

    assert fake.instances, "잡은 자체 서비스 인스턴스를 만들어야 한다"
    assert all(inst.closed for inst in fake.instances), "만든 인스턴스는 모두 닫아야 한다"

