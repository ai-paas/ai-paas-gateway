"""개인 사용자 대시보드 — 본인 자산만 카운트되는지 검증."""
from contextlib import contextmanager
from datetime import datetime

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models import (
    Dataset,
    Experiment,
    KnowledgeBase,
    Model,
    ModelImprovement,
    Prompt,
    Service,
    Workflow,
)
from app.services import dashboard_service


@contextmanager
def _client_for_user(db, user):
    def override_get_db():
        yield db

    def override_user():
        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _seed_for(db, member_id, *, services=0, workflows=0, models=(0, 0, 0)):
    """models tuple = (active, inactive, deleted)."""
    base = abs(hash(member_id)) % 100000
    for i in range(services):
        db.add(Service(name=f"s{i}", created_by=member_id, surro_service_id=f"{member_id}-s{i}"))
    for i in range(workflows):
        db.add(Workflow(name=f"w{i}", created_by=member_id, surro_workflow_id=f"{member_id}-w{i}"))
    active_n, inactive_n, deleted_n = models
    seq = 0
    for _ in range(active_n):
        db.add(Model(surro_model_id=base + seq, created_by=member_id, is_active=True))
        seq += 1
    for _ in range(inactive_n):
        db.add(Model(surro_model_id=base + seq, created_by=member_id, is_active=False))
        seq += 1
    for _ in range(deleted_n):
        db.add(Model(
            surro_model_id=base + seq, created_by=member_id,
            is_active=True, deleted_at=datetime.utcnow(),
        ))
        seq += 1
    db.flush()


def test_me_summary_returns_only_own_assets(db, sample_member, admin_member):
    """다른 사용자 자산은 본인 카운트에서 제외."""
    _seed_for(db, sample_member.member_id, services=2, workflows=1, models=(1, 0, 0))
    _seed_for(db, admin_member.member_id, services=5, workflows=3, models=(4, 0, 0))

    with _client_for_user(db, sample_member) as client:
        resp = client.get("/api/v1/me/dashboard/summary")
        assert resp.status_code == 200
        data = resp.json()

    assert data["member_id"] == sample_member.member_id
    assert data["services"]["total"] == 2
    assert data["workflows"]["total"] == 1
    assert data["models"]["total"] == 1
    assert data["models"]["active"] == 1


def test_me_summary_split_active_inactive_deleted(db, sample_member):
    """본인 자산도 active/inactive/deleted 3분할 정상."""
    _seed_for(db, sample_member.member_id, models=(2, 1, 3))

    with _client_for_user(db, sample_member) as client:
        data = client.get("/api/v1/me/dashboard/summary").json()

    assert data["models"]["total"] == 6
    assert data["models"]["active"] == 2
    assert data["models"]["inactive"] == 1
    assert data["models"]["deleted"] == 3


def test_me_summary_admin_only_sees_own_when_using_me_endpoint(db, admin_member, sample_member):
    """admin이라도 /me/dashboard는 본인 자산만."""
    _seed_for(db, admin_member.member_id, services=1)
    _seed_for(db, sample_member.member_id, services=10)

    with _client_for_user(db, admin_member) as client:
        data = client.get("/api/v1/me/dashboard/summary").json()

    assert data["member_id"] == admin_member.member_id
    assert data["services"]["total"] == 1


def test_me_summary_empty_user_returns_zero_counts(db, sample_member):
    with _client_for_user(db, sample_member) as client:
        data = client.get("/api/v1/me/dashboard/summary").json()

    assert data["services"]["total"] == 0
    assert data["workflows"]["total"] == 0
    assert data["models"]["total"] == 0
    assert data["model_improvements"]["total"] == 0
    assert data["datasets"]["total"] == 0
    assert data["experiments"]["total"] == 0
    assert data["knowledge_bases"]["total"] == 0
    assert data["prompts"]["total"] == 0


def test_me_summary_requires_auth(db, sample_member):
    """auth 의존성 — overrides 없이는 인증 실패."""
    app.dependency_overrides.clear()
    with TestClient(app) as client:
        resp = client.get("/api/v1/me/dashboard/summary")
        assert resp.status_code == 401


# ---------- service-level scope filter unit tests ----------

class TestCountAssetMemberScope:
    def test_count_asset_with_member_id_filters(self, db, sample_member, admin_member):
        db.add(Model(surro_model_id=1, created_by=sample_member.member_id, is_active=True))
        db.add(Model(surro_model_id=2, created_by=admin_member.member_id, is_active=True))
        db.flush()

        sample_count = dashboard_service.count_asset(db, Model, member_id=sample_member.member_id)
        assert sample_count.total == 1
        assert sample_count.active == 1

        global_count = dashboard_service.count_asset(db, Model)
        assert global_count.total == 2

    def test_count_asset_member_scope_respects_soft_delete(self, db, sample_member):
        db.add(Model(surro_model_id=10, created_by=sample_member.member_id, is_active=True))
        db.add(Model(surro_model_id=11, created_by=sample_member.member_id, is_active=False))
        db.add(Model(
            surro_model_id=12, created_by=sample_member.member_id,
            deleted_at=datetime.utcnow(),
        ))
        db.flush()

        result = dashboard_service.count_asset(db, Model, member_id=sample_member.member_id)
        assert result.total == 3
        assert result.active == 1
        assert result.inactive == 1
        assert result.deleted == 1

    def test_count_asset_no_soft_delete_with_member(self, db, sample_member, admin_member):
        db.add(Service(name="a", created_by=sample_member.member_id, surro_service_id="a"))
        db.add(Service(name="b", created_by=admin_member.member_id, surro_service_id="b"))
        db.flush()
        result = dashboard_service.count_asset(db, Service, member_id=sample_member.member_id)
        assert result.total == 1
        assert result.active == 1
        assert result.inactive == 0
        assert result.deleted == 0
