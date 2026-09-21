"""고아 Knowledge Base 관리자 라우트 (docs/orphan-kb-plan.md Step 1).

검증 대상은 계획서 Step 1의 "검증:" 줄이다 — 고아만 노출 / active 매핑 미노출 /
매핑 있는 id 삭제 거부 / 보호 대상 409·force 시 삭제 + 시도 abandoned /
복구 창 밖 KB 는 살아 있는 시도가 있어도 보호되지 않음.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.auth import get_current_admin_user, get_current_user
from app.config import settings
from app.database import get_db
from app.main import app
from app.models import AttemptState, AuditLog, KnowledgeBase, KnowledgeBaseCreateAttempt
from app.schemas.knowledge_base import ExternalKnowledgeBaseBriefResponse
from app.services.knowledge_base_service import knowledge_base_service

ORPHANS = "/api/v1/knowledge-bases/admin/orphans"

NOW = datetime.now(timezone.utc)
T0 = NOW - timedelta(hours=3)
MAX_INGEST = timedelta(seconds=settings.KB_MAX_INGEST_SECONDS)


def _external(kb_id, name="kb", created_at=None):
    return ExternalKnowledgeBaseBriefResponse(
        id=kb_id,
        name=name,
        description=None,
        collection_name=f"kb_col_{kb_id}",
        chunk_size=500,
        chunk_overlap=50,
        top_k=3,
        threshold=0.4,
        created_at=created_at if created_at is not None else T0 + timedelta(minutes=30),
    )


@contextmanager
def _client(db, user, upstream, deleted=True, admin=True):
    """업스트림 응답을 고정한 TestClient."""
    async def fake_list(*args, **kwargs):
        return upstream

    async def fake_delete(knowledge_base_id, user_info=None):
        return deleted

    original_list = knowledge_base_service.get_knowledge_bases
    original_delete = knowledge_base_service.delete_knowledge_base
    knowledge_base_service.get_knowledge_bases = fake_list
    knowledge_base_service.delete_knowledge_base = fake_delete

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    if admin:
        app.dependency_overrides[get_current_admin_user] = lambda: user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        knowledge_base_service.get_knowledge_bases = original_list
        knowledge_base_service.delete_knowledge_base = original_delete


def _mapping(db, member_id, surro_id, name="kb"):
    kb = KnowledgeBase(
        name=name,
        collection_name=f"kb_col_{surro_id}",
        created_by=member_id,
        surro_knowledge_id=surro_id,
        is_active=True,
    )
    db.add(kb)
    db.flush()
    return kb


def _attempt(db, member_id, snapshot, started_at=T0, state=AttemptState.ORPHAN_SUSPECT):
    a = KnowledgeBaseCreateAttempt(
        member_id=member_id,
        name="사내규정_2026",
        filename="규정.pdf",
        request_id="req-1",
        upstream_snapshot=snapshot,
        state=state,
        started_at=started_at,
    )
    db.add(a)
    db.flush()
    return a


# ---------- 목록 ----------

def test_list_orphans_excludes_active_mappings(db, admin_member):
    _mapping(db, admin_member.member_id, surro_id=100)
    upstream = [_external(100), _external(407)]

    with _client(db, admin_member, upstream) as client:
        body = client.get(ORPHANS).json()

    assert body["total"] == 1, "active 매핑이 있는 건은 고아가 아니다"
    assert body["data"][0]["surro_knowledge_id"] == 407


def test_list_orphans_marks_protected(db, admin_member):
    _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])
    upstream = [_external(407, created_at=T0 + timedelta(minutes=30))]

    with _client(db, admin_member, upstream) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is True, "창 안에 생긴 미지 KB 는 복구 대기로 표시돼야 한다"
    assert admin_member.member_id in item["protected_by"]


def test_list_orphans_outside_recovery_window_is_not_protected(db, admin_member):
    """복구 창 밖 KB 는 살아 있는 시도가 있어도 보호되지 않는다.

    보호 범위가 복구 범위보다 넓으면, 복구되지도 않으면서 삭제만 막히는 구간이 생긴다.
    """
    _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])
    upstream = [_external(407, created_at=T0 + MAX_INGEST + timedelta(minutes=1))]

    with _client(db, admin_member, upstream) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is False
    assert item["protected_by"] is None


def test_list_orphans_ignores_attempt_that_already_knew_the_kb(db, admin_member):
    """스냅샷에 이미 있던 id 는 그 시도의 결과일 수 없다."""
    _attempt(db, admin_member.member_id, snapshot=[407])
    upstream = [_external(407)]

    with _client(db, admin_member, upstream) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is False


def test_list_orphans_refuses_empty_upstream(db, admin_member):
    """빈 응답을 '전부 고아'로 해석하면 안 된다."""
    with _client(db, admin_member, upstream=[]) as client:
        assert client.get(ORPHANS).status_code == 503


def test_list_orphans_requires_admin(db, sample_member):
    with _client(db, sample_member, upstream=[_external(407)], admin=False) as client:
        assert client.get(ORPHANS).status_code == 403


# ---------- 삭제 ----------

def test_delete_rejects_when_active_mapping_exists(db, admin_member):
    _mapping(db, admin_member.member_id, surro_id=100)

    with _client(db, admin_member, upstream=[_external(100)]) as client:
        res = client.delete(f"{ORPHANS}/100")

    assert res.status_code == 409, "매핑이 있으면 고아가 아니므로 일반 삭제 경로를 써야 한다"


def test_delete_rejects_protected_without_force(db, admin_member):
    _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])
    upstream = [_external(407, created_at=T0 + timedelta(minutes=30))]

    with _client(db, admin_member, upstream) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert "force" in res.json()["detail"]


def test_delete_protected_with_force_abandons_attempt(db, admin_member):
    attempt = _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])
    upstream = [_external(407, name="사내규정_2026", created_at=T0 + timedelta(minutes=30))]

    with _client(db, admin_member, upstream) as client:
        res = client.delete(f"{ORPHANS}/407?force=true")

    assert res.status_code == 200
    body = res.json()
    assert body["forced"] is True
    assert body["abandoned_attempts"] == 1

    db.refresh(attempt)
    assert attempt.state == AttemptState.ABANDONED, (
        "붙을 대상이 사라진 시도를 남기면 ATTEMPT_TTL 동안 무관한 고아를 계속 보호한다"
    )
    assert attempt.finished_at is not None

    log = db.query(AuditLog).filter(AuditLog.resource_id == "407").one()
    assert log.action == "delete"
    assert log.metadata_json["forced"] is True
    assert log.metadata_json["orphan"] is True


def test_delete_unprotected_orphan_succeeds(db, admin_member):
    upstream = [_external(407)]

    with _client(db, admin_member, upstream) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 200
    body = res.json()
    assert body["forced"] is False
    assert body["abandoned_attempts"] == 0


def test_delete_refuses_empty_upstream(db, admin_member):
    with _client(db, admin_member, upstream=[]) as client:
        assert client.delete(f"{ORPHANS}/407").status_code == 503


def test_delete_returns_404_when_missing_upstream(db, admin_member):
    with _client(db, admin_member, upstream=[_external(100)]) as client:
        assert client.delete(f"{ORPHANS}/407").status_code == 404


def test_delete_requires_admin(db, sample_member):
    with _client(db, sample_member, upstream=[_external(407)], admin=False) as client:
        assert client.delete(f"{ORPHANS}/407").status_code == 403
