"""task-types 라우트의 source_model_id 통과 + 권한 검증.

MLOps spec에 추가된 source_model_id 쿼리가 게이트웨이 라우트→서비스→upstream
params에 그대로 전달되는지, 그리고 권한이 없는 타 사용자 모델이면 차단되는지
확인한다 (lockstep 규약 + 메모 4번 권한 매핑 규약).
"""
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models.model import Model


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


@pytest.fixture
def captured_params():
    return {}


def _install_fake_service(monkeypatch, captured):
    async def fake_get_task_types(category=None, source_model_id=None, user_info=None):
        captured["category"] = category
        captured["source_model_id"] = source_model_id
        return []

    monkeypatch.setattr(
        "app.routes.model_improvement.model_improvement_service.get_task_types",
        fake_get_task_types,
    )


def _add_model_mapping(db, member_id: str, surro_model_id: int):
    """주어진 사용자가 소유한 게이트웨이 DB 모델 매핑 생성."""
    model = Model(
        surro_model_id=surro_model_id,
        created_by=member_id,
        is_active=True,
    )
    db.add(model)
    db.flush()
    return model


def test_task_types_passes_source_model_id_when_user_owns_model(
    db, sample_member, monkeypatch, captured_params
):
    _add_model_mapping(db, sample_member.member_id, surro_model_id=42)
    _install_fake_service(monkeypatch, captured_params)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(
            "/api/v1/model-improvements/task-types",
            params={"source_model_id": 42, "category": "optimization"},
        )

    assert response.status_code == 200, response.text
    assert captured_params["source_model_id"] == 42
    assert captured_params["category"] == "optimization"


def test_task_types_returns_404_when_user_does_not_own_model(
    db, sample_member, monkeypatch, captured_params
):
    """타 사용자 모델 ID는 게이트웨이에서 차단되어야 한다 — upstream 호출 금지."""
    _add_model_mapping(db, "other-owner", surro_model_id=999)

    upstream_called = {"hit": False}

    async def fake_get_task_types(**_kwargs):
        upstream_called["hit"] = True
        return []

    monkeypatch.setattr(
        "app.routes.model_improvement.model_improvement_service.get_task_types",
        fake_get_task_types,
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(
            "/api/v1/model-improvements/task-types",
            params={"source_model_id": 999},
        )

    assert response.status_code == 404, response.text
    assert upstream_called["hit"] is False


def test_task_types_admin_bypasses_ownership_check(
    db, admin_member, monkeypatch, captured_params
):
    """admin은 타 사용자 모델 ID도 조회 가능 — 단 게이트웨이 DB 매핑은 있어야 한다."""
    _add_model_mapping(db, "other-owner", surro_model_id=555)
    _install_fake_service(monkeypatch, captured_params)

    with _client_with_overrides(db, admin_member) as client:
        response = client.get(
            "/api/v1/model-improvements/task-types",
            params={"source_model_id": 555},
        )

    assert response.status_code == 200, response.text
    assert captured_params["source_model_id"] == 555


def test_task_types_admin_404_when_model_not_in_gateway_db(
    db, admin_member, monkeypatch, captured_params
):
    """admin이라도 외부 ID만으로 upstream 호출 금지 — 게이트웨이 DB에 매핑이 없으면 404.

    메모 4번 규약: 외부 ID + 게이트웨이 DB 매핑 동시 확인.
    """
    upstream_called = {"hit": False}

    async def fake_get_task_types(**_kwargs):
        upstream_called["hit"] = True
        return []

    monkeypatch.setattr(
        "app.routes.model_improvement.model_improvement_service.get_task_types",
        fake_get_task_types,
    )

    with _client_with_overrides(db, admin_member) as client:
        response = client.get(
            "/api/v1/model-improvements/task-types",
            params={"source_model_id": 9999},
        )

    assert response.status_code == 404, response.text
    assert upstream_called["hit"] is False


def test_task_types_admin_404_when_model_soft_deleted(
    db, admin_member, monkeypatch, captured_params
):
    """admin이라도 soft-delete된 모델은 404."""
    from datetime import datetime, timezone
    model = _add_model_mapping(db, "other-owner", surro_model_id=777)
    model.deleted_at = datetime.now(timezone.utc)
    model.deleted_by = "other-owner"
    model.is_active = False
    db.flush()

    upstream_called = {"hit": False}

    async def fake_get_task_types(**_kwargs):
        upstream_called["hit"] = True
        return []

    monkeypatch.setattr(
        "app.routes.model_improvement.model_improvement_service.get_task_types",
        fake_get_task_types,
    )

    with _client_with_overrides(db, admin_member) as client:
        response = client.get(
            "/api/v1/model-improvements/task-types",
            params={"source_model_id": 777},
        )

    assert response.status_code == 404, response.text
    assert upstream_called["hit"] is False


def test_task_types_omits_source_model_id_when_not_provided(
    db, sample_member, monkeypatch, captured_params
):
    _install_fake_service(monkeypatch, captured_params)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/model-improvements/task-types")

    assert response.status_code == 200, response.text
    assert captured_params["source_model_id"] is None
    assert captured_params["category"] is None


def test_service_get_task_types_includes_source_model_id_in_upstream_params(monkeypatch):
    """서비스 함수가 upstream 호출 시 params에 source_model_id를 넣는지 직접 검증."""
    from app.services import model_improvement_service as mi_module

    captured = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return []

    async def fake_request(method, url, user_info=None, params=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return FakeResponse()

    monkeypatch.setattr(
        mi_module.model_improvement_service,
        "_make_authenticated_request",
        fake_request,
    )

    import asyncio
    asyncio.run(
        mi_module.model_improvement_service.get_task_types(
            category="optimization",
            source_model_id=7,
            user_info={"member_id": "x", "role": "user", "name": "x"},
        )
    )

    assert captured["url"].endswith("/model-improvements/task-types")
    assert captured["params"] == {"category": "optimization", "source_model_id": 7}
