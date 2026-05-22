"""Phase 2 — audit_logs 발행 + /admin/dashboard/events 조회 통합 테스트.

route-level 발행(`emit_from_request`)이 실제로 audit_logs를 만드는지,
events endpoint가 필터/페이지네이션을 정상 처리하는지 검증.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import AuthService, get_current_admin_user, get_current_user
from app.database import get_db
from app.main import app
from app.models import Member
from app.models.audit_log import AuditLog
from app.services.audit_service import Action, ResourceType, emit, emit_from_request


@contextmanager
def _client_with_admin(db, admin_user):
    def override_get_db():
        yield db

    def override_admin():
        return admin_user

    def override_current():
        return admin_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_admin_user] = override_admin
    app.dependency_overrides[get_current_user] = override_current
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


# ---------- emit / emit_from_request 단위 ----------

class TestEmitHelpers:
    def test_emit_inserts_and_commits(self, db, sample_member):
        emit(
            db,
            action=Action.CREATE,
            resource_type=ResourceType.MODEL,
            actor_member_id=sample_member.member_id,
            resource_id="42",
            metadata={"name": "test"},
            request_id="req-1",
        )
        rows = db.query(AuditLog).filter(AuditLog.request_id == "req-1").all()
        assert len(rows) == 1
        assert rows[0].action == "create"
        assert rows[0].metadata_json == {"name": "test"}

    def test_emit_swallows_failure(self, db, sample_member):
        """잘못된 컬럼 길이라도 본 액션이 깨지지 않음 (best-effort)."""
        # action 길이 64 초과 — 일부러 실패 유도
        emit(
            db,
            action="x" * 200,
            resource_type=ResourceType.MODEL,
            actor_member_id=sample_member.member_id,
        )
        # 예외 안 던지고 정상 진행되면 통과
        # (SQLite는 길이 제약을 강제하지 않을 수 있어 실패 안 할 수도 있음)


# ---------- /events 조회 ----------

def _seed_audits(db, actor):
    """다양한 audit 시드. created_at 약간씩 차이를 두기 위해 순서대로 add."""
    now = datetime.utcnow()
    items = [
        AuditLog(action="create", resource_type="model",
                 actor_member_id=actor.member_id, resource_id="1",
                 created_at=now - timedelta(minutes=5)),
        AuditLog(action="update", resource_type="model",
                 actor_member_id=actor.member_id, resource_id="1",
                 created_at=now - timedelta(minutes=4)),
        AuditLog(action="delete", resource_type="prompt",
                 actor_member_id=actor.member_id, resource_id="9",
                 created_at=now - timedelta(minutes=3)),
        AuditLog(action="login", resource_type="member",
                 actor_member_id=actor.member_id, resource_id=actor.member_id,
                 created_at=now - timedelta(minutes=2)),
        AuditLog(action="create", resource_type="dataset",
                 actor_member_id=actor.member_id, resource_id="100",
                 created_at=now - timedelta(minutes=1)),
    ]
    for it in items:
        db.add(it)
    db.flush()


def test_events_returns_latest_first(db, admin_member):
    _seed_audits(db, admin_member)

    with _client_with_admin(db, admin_member) as client:
        resp = client.get("/api/v1/admin/dashboard/events", params={"size": 10})
        assert resp.status_code == 200
        body = resp.json()

    assert body["total"] == 5
    assert len(body["data"]) == 5
    # 최신 (dataset create)이 첫 번째
    assert body["data"][0]["action"] == "create"
    assert body["data"][0]["resource_type"] == "dataset"


def test_events_filter_by_resource_type(db, admin_member):
    _seed_audits(db, admin_member)

    with _client_with_admin(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/events",
            params={"resource_type": "model"},
        ).json()

    assert body["total"] == 2
    assert all(item["resource_type"] == "model" for item in body["data"])


def test_events_filter_by_action(db, admin_member):
    _seed_audits(db, admin_member)

    with _client_with_admin(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/events",
            params={"action": "create"},
        ).json()

    assert body["total"] == 2
    assert all(item["action"] == "create" for item in body["data"])


def test_events_filter_by_actor(db, admin_member, sample_member):
    _seed_audits(db, admin_member)
    db.add(AuditLog(
        action="create", resource_type="prompt",
        actor_member_id=sample_member.member_id, resource_id="200",
    ))
    db.flush()

    with _client_with_admin(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/events",
            params={"actor": sample_member.member_id},
        ).json()

    assert body["total"] == 1
    assert body["data"][0]["actor_member_id"] == sample_member.member_id


def test_events_filter_by_since(db, admin_member):
    _seed_audits(db, admin_member)

    threshold = datetime.utcnow() - timedelta(minutes=2, seconds=30)
    with _client_with_admin(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/events",
            params={"since": threshold.isoformat()},
        ).json()

    # 최근 2건 (login + dataset create)
    assert body["total"] == 2


def test_events_pagination(db, admin_member):
    _seed_audits(db, admin_member)

    with _client_with_admin(db, admin_member) as client:
        page1 = client.get(
            "/api/v1/admin/dashboard/events",
            params={"size": 2, "page": 1},
        ).json()
        page2 = client.get(
            "/api/v1/admin/dashboard/events",
            params={"size": 2, "page": 2},
        ).json()

    assert page1["total"] == 5
    assert len(page1["data"]) == 2
    assert len(page2["data"]) == 2
    # 페이지 1, 2의 첫 행 다름
    assert page1["data"][0]["id"] != page2["data"][0]["id"]


def test_events_metadata_alias_exposed(db, admin_member):
    """payload는 응답에서 metadata로 노출 (계획대로)."""
    db.add(AuditLog(
        action="create", resource_type="prompt",
        actor_member_id=admin_member.member_id,
        metadata_json={"name": "p1"},
    ))
    db.flush()

    with _client_with_admin(db, admin_member) as client:
        body = client.get("/api/v1/admin/dashboard/events").json()

    item = body["data"][0]
    # serialization_alias="metadata" 적용
    assert "metadata" in item
    assert item["metadata"] == {"name": "p1"}


def test_events_blocks_non_admin(db, sample_member):
    """admin 가드."""
    def override_get_db():
        yield db

    def override_current():
        return sample_member

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current
    try:
        with TestClient(app) as client:
            resp = client.get("/api/v1/admin/dashboard/events")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---------- 통합: login 호출 시 audit 발행 ----------

class _DummyResponse:
    def __init__(self):
        self.cookies = {}

    def set_cookie(self, **kwargs):
        self.cookies[kwargs["key"]] = kwargs["value"]


def test_login_emits_audit(db, monkeypatch):
    """auth.py의 login 라우트가 호출되면 audit_logs에 LOGIN 이벤트가 1건 생긴다."""
    from app.cruds.member import member_crud
    from app.schemas.member import MemberCreate

    member = member_crud.create_member(
        db,
        MemberCreate(
            name="감사대상",
            member_id="audit-test-001",
            email="audit01@test.com",
            password="Test1234!@",
            password_confirm="Test1234!@",
            role="user",
        ),
    )

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            resp = client.post("/api/v1/auth/login", json={
                "member_id": "audit-test-001",
                "password": "Test1234!@",
            })
            assert resp.status_code == 200, resp.text
    finally:
        app.dependency_overrides.clear()

    logs = db.query(AuditLog).filter(
        AuditLog.actor_member_id == "audit-test-001",
        AuditLog.action == "login",
    ).all()
    assert len(logs) == 1
    assert logs[0].resource_type == "member"
    # request_id가 middleware 통해 들어왔다면 set
    assert logs[0].request_id is not None
