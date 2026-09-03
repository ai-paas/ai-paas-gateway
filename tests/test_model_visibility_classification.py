"""
모델 목록 분류(CATALOG/CUSTOM) 계약 테스트.

분류의 단일 소스는 MLOps `visibility` 필드이고, gateway DB 매핑은
노출 권한(커스텀=본인만)과 soft-delete 제외에만 쓰인다. is_catalog는
MLOps visibility의 로컬 캐시로, 목록 조회 시 read-through로 정정된다.
"""
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Optional

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models.model import Model
from app.routes.model import _derive_is_catalog
from app.scheduler import job_reconcile_model_visibility
from app.schemas.model import ModelCreateResponse, ModelResponse
from app.services.model_service import normalize_visibility
from scripts.sync_models import _build_reconciliation_plan


@contextmanager
def _client_with_overrides(db, current_user):
    def override_get_db():
        yield db

    def override_get_current_user():
        return current_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _seed_mapping(db, member, surro_model_id: int, is_catalog: bool, deleted: bool = False):
    db.add(
        Model(
            name=f"model-{surro_model_id}",
            created_by=member.member_id,
            surro_model_id=surro_model_id,
            is_catalog=is_catalog,
            deleted_at=datetime(2026, 7, 1) if deleted else None,
            is_active=not deleted,
        )
    )
    db.flush()


def _model(model_id: int, visibility: Optional[str] = None) -> ModelResponse:
    return ModelResponse(
        id=model_id,
        name=f"model-{model_id}",
        visibility=visibility,
        created_at=datetime(2026, 4, 1, 12, 0, 0),
        updated_at=datetime(2026, 4, 1, 12, 0, 0),
    )


def _fake_get_models(upstream_models):
    """MLOps 목록 fake — 실제 upstream처럼 visibility 파라미터를 대소문자 무관 필터."""

    async def fake(skip=0, limit=100, search=None, provider_id=None,
                   type_id=None, format_id=None, filter_type=None, user_info=None):
        if filter_type:
            want = filter_type.upper()
            return [
                m for m in upstream_models
                if (normalize_visibility(m.visibility) or "") == want
            ]
        return list(upstream_models)

    return fake


UPSTREAM = [
    _model(1, visibility="CATALOG"),   # 정상 카탈로그 (매핑 정합)
    _model(2, visibility="CUSTOM"),    # 내(testuser) 커스텀
    _model(3, visibility="CUSTOM"),    # 타인(admin) 커스텀 → 나에게 비노출
    _model(4, visibility="CUSTOM"),    # 캐시가 catalog로 어긋난 파생 모델 (실사례 id 14/15)
    _model(5, visibility="CATALOG"),   # soft-delete된 카탈로그 → 비노출 (실사례 id 24)
    _model(6, visibility="CATALOG"),   # gateway 매핑 없음 → 비노출
]


def _seed_default(db, sample_member, admin_member):
    _seed_mapping(db, admin_member, 1, is_catalog=True)
    _seed_mapping(db, sample_member, 2, is_catalog=False)
    _seed_mapping(db, admin_member, 3, is_catalog=False)
    _seed_mapping(db, admin_member, 4, is_catalog=True)   # 어긋난 캐시
    _seed_mapping(db, admin_member, 5, is_catalog=True, deleted=True)
    # 6: 매핑 없음


def test_catalog_filter_follows_upstream_visibility(db, sample_member, admin_member, monkeypatch):
    _seed_default(db, sample_member, admin_member)
    monkeypatch.setattr(
        "app.routes.model.model_service.get_models", _fake_get_models(UPSTREAM)
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models", params={"visibility": "catalog"})

    assert response.status_code == 200, response.text
    ids = {m["id"] for m in response.json()["data"]}
    # 4는 캐시가 catalog여도 MLOps CUSTOM이므로 제외, 5는 soft-delete, 6은 무매핑
    assert ids == {1}


def test_custom_filter_shows_only_my_custom(db, sample_member, admin_member, monkeypatch):
    _seed_default(db, sample_member, admin_member)
    monkeypatch.setattr(
        "app.routes.model.model_service.get_models", _fake_get_models(UPSTREAM)
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models", params={"visibility": "custom"})

    assert response.status_code == 200, response.text
    ids = {m["id"] for m in response.json()["data"]}
    assert ids == {2}  # 3(타인), 4(타인 파생)는 비노출


def test_default_list_is_catalog_plus_my_custom(db, sample_member, admin_member, monkeypatch):
    _seed_default(db, sample_member, admin_member)
    monkeypatch.setattr(
        "app.routes.model.model_service.get_models", _fake_get_models(UPSTREAM)
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models")

    assert response.status_code == 200, response.text
    body = response.json()
    assert {m["id"] for m in body["data"]} == {1, 2}
    assert body["total"] == 2
    assert set(body.keys()) == {"data", "total", "page", "size"}


def test_unknown_upstream_visibility_fails_closed(
    db, sample_member, admin_member, monkeypatch
):
    _seed_mapping(db, admin_member, 7, is_catalog=True)
    monkeypatch.setattr(
        "app.routes.model.model_service.get_models",
        _fake_get_models([_model(7, visibility="PRIVATE")]),
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models")

    assert response.status_code == 200, response.text
    assert response.json()["data"] == []


def test_filter_type_alias_and_uppercase_visibility(db, sample_member, admin_member, monkeypatch):
    _seed_default(db, sample_member, admin_member)
    monkeypatch.setattr(
        "app.routes.model.model_service.get_models", _fake_get_models(UPSTREAM)
    )

    with _client_with_overrides(db, sample_member) as client:
        legacy = client.get("/api/v1/models", params={"filter_type": "catalog"})
        upper = client.get("/api/v1/models", params={"visibility": "CATALOG"})
        mixed = client.get("/api/v1/models", params={"visibility": "CaTaLoG"})
        invalid = client.get("/api/v1/models", params={"visibility": "everything"})

    assert {m["id"] for m in legacy.json()["data"]} == {1}
    assert {m["id"] for m in upper.json()["data"]} == {1}
    assert {m["id"] for m in mixed.json()["data"]} == {1}
    assert invalid.status_code == 422


def test_list_read_through_syncs_is_catalog_cache(db, sample_member, admin_member, monkeypatch):
    _seed_default(db, sample_member, admin_member)
    monkeypatch.setattr(
        "app.routes.model.model_service.get_models", _fake_get_models(UPSTREAM)
    )

    with _client_with_overrides(db, sample_member) as client:
        client.get("/api/v1/models")

    synced = db.query(Model).filter(Model.surro_model_id == 4).one()
    assert synced.is_catalog is False  # MLOps CUSTOM으로 정정
    assert synced.updated_by == "visibility-sync"
    deleted_row = db.query(Model).filter(Model.surro_model_id == 5).one()
    assert deleted_row.is_catalog is True  # soft-delete 행도 캐시는 유지/정정


def test_dedicated_endpoints_follow_visibility(db, sample_member, admin_member, monkeypatch):
    """admin 시점: /custom-models에 카탈로그가 섞이지 않고, /model-catalog는 CATALOG만."""
    _seed_default(db, sample_member, admin_member)
    monkeypatch.setattr(
        "app.routes.model.model_service.get_models", _fake_get_models(UPSTREAM)
    )

    with _client_with_overrides(db, admin_member) as client:
        custom = client.get("/api/v1/models/custom-models")
        catalog = client.get("/api/v1/models/model-catalog")

    # admin이 만든 1(CATALOG)은 custom 페이지에서 제외, 3/4(CUSTOM)만
    assert {m["id"] for m in custom.json()["data"]} == {3, 4}
    assert {m["id"] for m in catalog.json()["data"]} == {1}


def test_create_model_mapping_uses_response_visibility(db, admin_member, monkeypatch):
    """admin이 등록해도 MLOps가 CUSTOM이라 하면 커스텀으로 매핑 (파생 모델 케이스)."""

    async def fake_create_model(model_data, file_data=None, file_name=None, user_info=None):
        return ModelCreateResponse(
            id=77, name=model_data.name, visibility="CUSTOM",
            created_at=datetime(2026, 7, 31), updated_at=datetime(2026, 7, 31),
        )

    monkeypatch.setattr("app.routes.model.model_service.create_model", fake_create_model)

    with _client_with_overrides(db, admin_member) as client:
        response = client.post(
            "/api/v1/models",
            data={"name": "derived", "provider_id": 1, "type_id": 1, "format_id": 1},
        )

    assert response.status_code == 200, response.text
    mapping = db.query(Model).filter(Model.surro_model_id == 77).one()
    assert mapping.is_catalog is False


def test_derive_is_catalog_does_not_use_role_fallback():
    assert _derive_is_catalog("CATALOG") is True
    assert _derive_is_catalog("custom") is False
    assert _derive_is_catalog(None) is False
    assert _derive_is_catalog("") is False
    assert _derive_is_catalog("PRIVATE") is False


def test_admin_create_without_visibility_is_custom(db, admin_member, monkeypatch):
    async def fake_create_model(model_data, file_data=None, file_name=None, user_info=None):
        return ModelCreateResponse(
            id=78, name=model_data.name, visibility=None,
            created_at=datetime(2026, 7, 31), updated_at=datetime(2026, 7, 31),
        )

    monkeypatch.setattr("app.routes.model.model_service.create_model", fake_create_model)

    with _client_with_overrides(db, admin_member) as client:
        response = client.post(
            "/api/v1/models",
            data={"name": "admin-custom", "provider_id": 1, "type_id": 1, "format_id": 1},
        )

    assert response.status_code == 200, response.text
    mapping = db.query(Model).filter(Model.surro_model_id == 78).one()
    assert mapping.created_by == admin_member.member_id
    assert mapping.is_catalog is False


def test_reconciliation_plan_only_maps_unmapped_models_to_admin():
    existing_catalog = Model(
        surro_model_id=1, created_by="user", is_catalog=True, is_active=True,
    )
    existing_custom = Model(
        surro_model_id=2, created_by="user", is_catalog=False, is_active=True,
    )
    deleted_catalog = Model(
        surro_model_id=5, created_by="user", is_catalog=True, is_active=False,
        deleted_at=datetime(2026, 7, 1),
    )
    external = [
        SimpleNamespace(id=1, name="existing-catalog", visibility=None),
        SimpleNamespace(id=2, name="existing-custom", visibility=None),
        SimpleNamespace(id=3, name="new-catalog", visibility="CATALOG"),
        SimpleNamespace(id=4, name="new-custom", visibility="CUSTOM"),
        SimpleNamespace(id=5, name="restored-catalog", visibility=None),
        SimpleNamespace(id=6, name="temporary-custom", visibility=None),
    ]

    plan = _build_reconciliation_plan(
        external, [existing_catalog, existing_custom, deleted_catalog]
    )
    creates = {item["surro_model_id"]: item for item in plan["creates"]}

    assert set(creates) == {3, 4, 5, 6}
    assert creates[3]["is_catalog"] is True
    assert creates[4]["is_catalog"] is False
    assert creates[5]["is_catalog"] is True
    assert creates[5]["temporary"] is False
    assert creates[6]["is_catalog"] is False
    assert creates[6]["temporary"] is True
    assert plan["updates"] == []


def test_reconciliation_plan_rejects_unknown_visibility():
    with pytest.raises(ValueError, match="Unsupported visibility for model 7"):
        _build_reconciliation_plan(
            [SimpleNamespace(id=7, name="unknown", visibility="PRIVATE")], []
        )


def test_detail_rejects_stale_catalog_cache_for_other_users_custom(
    db, sample_member, admin_member, monkeypatch
):
    _seed_mapping(db, admin_member, 80, is_catalog=True)

    async def fake_get_model(model_id, user_info=None):
        return _model(model_id, visibility="CUSTOM")

    monkeypatch.setattr("app.routes.model.model_service.get_model", fake_get_model)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models/80")

    assert response.status_code == 404
    mapping = db.query(Model).filter(Model.surro_model_id == 80).one()
    assert mapping.is_catalog is False


def test_detail_allows_upstream_catalog_despite_stale_custom_cache(
    db, sample_member, admin_member, monkeypatch
):
    _seed_mapping(db, admin_member, 81, is_catalog=False)

    async def fake_get_model(model_id, user_info=None):
        return _model(model_id, visibility="CATALOG")

    monkeypatch.setattr("app.routes.model.model_service.get_model", fake_get_model)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models/81")

    assert response.status_code == 200, response.text
    mapping = db.query(Model).filter(Model.surro_model_id == 81).one()
    assert mapping.is_catalog is True


def test_visibility_reconcile_fetches_all_upstream_pages(monkeypatch):
    calls = []
    captured = {}

    class _FakeService:
        async def get_models(self, skip=0, limit=100):
            calls.append((skip, limit))
            if skip == 0:
                return [
                    SimpleNamespace(id=model_id, visibility="CATALOG")
                    for model_id in range(1, 1001)
                ]
            if skip == 1000:
                return [SimpleNamespace(id=1001, visibility="CUSTOM")]
            return []

        async def close(self):
            captured["closed"] = True

    class _FakeDB:
        def close(self):
            captured["db_closed"] = True

    def fake_sync_visibility_cache(db, visibility_map):
        captured["db"] = db
        captured["visibility_map"] = visibility_map
        return len(visibility_map)

    monkeypatch.setattr("app.scheduler.SessionLocal", _FakeDB)
    monkeypatch.setattr("app.services.model_service.ModelService", _FakeService)
    monkeypatch.setattr(
        "app.cruds.model_crud.sync_visibility_cache",
        fake_sync_visibility_cache,
    )

    job_reconcile_model_visibility()

    assert calls == [(0, 1000), (1000, 1000)]
    assert len(captured["visibility_map"]) == 1001
    assert captured["visibility_map"][1001] is False
    assert captured["closed"] is True
    assert captured["db_closed"] is True
