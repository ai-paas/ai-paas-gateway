import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models.model import Model
from app.schemas.model import (
    ModelFileDownloadUrlResponse,
    ModelFileListResponse,
    ModelFileStorageType,
)
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


def _seed_mapping(db, member_id: str, model_id: int, *, is_catalog: bool = False):
    db.add(
        Model(
            name=f"model-{model_id}",
            created_by=member_id,
            surro_model_id=model_id,
            is_catalog=is_catalog,
        )
    )
    db.flush()


def _file(name: str, size_bytes: int, day: int):
    return {
        "name": name,
        "size_bytes": size_bytes,
        "last_modified": datetime(2026, 7, day, 4, 11, 22, tzinfo=timezone.utc),
        "download_url": f"/upstream/files/download-url?name={name}",
    }


def _file_list(
        model_id: int = 12,
        *,
        files=None,
        next_cursor=None,
        model_name: str = "facebook/detr-resnet-50",
        storage_type: ModelFileStorageType = ModelFileStorageType.MLFLOW,
        location: str | None = "8/run/artifacts/facebook-detr-resnet-50",
        message: str | None = None,
) -> ModelFileListResponse:
    if files is None:
        files = [_file("data/model.safetensors", 167501120, 2)]
    return ModelFileListResponse(
        model_id=model_id,
        model_name=model_name,
        storage_type=storage_type,
        location=location,
        files=files,
        next_cursor=next_cursor,
        message=message,
    )


def test_model_files_route_paginates_sorts_and_rewrites_download_links(
        db, sample_member, monkeypatch
):
    _seed_mapping(db, sample_member.member_id, 12)
    captured = {}

    async def fake_get_all_model_files(model_id, user_info=None):
        captured.update(model_id=model_id, user_info=user_info)
        return _file_list(
            model_id,
            files=[
                _file("config.json", 100, 2),
                _file("data/model.safetensors", 300, 3),
                _file("tokenizer.json", 200, 1),
            ],
        )

    monkeypatch.setattr(
        "app.routes.model.model_service.get_all_model_files",
        fake_get_all_model_files,
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(
            "/api/v1/models/12/files",
            params={"page": 1, "size": 2, "sort": "-size_bytes"},
        )

    assert response.status_code == 200, response.text
    assert captured == {
        "model_id": 12,
        "user_info": {
            "member_id": sample_member.member_id,
            "role": sample_member.role,
            "name": sample_member.name,
        },
    }
    body = response.json()
    assert set(body) == {"data", "total", "page", "size"}
    assert (body["total"], body["page"], body["size"]) == (3, 1, 2)
    assert [item["name"] for item in body["data"]] == [
        "data/model.safetensors",
        "tokenizer.json",
    ]
    assert body["data"][0]["download_url"] == (
        "/api/v1/models/12/files/download-url?name=data%2Fmodel.safetensors"
    )


def test_model_files_route_rejects_invalid_sort_before_upstream(
        db, sample_member, monkeypatch
):
    _seed_mapping(db, sample_member.member_id, 12)
    called = False

    async def fake_get_all_model_files(model_id, user_info=None):
        nonlocal called
        called = True
        return _file_list(model_id)

    monkeypatch.setattr(
        "app.routes.model.model_service.get_all_model_files",
        fake_get_all_model_files,
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(
            "/api/v1/models/12/files",
            params={"sort": "unsupported"},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid sort field: unsupported"
    assert called is False


def test_catalog_model_files_are_available_to_other_users(
        db, sample_member, admin_member, monkeypatch
):
    _seed_mapping(db, admin_member.member_id, 31, is_catalog=True)

    async def fake_get_all_model_files(model_id, user_info=None):
        return _file_list(
            model_id,
            files=[],
            model_name="gpt-oss-20b",
            storage_type=ModelFileStorageType.OLLAMA,
            location="ollama-model-12-gpt-oss-20b",
            message="Ollama가 관리하는 볼륨이라 파일 목록을 제공하지 않습니다.",
        )

    monkeypatch.setattr(
        "app.routes.model.model_service.get_all_model_files",
        fake_get_all_model_files,
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models/31/files")

    assert response.status_code == 200, response.text
    assert response.json() == {"data": [], "total": 0, "page": 1, "size": 20}


def test_other_users_custom_model_is_rejected_before_upstream(
        db, sample_member, admin_member, monkeypatch
):
    _seed_mapping(db, admin_member.member_id, 60, is_catalog=False)
    called = False

    async def fake_get_all_model_files(model_id, user_info=None):
        nonlocal called
        called = True
        return _file_list(model_id)

    monkeypatch.setattr(
        "app.routes.model.model_service.get_all_model_files",
        fake_get_all_model_files,
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models/60/files")

    assert response.status_code == 404
    assert response.json()["detail"] == "Model 60 not found or access denied"
    assert called is False


def test_download_url_route_passes_file_name_without_path_rewriting(
        db, sample_member, monkeypatch
):
    _seed_mapping(db, sample_member.member_id, 12)
    captured = {}

    async def fake_get_download_url(model_id, name, user_info=None):
        captured.update(model_id=model_id, name=name, user_info=user_info)
        return ModelFileDownloadUrlResponse(
            model_id=model_id,
            name=name,
            size_bytes=167501120,
            download_url="https://storage.example.invalid/object?signature=test",
            expires_at=datetime(2026, 8, 18, 6, 45, 36, tzinfo=timezone.utc),
        )

    monkeypatch.setattr(
        "app.routes.model.model_service.get_model_file_download_url",
        fake_get_download_url,
    )

    name = "sentence-transformers/onnx/model.onnx"
    with _client_with_overrides(db, sample_member) as client:
        response = client.get(
            "/api/v1/models/12/files/download-url",
            params={"name": name},
        )

    assert response.status_code == 200, response.text
    assert captured == {
        "model_id": 12,
        "name": name,
        "user_info": {
            "member_id": sample_member.member_id,
            "role": sample_member.role,
            "name": sample_member.name,
        },
    }
    assert response.json()["download_url"].startswith("https://storage.example.invalid/")


def test_model_file_service_forwards_cursor_and_parses_response(monkeypatch):
    captured = {}

    async def fake_request(method, url, user_info=None, **kwargs):
        captured.update(method=method, url=url, user_info=user_info, kwargs=kwargs)
        payload = _file_list(next_cursor="next-page").model_dump(mode="json")
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(model_service, "_make_authenticated_request", fake_request)
    cursor = "opaque/+=="
    result = asyncio.run(
        model_service.get_model_files(
            12,
            cursor=cursor,
            user_info={"member_id": "member"},
        )
    )

    assert result.model_id == 12
    assert result.next_cursor == "next-page"
    assert captured["method"] == "GET"
    assert captured["url"].endswith("/models/12/files")
    assert captured["kwargs"]["params"] == {"cursor": cursor}
    assert captured["user_info"] == {"member_id": "member"}


def test_model_file_service_collects_all_cursor_pages(monkeypatch):
    calls = []
    pages = {
        None: _file_list(
            files=[_file("b.bin", 2, 2)],
            next_cursor="opaque-next",
        ),
        "opaque-next": _file_list(
            files=[_file("a.bin", 1, 1)],
            next_cursor=None,
        ),
    }

    async def fake_get_model_files(model_id, cursor=None, user_info=None):
        calls.append((model_id, cursor, user_info))
        return pages[cursor]

    monkeypatch.setattr(model_service, "get_model_files", fake_get_model_files)
    result = asyncio.run(
        model_service.get_all_model_files(12, user_info={"member_id": "member"})
    )

    assert calls == [
        (12, None, {"member_id": "member"}),
        (12, "opaque-next", {"member_id": "member"}),
    ]
    assert [file.name for file in result.files] == ["b.bin", "a.bin"]
    assert result.next_cursor is None


def test_model_file_service_rejects_repeated_cursor(monkeypatch):
    pages = {
        None: _file_list(files=[_file("a.bin", 1, 1)], next_cursor="same"),
        "same": _file_list(files=[_file("b.bin", 2, 2)], next_cursor="same"),
    }

    async def fake_get_model_files(model_id, cursor=None, user_info=None):
        return pages[cursor]

    monkeypatch.setattr(model_service, "get_model_files", fake_get_model_files)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(model_service.get_all_model_files(12))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "invalid upstream response"


def test_model_file_service_rejects_inconsistent_cursor_metadata(monkeypatch):
    pages = {
        None: _file_list(files=[_file("a.bin", 1, 1)], next_cursor="next"),
        "next": _file_list(
            files=[_file("b.bin", 2, 2)],
            next_cursor=None,
            model_name="different-model",
        ),
    }

    async def fake_get_model_files(model_id, cursor=None, user_info=None):
        return pages[cursor]

    monkeypatch.setattr(model_service, "get_model_files", fake_get_model_files)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(model_service.get_all_model_files(12))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "invalid upstream response"


@pytest.mark.parametrize(
    ("upstream_status", "expected_status", "expected_detail"),
    [
        (404, 404, "model not found"),
        (503, 502, "upstream service error"),
        (401, 502, "upstream service error"),
    ],
)
def test_model_file_service_maps_upstream_errors(
        monkeypatch, upstream_status, expected_status, expected_detail
):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(upstream_status, json={"detail": "model not found"})

    monkeypatch.setattr(model_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(model_service.get_model_files(12))

    assert exc_info.value.status_code == expected_status
    assert exc_info.value.detail == expected_detail


def test_download_url_service_preserves_upstream_409(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(
            409,
            json={"detail": "model storage does not support downloads"},
        )

    monkeypatch.setattr(model_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(model_service.get_model_file_download_url(31, "model.bin"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "model storage does not support downloads"


def test_model_file_service_rejects_invalid_success_response(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(
            200,
            json={
                "model_id": 12,
                "model_name": "broken",
                "storage_type": "MLFLOW",
                "location": None,
                "files": None,
                "next_cursor": None,
                "message": None,
            },
        )

    monkeypatch.setattr(model_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(model_service.get_model_files(12))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "invalid upstream response"


def test_model_file_list_accepts_live_openapi_defaults():
    result = ModelFileListResponse(
        model_id=12,
        model_name="empty-mlflow-model",
        storage_type=ModelFileStorageType.MLFLOW,
    )

    assert result.files == []
    assert result.location is None
    assert result.next_cursor is None
    assert result.message is None


def test_model_file_list_rejects_empty_page_with_next_cursor():
    with pytest.raises(ValueError):
        ModelFileListResponse(
            model_id=12,
            model_name="broken",
            storage_type=ModelFileStorageType.MLFLOW,
            files=[],
            next_cursor="unexpected-next-page",
        )


def test_model_file_service_maps_timeout_to_504(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(model_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(model_service.get_model_files(12))

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "upstream service timeout"


def test_model_file_openapi_contract():
    app.openapi_schema = None
    spec = app.openapi()

    list_operation = spec["paths"]["/api/v1/models/{model_id}/files"]["get"]
    assert list_operation["summary"] == "모델 저장 파일 목록 조회"
    assert [(p["name"], p["in"], p["required"]) for p in list_operation["parameters"]] == [
        ("model_id", "path", True),
        ("page", "query", False),
        ("size", "query", False),
        ("sort", "query", False),
    ]
    assert list_operation["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ModelFileListWrapper"
    }

    wrapper = spec["components"]["schemas"]["ModelFileListWrapper"]
    assert wrapper["required"] == ["data", "total", "page", "size"]
    assert set(wrapper["properties"]) == {"data", "total", "page", "size"}
    assert "ModelFileListResponse" not in spec["components"]["schemas"]

    download_operation = spec["paths"][
        "/api/v1/models/{model_id}/files/download-url"
    ]["get"]
    assert download_operation["summary"] == "모델 파일 다운로드 URL 발급"
    assert [(p["name"], p["in"], p["required"]) for p in download_operation["parameters"]] == [
        ("model_id", "path", True),
        ("name", "query", True),
    ]
    assert set(download_operation["responses"]) >= {"200", "401", "404", "409", "502", "504"}
