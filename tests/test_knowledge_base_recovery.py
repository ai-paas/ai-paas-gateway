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
from app.models import AttemptState, KnowledgeBase, KnowledgeBaseCreateAttempt
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
def _client(db, user, upstream, detail=None):
    async def fake_list(*args, **kwargs):
        return upstream

    async def fake_detail(knowledge_base_id, user_info=None):
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


# ---------- Step 3: 분류 ----------

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


# ---------- Step 4: 자동 복구 ----------

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
    """조건 2 — 게이트웨이를 거치지 않은 직접 생성이 끼면 자동화가 스스로 멈춘다."""
    attempt = _attempt(db, sample_member.member_id, snapshot=[1, 2])
    upstream = [_brief(407), _brief(408, name="남의KB")]

    with _client(db, sample_member, upstream, detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0

    db.refresh(attempt)
    assert attempt.state == AttemptState.ORPHAN_SUSPECT


def test_no_recovery_when_filename_differs(db, sample_member):
    """조건 4"""
    _attempt(db, sample_member.member_id, snapshot=[1, 2])

    with _client(db, sample_member, [_brief(407)], detail=_detail(407, filename="다른.pdf")) as client:
        assert client.get(KB_LIST).json()["total"] == 0


def test_no_recovery_when_name_differs(db, sample_member):
    """조건 3"""
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
    """조건 0 — 스냅샷 없는 시도는 개선분만 포기한다."""
    _attempt(db, sample_member.member_id, snapshot=None)

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0


def test_no_recovery_when_two_attempts_share_the_window(db, sample_member, admin_member):
    """조건 5 — 동시 타임아웃. 오매칭 대신 양쪽 다 미복구."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2], request_id="req-a")
    _attempt(db, admin_member.member_id, snapshot=[1, 2],
             started_at=T0 + timedelta(minutes=5), request_id="req-b")

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        assert client.get(KB_LIST).json()["total"] == 0


def test_no_recovery_when_user_already_retried_successfully(db, sample_member):
    """조건 6 — 구분 불가능한 중복을 만들지 않는다. 원본은 Step 5 가 회수한다."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2])
    _attempt(db, sample_member.member_id, snapshot=[1, 2], state=AttemptState.SUCCEEDED,
             started_at=T0 + timedelta(minutes=5), resolved=500, request_id="req-retry")
    _mapping(db, sample_member.member_id, surro_id=500)

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        body = client.get(KB_LIST).json()

    assert body["total"] == 1, "재시도본만 보여야 한다"
    assert body["data"][0]["surro_knowledge_id"] == 500


def test_list_survives_recovery_failure(db, sample_member, monkeypatch):
    """부가 기능이 주 기능을 깨면 안 된다."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2])
    monkeypatch.setattr(
        crud, "get_recoverable_attempts",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with _client(db, sample_member, [_brief(407)], detail=_detail(407)) as client:
        assert client.get(KB_LIST).status_code == 200


# ---------- Step 5: 자동 정리 ----------

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


def test_cleanup_job_skips_on_empty_upstream(monkeypatch, caplog):
    """빈 응답을 '전부 고아'로 해석하면 업스트림 장애 한 번에 전체를 지운다."""
    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(knowledge_base_service, "get_knowledge_bases", empty)
    called = {"n": 0}
    monkeypatch.setattr(crud, "find_cleanup_targets",
                        lambda *a, **k: called.__setitem__("n", called["n"] + 1) or [])

    job_cleanup_orphan_knowledge_bases()
    assert called["n"] == 0, "대상 계산 자체에 도달하면 안 된다"


def test_cleanup_job_dry_run_does_not_delete(monkeypatch):
    async def upstream(*args, **kwargs):
        return [_brief(408, created_at=NOW - timedelta(days=365))]

    deleted = []

    async def fake_delete(kb_id, user_info=None):
        deleted.append(kb_id)
        return True

    monkeypatch.setattr(knowledge_base_service, "get_knowledge_bases", upstream)
    monkeypatch.setattr(knowledge_base_service, "delete_knowledge_base", fake_delete)
    monkeypatch.setattr(settings, "KB_ORPHAN_CLEANUP_DRY_RUN", True)

    job_cleanup_orphan_knowledge_bases()
    assert deleted == [], "dry-run 은 삭제하지 않는다"
