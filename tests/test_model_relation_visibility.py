"""
모델 상세 응답의 parent_model/child_models 노드 visibility 보강 테스트.

MLOps 원본 노드는 id/name/description만 주고 visibility가 없다. 게이트웨이가
현재 사용자에게 접근 가능한 gateway DB 매핑으로 각 노드(재귀 포함)를 보강한다.
"""
import asyncio
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models.model import Model
from app.schemas.model import ModelResponse
from app.services.model_service import model_service


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


def _seed_model_mapping(db, member, surro_model_id: int, is_catalog: bool):
    db.add(
        Model(
            name=f"model-{surro_model_id}",
            description="gateway mapping",
            created_by=member.member_id,
            surro_model_id=surro_model_id,
            is_catalog=is_catalog,
        )
    )
    db.flush()


def _model(
    model_id: int,
    visibility: Optional[str] = None,
    parent_model: Optional[Dict[str, Any]] = None,
    child_models: Optional[List[Dict[str, Any]]] = None,
) -> ModelResponse:
    return ModelResponse(
        id=model_id,
        name=f"model-{model_id}",
        visibility=visibility,
        parent_model=parent_model,
        child_models=child_models or [],
        created_at=datetime(2026, 4, 1, 12, 0, 0),
        updated_at=datetime(2026, 4, 1, 12, 0, 0),
    )


def test_injects_visibility_into_parent_and_child_tree(db, sample_member, monkeypatch):
    for surro_model_id, is_catalog in (
        (14, True),
        (3, True),
        (20, False),
        (21, True),
        (22, False),
    ):
        _seed_model_mapping(db, sample_member, surro_model_id, is_catalog)

    # 14의 upstream 상세: 노드에 visibility 없음 (MLOps 원본 형태)
    root = _model(
        14,
        visibility="CUSTOM",
        parent_model={"id": 3, "name": "parent", "description": "p", "parent_model": None},
        child_models=[
            {
                "id": 20,
                "name": "child-a",
                "description": "ca",
                "child_models": [
                    {"id": 21, "name": "grandchild", "description": "gc", "child_models": []}
                ],
            },
            {"id": 22, "name": "child-b", "description": "cb", "child_models": []},
        ],
    )
    calls: List[int] = []

    async def fake_get_model(model_id, user_info=None):
        calls.append(model_id)
        assert model_id == 14
        return root

    monkeypatch.setattr(
        "app.services.model_service.model_service.get_model", fake_get_model
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models/14")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["visibility"] == "CUSTOM"  # 루트 자체는 passthrough
    assert data["parent_model"]["visibility"] == "CATALOG"
    assert data["child_models"][0]["visibility"] == "CUSTOM"
    assert data["child_models"][0]["child_models"][0]["visibility"] == "CATALOG"  # 재귀 주입
    assert data["child_models"][1]["visibility"] == "CUSTOM"
    # upstream은 루트 상세만 1회 조회하고 관계 visibility는 gateway DB 한 번으로 계산
    assert calls == [14]


def test_unmapped_relation_visibility_is_null(db, sample_member, monkeypatch):
    _seed_model_mapping(db, sample_member, 14, True)
    _seed_model_mapping(db, sample_member, 20, True)

    root = _model(
        14,
        visibility="CUSTOM",
        child_models=[
            {"id": 20, "name": "child-a", "description": "ca", "child_models": []},
            {"id": 99, "name": "child-b", "description": "cb", "child_models": []},
        ],
    )

    async def fake_get_model(model_id, user_info=None):
        assert model_id == 14
        return root

    monkeypatch.setattr(
        "app.services.model_service.model_service.get_model", fake_get_model
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models/14")

    assert response.status_code == 200, response.text
    data = response.json()
    by_id = {c["id"]: c for c in data["child_models"]}
    assert by_id[20]["visibility"] == "CATALOG"
    assert by_id[99]["visibility"] is None


def test_other_users_custom_relation_visibility_is_hidden(
    db, sample_member, admin_member, monkeypatch
):
    _seed_model_mapping(db, sample_member, 14, True)
    _seed_model_mapping(db, admin_member, 20, False)
    root = _model(
        14,
        child_models=[
            {"id": 20, "name": "private-child", "description": None, "child_models": []}
        ],
    )

    async def fake_get_model(model_id, user_info=None):
        assert model_id == 14
        return root

    monkeypatch.setattr(
        "app.services.model_service.model_service.get_model", fake_get_model
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models/14")

    assert response.status_code == 200, response.text
    assert response.json()["child_models"][0]["visibility"] is None


def test_get_model_upstream_5xx_maps_to_502_without_raw_body(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(500, text="internal upstream details")

    monkeypatch.setattr(model_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(model_service.get_model(14))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "upstream service error"


def test_get_model_4xx_uses_structured_detail(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(403, json={"detail": "model access denied"})

    monkeypatch.setattr(model_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(model_service.get_model(14))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "model access denied"
