"""생성 시도 레코드·자동 복구·자동 정리 회귀 테스트."""
import pytest

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.common.kb_attempt_token import attach_token, attempt_token, make_token
from app.auth import get_current_user
from app.config import settings
from app.cruds.knowledge_base import knowledge_base_crud as crud
from app.database import get_db
from app.main import app
from app.models import AttemptState, AuditLog, KnowledgeBase, KnowledgeBaseCreateAttempt
from app.schemas.knowledge_base import ExternalKnowledgeBaseBriefResponse
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


def _brief(kb_id, name=NAME, created_at=None, token_for=None):
    """`token_for` 에 시도를 주면, 그 시도가 생성 요청에 실어 보낸 토큰이 description 에 들어 있다."""
    return ExternalKnowledgeBaseBriefResponse(
        id=kb_id, name=name,
        description=(attach_token(None, attempt_token(token_for))
                     if token_for is not None else None),
        collection_name=f"col_{kb_id}",
        chunk_size=500, chunk_overlap=50, top_k=3, threshold=0.4,
        created_at=created_at if created_at is not None else T0 + timedelta(minutes=10),
    )


@contextmanager
def _client(db, user, upstream, detail_calls=None):
    """업스트림 목록을 고정한 TestClient. 상세 조회가 불리면 `detail_calls` 에 기록한다."""
    async def fake_list(*args, **kwargs):
        return upstream

    async def fake_detail(knowledge_base_id, user_info=None):
        if detail_calls is not None:
            detail_calls.append(knowledge_base_id)
        return None

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


def _attempt(db, member_id, snapshot=None, state=AttemptState.ORPHAN_SUSPECT,
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
    attempt_id, token = crud.create_attempt(
        member_id=sample_member.member_id, name=NAME, filename=FILENAME, request_id="req-x",
    )
    row = db.get(KnowledgeBaseCreateAttempt, attempt_id)
    assert row.state == AttemptState.PENDING
    assert token == attempt_token(row), "생성 요청에 실은 토큰을 저장된 행으로 다시 만들 수 있어야 한다"

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

    async def cancelled(**kwargs):
        raise asyncio.CancelledError()

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
    attempt = _attempt(db, sample_member.member_id)

    with _client(db, sample_member, [_brief(407, token_for=attempt)]) as client:
        body = client.get(KB_LIST).json()

    assert body["total"] == 1, "복구된 KB 가 같은 응답에 나타나야 한다"
    assert body["data"][0]["surro_knowledge_id"] == 407
    assert body["data"][0]["created_by"] == sample_member.member_id, "소유자는 시도 레코드로 고정"

    db.refresh(attempt)
    assert attempt.state == AttemptState.RECOVERED
    assert attempt.recovered_at is not None


def test_no_recovery_when_two_kbs_carry_the_same_token(db, sample_member):
    """같은 토큰을 가진 KB 가 둘이면 복구하지 않는다.

    토큰은 업스트림 화면에 description 으로 그대로 보이므로, 그걸 복사해 만든 KB 가 섞일 수 있다.
    어느 쪽이 이 시도의 결과인지 알 수 없으면 멈춘다.
    """
    attempt = _attempt(db, sample_member.member_id)
    upstream = [_brief(407, token_for=attempt), _brief(408, token_for=attempt)]

    with _client(db, sample_member, upstream) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    db.refresh(attempt)
    assert attempt.state == AttemptState.ORPHAN_SUSPECT


def test_copy_is_not_recovered_when_the_original_is_already_mapped(db, sample_member):
    """원본이 이미 매핑돼 있으면 같은 토큰의 복사본은 후보가 아니다.

    매핑 뒤 성공 기록이 유실되면 시도가 pending 으로 남고 복구 창이 닫힌 뒤 다시 복구 대상이 된다.
    알려진 원본을 먼저 빼고 세면 복사본이 유일 후보가 되어 이 사용자에게 넘어간다.
    """
    attempt = _attempt(db, sample_member.member_id, state=AttemptState.PENDING,
                       started_at=NOW - MAX_INGEST - timedelta(minutes=1))
    _mapping(db, sample_member.member_id, 407)
    upstream = [_brief(407, token_for=attempt), _brief(500, token_for=attempt)]

    with _client(db, sample_member, upstream) as client:
        client.get(KB_LIST)

    assert crud.get_knowledge_base_by_surro_id(db, 500) is None
    db.refresh(attempt)
    assert attempt.state == AttemptState.PENDING


def test_differently_named_copy_is_not_recovered_after_the_original_is_gone(db, sample_member):
    """원본이 업스트림에서 직접 삭제되고 이름이 다른 복사본만 남으면 복구하지 않는다.

    게이트웨이는 이름을 바꾸지 않고 보내므로, 이름이 다르면 이 시도가 만든 KB 가 아니다.
    이름까지 같은 복사본은 구별할 수 없어 복구된다.
    """
    attempt = _attempt(db, sample_member.member_id)

    with _client(db, sample_member, [_brief(500, name="복사본", token_for=attempt)]) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    db.refresh(attempt)
    assert attempt.state == AttemptState.ORPHAN_SUSPECT


def test_same_name_kb_without_the_token_is_not_a_candidate(db, sample_member):
    """이름·파일·시각이 다 맞아도 토큰이 없으면 이 시도의 결과가 아니다 — 게이트웨이를 거치지 않은 생성이다."""
    attempt = _attempt(db, sample_member.member_id)

    with _client(db, sample_member, [_brief(407)]) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    db.refresh(attempt)
    assert attempt.state == AttemptState.ORPHAN_SUSPECT


def test_kb_carrying_another_attempts_token_is_not_a_candidate(db, sample_member):
    mine = _attempt(db, sample_member.member_id, request_id="req-mine")
    other = _attempt(db, sample_member.member_id, state=AttemptState.ABANDONED,
                     request_id="req-other")

    with _client(db, sample_member, [_brief(407, token_for=other)]) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    db.refresh(mine)
    assert mine.state == AttemptState.ORPHAN_SUSPECT


def test_kb_from_before_a_restore_is_not_claimed_by_a_reused_attempt_id(db, sample_member):
    """DB 를 백업에서 복원하면 시퀀스가 되돌아가 같은 id 가 다시 발급된다.

    복원 전에 그 id 로 만든 KB 는 업스트림에 남아 매핑 없는 고아가 된다. 토큰이 id 만으로
    정해지면 새 시도가 그 KB 를 자기 것으로 가져간다 — 다른 사용자의 KB 일 수 있다.
    """
    # 클라이언트가 X-Request-ID 를 고정해 보내 request_id 까지 같은 최악의 경우다.
    attempt = _attempt(db, sample_member.member_id, request_id="fixed-header")
    before_restore = _brief(407)
    before_restore.attempt_token = make_token(
        attempt.id, "fixed-header", attempt.started_at - timedelta(days=3)
    )

    with _client(db, sample_member, [before_restore]) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    db.refresh(attempt)
    assert attempt.state == AttemptState.ORPHAN_SUSPECT


def test_recovery_does_not_depend_on_creation_time(db, sample_member):
    """토큰과 이름이 맞으면 복구한다 — 업스트림 생성 시각은 판정에 쓰지 않는다.

    남겨 두면 업스트림 시계가 어긋나거나 인제스트가 길어질 때 멀쩡한 복구를 거부한다.
    """
    attempt = _attempt(db, sample_member.member_id)
    late = T0 + MAX_INGEST + timedelta(minutes=1)
    kb = _brief(407, created_at=late, token_for=attempt)

    with _client(db, sample_member, [kb]) as client:
        assert client.get(KB_LIST).json()["total"] == 1


def test_recovers_even_when_upstream_omits_created_at(db, sample_member):
    attempt = _attempt(db, sample_member.member_id)
    kb = _brief(407, token_for=attempt)
    kb.created_at = None

    with _client(db, sample_member, [kb]) as client:
        assert client.get(KB_LIST).json()["total"] == 1


def test_no_recovery_when_user_already_retried_successfully(db, sample_member):
    """같은 이름·파일로 재시도에 성공했으면 원본은 복구하지 않는다 — 사용자는 이미 원하는 KB 를 가졌다.

    토큰은 원본의 주인을 알려 줄 뿐, 사용자가 둘 다 원하는지는 알려 주지 않는다. 원본은 정리 잡이 회수한다.
    """
    original = _attempt(db, sample_member.member_id)
    _attempt(db, sample_member.member_id, state=AttemptState.SUCCEEDED,
             started_at=T0 + timedelta(minutes=5), resolved=500, request_id="req-retry")
    _mapping(db, sample_member.member_id, surro_id=500)

    with _client(db, sample_member, [_brief(407, token_for=original)]) as client:
        body = client.get(KB_LIST).json()

    assert body["total"] == 1, "재시도본만 보여야 한다"
    assert body["data"][0]["surro_knowledge_id"] == 500


def test_other_users_concurrent_timeout_does_not_block_recovery(db, sample_member, admin_member):
    """다른 사용자의 동시 타임아웃은 이름이 같아도 서로의 복구를 막지 않는다 — 각 KB 에 주인의 토큰이 있다."""
    mine = _attempt(db, sample_member.member_id, request_id="req-a")
    theirs = _attempt(db, admin_member.member_id, started_at=T0 + timedelta(minutes=5),
                      request_id="req-b")
    upstream = [_brief(407, token_for=mine), _brief(408, token_for=theirs)]

    with _client(db, sample_member, upstream) as client:
        body = client.get(KB_LIST).json()

    assert [kb["surro_knowledge_id"] for kb in body["data"]] == [407]
    db.refresh(mine)
    db.refresh(theirs)
    assert mine.state == AttemptState.RECOVERED
    assert theirs.state == AttemptState.ORPHAN_SUSPECT, "남의 KB 는 그 주인이 목록을 열 때 복구된다"


def test_recovery_writes_audit_log(db, sample_member):
    """복구는 소유권을 부여하는 유일한 자동 경로이므로 감사 기록이 남아야 한다."""
    attempt = _attempt(db, sample_member.member_id, request_id="req-orig")

    with _client(db, sample_member, [_brief(407, token_for=attempt)]) as client:
        assert client.get(KB_LIST).json()["total"] == 1

    log = db.query(AuditLog).filter(AuditLog.resource_id == "407").one()
    assert log.action == "create"
    assert log.actor_member_id == "system:kb-orphan-recovery"
    assert log.target_member_id == sample_member.member_id
    assert log.metadata_json["recovered"] is True
    assert log.metadata_json["attempt_id"] == attempt.id
    assert log.request_id == "req-orig", "원래 생성 요청과 연결돼야 추적할 수 있다"


def test_no_recovery_of_a_kb_another_user_is_still_creating(db, sample_member, admin_member):
    """다른 사용자가 같은 이름·파일로 생성 중이면 그 결과를 가로채지 않는다.

    B 의 시도는 pending 이라 아직 매핑이 없다. 여기서 A 가 가져가면 created_by 가 A 로 굳고,
    B 의 후처리는 기존 매핑을 갱신만 하므로 소유권이 되돌아오지 않는다.
    """
    _attempt(db, sample_member.member_id, request_id="req-a")
    # 복구 창이 열려 있어야 "아직 생성 중" 이다 — 닫힌 pending 은 그 주인의 복구 대상이 된다.
    theirs = _attempt(db, admin_member.member_id, state=AttemptState.PENDING,
                      started_at=NOW - MAX_INGEST / 2, request_id="req-b")

    with _client(db, sample_member, [_brief(407, token_for=theirs)]) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    assert db.query(KnowledgeBase).filter(
        KnowledgeBase.surro_knowledge_id == 407
    ).first() is None, "A 의 매핑이 생기면 안 된다"


def test_recovery_makes_no_per_candidate_upstream_call(db, sample_member):
    """판정에 필요한 값(토큰·이름·설명·컬렉션)은 목록 응답에 다 있다 — 후보마다 상세를 부르면 N+1 이다."""
    attempts = [_attempt(db, sample_member.member_id, request_id=f"req-{i}") for i in range(3)]
    upstream = [_brief(407 + i, token_for=a) for i, a in enumerate(attempts)]
    detail_calls = []

    with _client(db, sample_member, upstream, detail_calls=detail_calls) as client:
        assert client.get(KB_LIST).json()["total"] == 3

    assert detail_calls == []


def test_finish_attempt_does_not_revive_a_terminal_attempt(db, sample_member):
    """종결된 시도는 되살아나지 않는다.

    관리자가 force 삭제로 시도를 끊은 직후, 진행 중이던 그 생성 요청이 타임아웃으로 돌아와
    상태를 orphan_suspect 로 덮어쓰면 시도가 다시 살아난다. 붙을 대상은 이미 업스트림에서
    지워졌는데 시도 TTL 동안 남아 다른 판정을 흐린다.
    """
    for terminal in (AttemptState.ABANDONED, AttemptState.RECOVERED, AttemptState.SUCCEEDED):
        attempt = _attempt(db, sample_member.member_id, state=terminal,
                           request_id=f"req-{terminal}")
        crud.finish_attempt(attempt.id, state=AttemptState.ORPHAN_SUSPECT,
                            failure_kind="504")
        db.refresh(attempt)
        assert attempt.state == terminal, f"{terminal} 이 되살아났다"


def test_recoverable_attempts_do_not_require_a_snapshot(db, sample_member):
    """스냅샷은 더 이상 기록하지 않는다 — 스냅샷 유무로 거르면 새 시도가 전부 복구 대상에서 빠진다."""
    ids = [
        _attempt(db, sample_member.member_id, snapshot=s, request_id=f"req-{i}").id
        for i, s in enumerate([None, [1, 2]])
    ]

    rows = crud.get_recoverable_attempts(db, sample_member.member_id, NOW)

    assert [r.id for r in rows] == ids


def test_no_recovery_when_another_request_mapped_the_kb_first(db, sample_member, admin_member,
                                                              monkeypatch):
    """목록을 읽은 뒤 락을 잡기 전에 다른 요청이 먼저 복구를 끝낸 경우 — 중복 매핑 금지.

    판정은 락 밖에서 읽은 목록으로 하므로, 락 안에서 다시 확인하지 않으면 이 틈을 막을 수 없다.
    """
    attempt = _attempt(db, sample_member.member_id)

    def other_request_wins_then_lock(_db, surro_id):
        _mapping(db, admin_member.member_id, surro_id=surro_id)
        return True
    monkeypatch.setattr(crud, "try_lock_surro_knowledge_id", other_request_wins_then_lock)

    with _client(db, sample_member, [_brief(407, token_for=attempt)]) as client:
        assert client.get(KB_LIST).status_code == 200

    db.refresh(attempt)
    assert attempt.state == AttemptState.ORPHAN_SUSPECT, "물러나야 한다"
    assert db.query(KnowledgeBase).filter(
        KnowledgeBase.surro_knowledge_id == 407
    ).count() == 1, "매핑이 두 개가 되면 안 된다"


def test_no_recovery_when_the_attempt_was_abandoned_first(db, sample_member, monkeypatch):
    """목록을 읽은 뒤 락을 잡기 전에 관리자가 force 삭제로 시도를 끊은 경우.

    그대로 복구하면 업스트림에서 사라진 KB 를 가리키는 매핑이 생긴다.
    """
    attempt = _attempt(db, sample_member.member_id)

    def admin_force_deletes_then_lock(_db, _surro_id):
        attempt.state = AttemptState.ABANDONED
        db.flush()
        return True
    monkeypatch.setattr(crud, "try_lock_surro_knowledge_id", admin_force_deletes_then_lock)

    with _client(db, sample_member, [_brief(407, token_for=attempt)]) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    assert db.query(KnowledgeBase).filter(
        KnowledgeBase.surro_knowledge_id == 407
    ).first() is None


def test_skipped_claim_ends_the_transaction_before_the_next_lock(db, sample_member, monkeypatch):
    """후보 하나를 락 안에서 건너뛰었으면, 다음 후보의 락을 잡기 전에 트랜잭션을 닫아야 한다.

    트랜잭션 범위 락은 commit/rollback 으로만 풀린다. 닫지 않으면 건너뛴 KB 의 락이 요청이
    끝날 때까지 남아, 그동안 그 KB 에 대한 관리자 삭제가 409 로 막힌다.
    트랜잭션이 닫혔는지는 세션의 commit 호출로 관찰한다.
    """
    events = []
    a1 = _attempt(db, sample_member.member_id, request_id="req-1")
    a2 = _attempt(db, sample_member.member_id, started_at=T0 + timedelta(minutes=1),
                  request_id="req-2")

    def fake_try_lock(_db, surro_id):
        events.append(f"lock:{surro_id}")
        return surro_id != 407          # 407 은 경합으로 건너뛰게 만든다
    monkeypatch.setattr(crud, "try_lock_surro_knowledge_id", fake_try_lock)

    real_commit = db.commit

    def spy_commit():
        events.append("commit")
        real_commit()
    monkeypatch.setattr(db, "commit", spy_commit)

    upstream = [_brief(407, token_for=a1), _brief(408, token_for=a2)]

    with _client(db, sample_member, upstream) as client:
        assert client.get(KB_LIST).status_code == 200

    assert events[:3] == ["lock:407", "commit", "lock:408"], (
        f"락을 쥔 채 다음 후보로 넘어갔다: {events}"
    )
    db.refresh(a1)
    db.refresh(a2)
    assert a1.state == AttemptState.ORPHAN_SUSPECT, "경합한 후보는 다음 기회를 기다린다"
    assert a2.state == AttemptState.RECOVERED, "경합이 뒤 후보의 복구까지 막으면 안 된다"


def test_recovery_defers_when_lock_is_contended(db, sample_member, monkeypatch):
    """락 경합 시 복구를 보류한다 — 기다리지 않는다.

    복구는 지금 당장 해야 하는 일이 아니다. 기다리면 그동안 이벤트 루프가 멈춘다.
    """
    attempt = _attempt(db, sample_member.member_id)
    monkeypatch.setattr(crud, "try_lock_surro_knowledge_id", lambda *a, **k: False)

    with _client(db, sample_member, [_brief(407, token_for=attempt)]) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    db.refresh(attempt)
    assert attempt.state == AttemptState.ORPHAN_SUSPECT, "보류일 뿐 포기가 아니다"
    assert db.query(KnowledgeBase).filter(
        KnowledgeBase.surro_knowledge_id == 407
    ).first() is None


def test_recovery_completes_on_the_next_call_after_contention(db, sample_member, monkeypatch):
    """보류된 복구는 다음 목록 조회에서 완료된다 — 경합이 영구 지연이 되면 안 된다."""
    attempt = _attempt(db, sample_member.member_id)
    upstream = [_brief(407, token_for=attempt)]

    with monkeypatch.context() as m:
        m.setattr(crud, "try_lock_surro_knowledge_id", lambda *a, **k: False)
        with _client(db, sample_member, upstream) as client:
            assert client.get(KB_LIST).json()["total"] == 0

    with _client(db, sample_member, upstream) as client:
        assert client.get(KB_LIST).json()["total"] == 1

    db.refresh(attempt)
    assert attempt.state == AttemptState.RECOVERED


def test_try_lock_is_noop_outside_postgresql(db):
    """SQLite 등 advisory lock 이 없는 백엔드에서는 항상 획득한 것으로 본다 — 단일 커넥션이다."""
    assert crud.try_lock_surro_knowledge_id(db, 407) is True


def test_try_lock_does_not_wait_and_reports_contention():
    """PostgreSQL 에서 거는 SQL 의 형태와 반환 규약을 고정한다.

    테스트는 SQLite 로 돌아 실제 락 SQL 이 한 번도 실행되지 않는다. 직렬화 자체는 이 테스트로
    증명되지 않으며(PostgreSQL 실행이 필요하다), 여기서는 (1) 대기하는 락으로 되돌아가는 회귀와
    (2) 경합 결과를 삼켜 항상 획득한 것처럼 구는 회귀를 막는다. 대기하면 안 되는 이유는 이
    락을 부르는 라우트가 async 인데 세션은 동기라, 대기하는 동안 이벤트 루프가 통째로 멈추기
    때문이다.
    """
    captured = {}

    class _Result:
        def __init__(self, value):
            self._value = value

        def scalar(self):
            return self._value

    class _Session:
        class bind:
            class dialect:
                name = "postgresql"

        def __init__(self, value):
            self._value = value

        def execute(self, statement, params=None):
            captured["sql"] = str(statement)
            captured["params"] = params
            return _Result(self._value)

    assert crud.try_lock_surro_knowledge_id(_Session(True), 407) is True
    assert "pg_try_advisory_xact_lock" in captured["sql"], "대기형이면 이벤트 루프가 멈춘다"
    assert captured["params"]["id"] == 407
    assert crud.try_lock_surro_knowledge_id(_Session(False), 407) is False, "경합을 삼키면 안 된다"


def test_recoverable_attempts_are_id_ordered(db, sample_member):
    """호출자가 이 순서로 후보 KB 락을 잡는다 — 순서가 흔들리면 동시 요청이 데드락에 빠진다."""
    ids = [
        _attempt(db, sample_member.member_id, snapshot=[1], request_id=f"req-{i}").id
        for i in range(3)
    ]

    rows = crud.get_recoverable_attempts(db, sample_member.member_id, NOW)
    assert [r.id for r in rows] == sorted(ids)


def test_recoverable_attempts_include_pending_only_after_window_closes(db, sample_member):
    """창이 열린 pending 은 생성 요청이 아직 진행 중일 수 있어 대상이 아니다."""
    _attempt(db, sample_member.member_id, state=AttemptState.PENDING,
             started_at=NOW - MAX_INGEST / 2, request_id="req-open")
    stale = _attempt(db, sample_member.member_id, state=AttemptState.PENDING,
                     started_at=NOW - MAX_INGEST - timedelta(minutes=10), request_id="req-stale")

    ids = [a.id for a in crud.get_recoverable_attempts(db, sample_member.member_id, NOW)]

    assert ids == [stale.id]


def test_recovers_attempt_left_pending_by_a_killed_process(db, sample_member):
    """강제 종료로 pending 에 남은 시도도 창이 닫히면 복구된다.

    배포 재시작의 SIGKILL 로 끝난 요청은 예외 처리 경로를 타지 못한다. pending 을 영영
    복구하지 않으면 그 사용자의 KB 는 보호만 받다가 고아로 남는다.
    """
    started = NOW - MAX_INGEST - timedelta(minutes=10)
    attempt = _attempt(db, sample_member.member_id, state=AttemptState.PENDING,
                       started_at=started)
    upstream = [_brief(407, created_at=started + timedelta(minutes=5), token_for=attempt)]

    with _client(db, sample_member, upstream) as client:
        body = client.get(KB_LIST).json()

    assert body["total"] == 1
    assert body["data"][0]["created_by"] == sample_member.member_id
    db.refresh(attempt)
    assert attempt.state == AttemptState.RECOVERED


def test_list_survives_recovery_failure(db, sample_member, monkeypatch):
    """부가 기능이 주 기능을 깨면 안 된다."""
    _attempt(db, sample_member.member_id)
    monkeypatch.setattr(
        crud, "get_recoverable_attempts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with _client(db, sample_member, [_brief(407)]) as client:
        assert client.get(KB_LIST).status_code == 200


# ---------- 자동 정리 ----------

def test_cleanup_targets_exclude_active_and_protected(db, sample_member):
    _mapping(db, sample_member.member_id, surro_id=100)
    attempt = _attempt(db, sample_member.member_id)

    old = NOW - timedelta(minutes=settings.PROXY_KB_ORPHAN_TTL_MINUTES + 60)
    upstream = [
        _brief(100, created_at=old),                          # active 매핑 있음
        _brief(407, created_at=old, token_for=attempt),    # 살아 있는 시도의 토큰 — 보호
        _brief(408, created_at=old),                          # 정리 대상
        _brief(409),                                          # TTL 미경과
    ]

    targets = crud.find_cleanup_targets(db, upstream, NOW)
    assert [kb.id for kb in targets] == [408]


def test_settings_reject_attempt_ttl_not_shorter_than_orphan_ttl(monkeypatch):
    """시도 TTL 이 고아 TTL 보다 짧지 않은 설정은 기동 자체를 거부해야 한다.

    정리 잡은 락도 선점도 없이 업스트림을 지우고, 그게 안전한 근거는 정리 대상 창과 복구 창이
    겹칠 수 없다는 것 하나뿐이다. 그 관계를 만드는 것이 이 검증이므로, 검증이 사라지면 락 없는
    삭제가 곧바로 위험해진다. 현재 기본값만 확인하면 검증을 통째로 지워도 알아채지 못한다.
    """
    from app.config import Settings

    monkeypatch.setattr(Settings, "KB_ATTEMPT_TTL_MINUTES", 10080)
    monkeypatch.setattr(Settings, "PROXY_KB_ORPHAN_TTL_MINUTES", 1440)

    with pytest.raises(ValueError, match="KB_ATTEMPT_TTL_MINUTES"):
        Settings()


def test_cleanup_target_cannot_be_claimed_by_any_live_attempt(db, sample_member):
    """정리 잡은 락도 선점도 없이 업스트림을 지운다 — 살아 있는 시도가 가져갈 수 있는 KB 는 대상이 될 수 없다.

    두 겹으로 막는다. 설정 검증(시도 TTL < 고아 TTL) 때문에 살아 있는 시도의 KB 는 고아 TTL 을
    넘길 수 없다. 그래도 업스트림 시계가 어긋나 오래된 것처럼 보이면 토큰 보호가 대상에서 뺀다.
    """
    now = datetime.now(timezone.utc)
    old = now - timedelta(minutes=settings.PROXY_KB_ORPHAN_TTL_MINUTES + 1)

    # 살아 있을 수 있는 가장 이른 시도 — 시도 TTL 경계.
    live = _attempt(db, sample_member.member_id, state=AttemptState.PENDING,
                    started_at=now - timedelta(minutes=settings.KB_ATTEMPT_TTL_MINUTES - 1))
    owned = _brief(407, created_at=old, token_for=live)
    stranger = _brief(408, created_at=old)

    live_attempts = crud.get_live_attempts(db, now)
    assert crud.find_protecting_attempts(owned, live_attempts) == [live]
    assert crud.find_protecting_attempts(stranger, live_attempts) == []
    assert [kb.id for kb in crud.find_cleanup_targets(db, [owned, stranger], now)] == [408]


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

