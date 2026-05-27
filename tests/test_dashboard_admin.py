"""관리자 대시보드 라우트 + 서비스 통합 테스트."""
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_admin_user, get_current_user
from app.database import get_db
from app.main import app
from app.models import (
    Dataset,
    Experiment,
    KnowledgeBase,
    Member,
    Model,
    ModelImprovement,
    Prompt,
    Service,
    Workflow,
)
from app.services import dashboard_service


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


@contextmanager
def _client_with_non_admin(db, normal_user):
    """get_current_user는 override하지만 admin 가드는 그대로 둬서 403 검증."""
    def override_get_db():
        yield db

    def override_current():
        return normal_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_current
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _seed_assets(db, member_id):
    """샘플 자산 - soft-delete 도메인 1개씩 + 삭제된 1개, soft-delete 없는 도메인 2개씩."""
    # soft-delete 없는 도메인
    db.add(Service(name="s1", created_by=member_id, surro_service_id="srv-1"))
    db.add(Service(name="s2", created_by=member_id, surro_service_id="srv-2"))
    db.add(Workflow(name="w1", created_by=member_id, surro_workflow_id="wf-1"))

    # soft-delete 도메인 — active 1개, deleted 1개
    db.add(Model(surro_model_id=1, created_by=member_id, name="m-active"))
    deleted_model = Model(
        surro_model_id=2, created_by=member_id, name="m-deleted",
        deleted_at=datetime.utcnow(),
    )
    db.add(deleted_model)

    db.add(ModelImprovement(task_id="mi-1", source_model_id=1, created_by=member_id))
    db.add(Dataset(surro_dataset_id=10, created_by=member_id, name="ds-1"))
    db.add(Experiment(surro_experiment_id=20, created_by=member_id, name="exp-1"))
    db.add(KnowledgeBase(
        name="kb-1", collection_name="col-1",
        created_by=member_id, surro_knowledge_id=30,
    ))
    db.add(Prompt(
        name="p-1", content="hi", created_by=member_id, surro_prompt_id=40,
    ))
    db.flush()


# ---------- Admin guard ----------

def test_summary_blocks_non_admin(db, sample_member):
    """일반 사용자는 403."""
    with _client_with_non_admin(db, sample_member) as client:
        resp = client.get("/api/v1/admin/dashboard/summary")
        assert resp.status_code == 403


def test_users_top_blocks_non_admin(db, sample_member):
    with _client_with_non_admin(db, sample_member) as client:
        resp = client.get("/api/v1/admin/dashboard/users/top", params={"domain": "model"})
        assert resp.status_code == 403


# ---------- Summary ----------

def test_summary_basic_structure(db, admin_member, sample_member):
    _seed_assets(db, sample_member.member_id)

    with _client_with_admin(db, admin_member) as client:
        resp = client.get("/api/v1/admin/dashboard/summary")
        assert resp.status_code == 200
        data = resp.json()

    # 8 자산 도메인 + users + generated_at
    expected_keys = {
        "users", "services", "workflows", "models", "model_improvements",
        "datasets", "experiments", "knowledge_bases", "prompts", "generated_at",
    }
    assert expected_keys.issubset(data.keys())


def test_summary_soft_delete_split(db, admin_member, sample_member):
    """soft-delete 있는 도메인은 active/inactive/deleted 3분할, 없는 도메인은 deleted/inactive 모두 0."""
    _seed_assets(db, sample_member.member_id)

    with _client_with_admin(db, admin_member) as client:
        data = client.get("/api/v1/admin/dashboard/summary").json()

    # Service/Workflow는 soft-delete 없음
    assert data["services"]["deleted"] == 0
    assert data["services"]["inactive"] == 0
    assert data["services"]["active"] == data["services"]["total"] == 2
    assert data["workflows"]["deleted"] == 0
    assert data["workflows"]["inactive"] == 0
    assert data["workflows"]["total"] == 1

    # Model은 active 1, deleted 1, inactive 0 (is_active 기본 True)
    assert data["models"]["total"] == 2
    assert data["models"]["active"] == 1
    assert data["models"]["inactive"] == 0
    assert data["models"]["deleted"] == 1


def test_summary_inactive_asset_excluded_from_active(db, admin_member, sample_member):
    """is_active=False 자산은 active에서 제외되어 inactive로 분류."""
    db.add(Model(surro_model_id=1, created_by=sample_member.member_id, is_active=True))
    db.add(Model(surro_model_id=2, created_by=sample_member.member_id, is_active=False))
    db.add(Model(
        surro_model_id=3, created_by=sample_member.member_id,
        is_active=True, deleted_at=datetime.utcnow(),
    ))
    db.flush()

    with _client_with_admin(db, admin_member) as client:
        data = client.get("/api/v1/admin/dashboard/summary").json()

    assert data["models"]["total"] == 3
    assert data["models"]["active"] == 1
    assert data["models"]["inactive"] == 1
    assert data["models"]["deleted"] == 1


def test_summary_user_counts(db, admin_member, sample_member):
    """사용자 카운트 — 가입자 2명(admin+sample), 권한 분포."""
    with _client_with_admin(db, admin_member) as client:
        data = client.get("/api/v1/admin/dashboard/summary").json()

    users = data["users"]
    assert users["total"] == 2
    assert users["active"] == 2
    assert users["inactive"] == 0
    assert users["recent7d"] >= 0  # 가입 시각이 시드 시점이라 0~2
    assert users["by_role"].get("admin") == 1
    assert users["by_role"].get("user") == 1


def test_summary_inactive_user_counted(db, admin_member, sample_member):
    """is_active=False 사용자는 inactive로 분리."""
    sample_member.is_active = False
    db.flush()

    with _client_with_admin(db, admin_member) as client:
        data = client.get("/api/v1/admin/dashboard/summary").json()

    assert data["users"]["inactive"] == 1
    assert data["users"]["active"] == 1


# ---------- Users top ----------

def test_users_top_returns_owners_sorted(db, admin_member, sample_member):
    """도메인별 보유 상위 사용자."""
    _seed_assets(db, sample_member.member_id)
    # admin도 모델 1개 보유
    db.add(Model(surro_model_id=99, created_by=admin_member.member_id, name="admin-m"))
    db.flush()

    with _client_with_admin(db, admin_member) as client:
        resp = client.get(
            "/api/v1/admin/dashboard/users/top",
            params={"domain": "model", "size": 5},
        )
        assert resp.status_code == 200
        body = resp.json()

    assert body["domain"] == "model"
    items = body["items"]
    # sample_member는 active 1개, admin은 1개 (둘다 deleted 제외)
    assert len(items) >= 2
    # 가장 많이 보유한 사람이 첫 번째 (또는 동률)
    counts = [item["count"] for item in items]
    assert counts == sorted(counts, reverse=True)


def test_users_top_filters_soft_deleted(db, admin_member, sample_member):
    """soft-delete된 자산은 top에서 제외."""
    # sample_member가 model 5개 만들고 3개 삭제 → active 2개
    for i in range(2):
        db.add(Model(surro_model_id=100 + i, created_by=sample_member.member_id, name=f"a{i}"))
    for i in range(3):
        db.add(Model(
            surro_model_id=200 + i, created_by=sample_member.member_id,
            name=f"d{i}", deleted_at=datetime.utcnow(),
        ))
    db.flush()

    with _client_with_admin(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/users/top",
            params={"domain": "model"},
        ).json()

    sample_item = next((i for i in body["items"] if i["member_id"] == sample_member.member_id), None)
    assert sample_item is not None
    assert sample_item["count"] == 2  # deleted 3개 제외


def test_users_top_filters_inactive(db, admin_member, sample_member):
    """is_active=False 자산도 top 카운트에서 제외."""
    db.add(Model(surro_model_id=300, created_by=sample_member.member_id, is_active=True))
    db.add(Model(surro_model_id=301, created_by=sample_member.member_id, is_active=False))
    db.add(Model(surro_model_id=302, created_by=sample_member.member_id, is_active=False))
    db.flush()

    with _client_with_admin(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/users/top",
            params={"domain": "model"},
        ).json()

    sample_item = next((i for i in body["items"] if i["member_id"] == sample_member.member_id), None)
    assert sample_item is not None
    assert sample_item["count"] == 1  # inactive 2개 제외


def test_users_top_empty_returns_empty_list(db, admin_member):
    with _client_with_admin(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/users/top",
            params={"domain": "experiment"},
        ).json()
    assert body["items"] == []


def test_users_top_invalid_domain_returns_422(db, admin_member):
    with _client_with_admin(db, admin_member) as client:
        resp = client.get(
            "/api/v1/admin/dashboard/users/top",
            params={"domain": "bogus"},
        )
    # Literal 검증 실패
    assert resp.status_code == 422


# ---------- Infra (mock) ----------

def test_infra_status_returns_clusters(db, admin_member):
    with _client_with_admin(db, admin_member) as client:
        resp = client.get("/api/v1/admin/dashboard/infra/status")
        assert resp.status_code == 200
        body = resp.json()
    assert body["has_data"] is True
    assert len(body["clusters"]) >= 1
    assert all("status" in c and "last_checked_at" in c for c in body["clusters"])


def test_infra_nodes_accelerator_shape(db, admin_member):
    with _client_with_admin(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/infra/nodes",
            params={"cluster": "any-cloud-dev"},
        ).json()

    assert body["cluster"]["name"] == "any-cloud-dev"
    assert len(body["nodes"]) >= 1

    # 가속기 보유한 노드 찾기
    node_with_accel = next(
        (n for n in body["nodes"] if n["resources"]["accelerators"]),
        None,
    )
    assert node_with_accel is not None
    accels = node_with_accel["resources"]["accelerators"]
    kinds = {a["kind"] for a in accels}
    # GPU는 최소 1개, NPU placeholder 포함
    assert "gpu" in kinds
    assert any(a["kind"] == "npu" and a["status"] == "not_available" for a in accels)


def test_infra_resources_filters_by_type(db, admin_member):
    with _client_with_admin(db, admin_member) as client:
        # cpu만 요청
        cpu = client.get(
            "/api/v1/admin/dashboard/infra/resources",
            params={"cluster": "x", "resource_type": "cpu"},
        ).json()
        accel = client.get(
            "/api/v1/admin/dashboard/infra/resources",
            params={"cluster": "x", "resource_type": "accelerator"},
        ).json()

    assert cpu["resource_type"] == "cpu"
    # 노드별 entry에 cpu만 채워져 있어야 함
    for entry in cpu["nodes"]:
        assert entry["cpu"] is not None
        assert entry["memory"] is None
        assert entry["accelerators"] is None

    for entry in accel["nodes"]:
        assert entry["cpu"] is None
        # accelerators는 리스트 (가속기 없는 노드도 빈 리스트)
        assert entry["accelerators"] is not None


def test_infra_resources_invalid_type_returns_422(db, admin_member):
    with _client_with_admin(db, admin_member) as client:
        resp = client.get(
            "/api/v1/admin/dashboard/infra/resources",
            params={"cluster": "x", "resource_type": "bogus"},
        )
    assert resp.status_code == 422


# ---------- service-level unit tests ----------

class TestDashboardServiceUnit:
    def test_count_asset_no_soft_delete(self, db, sample_member):
        db.add(Service(name="s", created_by=sample_member.member_id, surro_service_id="x"))
        db.flush()
        result = dashboard_service.count_asset(db, Service)
        assert result.total == 1
        assert result.active == 1
        assert result.inactive == 0
        assert result.deleted == 0

    def test_count_asset_with_soft_delete(self, db, sample_member):
        # active 1, inactive 1, deleted 1
        db.add(Model(surro_model_id=1, created_by=sample_member.member_id, is_active=True))
        db.add(Model(surro_model_id=2, created_by=sample_member.member_id, is_active=False))
        db.add(Model(
            surro_model_id=3, created_by=sample_member.member_id,
            deleted_at=datetime.utcnow(),
        ))
        db.flush()
        result = dashboard_service.count_asset(db, Model)
        assert result.total == 3
        assert result.active == 1
        assert result.inactive == 1
        assert result.deleted == 1

    def test_top_users_unknown_domain_raises(self, db):
        with pytest.raises(ValueError):
            dashboard_service.top_users_by_domain(db, "nope")
