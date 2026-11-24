"""[임시] Kaggle 공인시험 우회 경로 테스트 — app/services/temp_kaggle_demo.py 와 함께 제거한다."""
import time
from contextlib import contextmanager

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models.model import Model
from app.schemas.hub_connect import ModelFileInfo, ModelFilesResponse
from app.services import temp_kaggle_demo
from tests.conftest import make_member

PROVIDERS = [
    {"id": 1, "name": "huggingface", "description": "hf"},
    {"id": 4, "name": "Kaggle", "description": "kaggle"},
]
TYPES = [{"id": 2, "name": "LLM", "description": None}]
FORMATS = {"data": [{"id": 3, "name": "pytorch", "description": None}]}
REPO_ID = "google/gemma/pyTorch/2b"


@contextmanager
def _client(db, current_user):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def fakes(monkeypatch):
    calls = {"downloads": [], "mlops_create": 0}

    async def providers(user_info=None, provider_name=None):
        return PROVIDERS

    async def types(user_info=None, type_name=None):
        return TYPES

    async def formats(user_info=None, format_name=None):
        return FORMATS

    async def hub_files(model_id, market, user_info=None):
        assert (model_id, market) == (REPO_ID, "kaggle")
        return ModelFilesResponse(data=[ModelFileInfo(name="model.pt"), ModelFileInfo(name="config.json")])

    async def hub_request(method, url, user_info=None, **kwargs):
        # 실제 hub 는 filename 과 무관하게 모델 전체 압축 파일 하나를 저장한다
        params = kwargs["params"]
        calls["downloads"].append((url, params, kwargs.get("timeout")))
        return httpx.Response(200, json={
            "download_type": "custom_path",
            "file_path": f"{params['download_dir']}/gemma.tar.gz",
            "file_size": 1828837,
            "filename": "gemma.tar.gz",
            "model_id": REPO_ID,
        })

    async def mlops_create(**kwargs):
        calls["mlops_create"] += 1
        raise AssertionError("Kaggle 요청은 MLOps 로 가면 안 된다")

    async def mlops_models(**kwargs):
        return []

    monkeypatch.setattr(temp_kaggle_demo.model_service, "get_model_providers", providers)
    monkeypatch.setattr(temp_kaggle_demo.model_service, "get_model_types", types)
    monkeypatch.setattr(temp_kaggle_demo.model_service, "get_model_formats", formats)
    monkeypatch.setattr(temp_kaggle_demo.model_service, "create_model", mlops_create)
    monkeypatch.setattr(temp_kaggle_demo.model_service, "get_models", mlops_models)
    monkeypatch.setattr(temp_kaggle_demo.hub_connect_service, "get_model_files", hub_files)
    monkeypatch.setattr(temp_kaggle_demo.hub_connect_service, "_make_authenticated_request", hub_request)

    # 사용자 다운로드 중계용: hub 의 download_dir 없는 다운로드는 파일 본문을 응답한다
    calls["streams"] = []
    calls["hub_status"] = 200

    def stream_handler(request: httpx.Request):
        calls["streams"].append(request)
        if calls["hub_status"] != 200:
            return httpx.Response(calls["hub_status"], text="kaggle error")
        return httpx.Response(200, content=ARCHIVE, headers={"content-type": "application/octet-stream"})

    async def valid_token():
        return "hub-token"

    monkeypatch.setattr(
        temp_kaggle_demo.hub_connect_service, "client", httpx.AsyncClient(transport=httpx.MockTransport(stream_handler))
    )
    monkeypatch.setattr(temp_kaggle_demo.hub_connect_service, "_get_valid_token", valid_token)
    return calls


ARCHIVE = b"fake-tar-gz-bytes" * 100


def _create(client, provider_id=4):
    return client.post("/api/v1/models", data={
        "name": "gemma-demo",
        "repo_id": REPO_ID,
        "provider_id": provider_id,
        "type_id": 2,
        "format_id": 3,
        "description": "kaggle demo",
    })


def test_kaggle_create_downloads_via_hub_and_flows_through_ui_endpoints(db, sample_member, fakes):
    with _client(db, sample_member) as client:
        created = _create(client)
        assert created.status_code == 200, created.text
        body = created.json()
        model_id = body["id"]
        assert model_id >= temp_kaggle_demo.DEMO_ID_BASE
        assert body["provider_info"]["name"] == "Kaggle"
        assert body["type_info"]["name"] == "LLM"
        assert body["format_info"]["name"] == "pytorch"
        assert body["repo_id"] == REPO_ID
        assert fakes["mlops_create"] == 0

        # hub 다운로드는 한 번만, download_dir 지정 + 긴 타임아웃
        assert len(fakes["downloads"]) == 1
        url, params, timeout = fakes["downloads"][0]
        assert url.endswith(f"/models/{REPO_ID}/download")
        assert params["download_dir"].endswith(f"/kaggle-demo/{model_id}")
        assert timeout == temp_kaggle_demo.DOWNLOAD_TIMEOUT

        custom = client.get("/api/v1/models/custom-models").json()
        assert [m["id"] for m in custom["data"]] == [model_id]
        assert custom["total"] == 1

        detail = client.get(f"/api/v1/models/{model_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["provider_info"]["name"] == "Kaggle"

        files = client.get(f"/api/v1/models/{model_id}/files").json()
        assert [(f["name"], f["size_bytes"]) for f in files["data"]] == [("gemma.tar.gz", 1828837)]
        assert files["total"] == 1

        dl = client.get(f"/api/v1/models/{model_id}/files/download-url", params={"name": "gemma.tar.gz"})
        assert dl.status_code == 200, dl.text
        assert dl.json()["size_bytes"] == 1828837
        file_response = client.get(dl.json()["download_url"])
        assert file_response.status_code == 200, file_response.text
        assert file_response.content == ARCHIVE
        assert file_response.headers["content-disposition"] == "attachment; filename*=UTF-8''gemma.tar.gz"
        hub_call = fakes["streams"][-1]
        assert hub_call.url.path.endswith(f"/models/{REPO_ID}/download")
        assert hub_call.url.params["filename"] == "model.pt"
        assert "download_dir" not in hub_call.url.params
        assert hub_call.headers["authorization"] == "Bearer hub-token"

        # 전체 목록·카탈로그(서빙·워크플로우 선택용)에는 나오지 않는다
        assert client.get("/api/v1/models").json()["data"] == []
        assert client.get("/api/v1/models/model-catalog").json()["data"] == []

        deleted = client.delete(f"/api/v1/models/{model_id}")
        assert deleted.status_code == 200, deleted.text
        assert client.get(f"/api/v1/models/{model_id}").status_code == 404
        assert client.get("/api/v1/models/custom-models").json()["data"] == []


def test_kaggle_demo_model_is_hidden_from_other_users(db, sample_member, fakes):
    with _client(db, sample_member) as client:
        model_id = _create(client).json()["id"]

    other = make_member("other-user")
    db.add(other)
    db.flush()
    with _client(db, other) as client:
        assert client.get(f"/api/v1/models/{model_id}").status_code == 404
        assert client.get(f"/api/v1/models/{model_id}/files").status_code == 404
        assert client.delete(f"/api/v1/models/{model_id}").status_code == 404
        assert client.get("/api/v1/models/custom-models").json()["data"] == []


def test_second_demo_model_gets_next_id(db, sample_member, fakes):
    with _client(db, sample_member) as client:
        first = _create(client).json()["id"]
        second = _create(client).json()["id"]
    assert second == first + 1


def test_non_kaggle_provider_still_goes_to_mlops(db, sample_member, fakes):
    with _client(db, sample_member) as client:
        response = _create(client, provider_id=1)
    # fake MLOps create 가 던진 예외를 라우트가 500 으로 감싼다 — MLOps 경로로 갔다는 증거
    assert response.status_code == 500
    assert fakes["mlops_create"] == 1
    assert fakes["downloads"] == []
    assert db.query(Model).filter(Model.surro_model_id >= temp_kaggle_demo.DEMO_ID_BASE).count() == 0


def test_provider_lookup_failure_falls_back_to_mlops(db, sample_member, fakes, monkeypatch):
    async def failing_providers(user_info=None, provider_name=None):
        raise RuntimeError("MLOps down")

    monkeypatch.setattr(temp_kaggle_demo.model_service, "get_model_providers", failing_providers)
    with _client(db, sample_member) as client:
        _create(client, provider_id=1)
    assert fakes["mlops_create"] == 1
    assert fakes["downloads"] == []


def test_download_link_rejects_tampered_expired_and_deleted(db, sample_member, fakes):
    with _client(db, sample_member) as client:
        model_id = _create(client).json()["id"]
        path = f"/api/v1/models/{model_id}/files/temp-kaggle-download"

        future = int(time.time()) + 60
        assert client.get(path, params={"expires": future, "sig": "0" * 64}).status_code == 403
        # 다른 모델 ID 로 만든 서명은 이 모델에 쓸 수 없다
        other_sig = temp_kaggle_demo._sign(model_id + 1, future)
        assert client.get(path, params={"expires": future, "sig": other_sig}).status_code == 403
        past = int(time.time()) - 1
        assert client.get(path, params={"expires": past, "sig": temp_kaggle_demo._sign(model_id, past)}).status_code == 403

        assert client.get(path, params={"expires": future, "sig": temp_kaggle_demo._sign(model_id, future)}).status_code == 200
        client.delete(f"/api/v1/models/{model_id}")
        assert client.get(path, params={"expires": future, "sig": temp_kaggle_demo._sign(model_id, future)}).status_code == 404


def test_download_url_uses_forwarded_host_and_unknown_file_is_404(db, sample_member, fakes):
    with _client(db, sample_member) as client:
        model_id = _create(client).json()["id"]
        url = f"/api/v1/models/{model_id}/files/download-url"
        dl = client.get(
            url,
            params={"name": "gemma.tar.gz"},
            headers={"X-Forwarded-Proto": "https", "X-Forwarded-Host": "aipaas.example.com"},
        )
        assert dl.json()["download_url"].startswith(
            f"https://aipaas.example.com/api/v1/models/{model_id}/files/temp-kaggle-download?"
        )
        assert client.get(url, params={"name": "nope.bin"}).status_code == 404


def test_download_hub_error_is_502(db, sample_member, fakes):
    with _client(db, sample_member) as client:
        model_id = _create(client).json()["id"]
        fakes["hub_status"] = 503
        download_url = client.get(
            f"/api/v1/models/{model_id}/files/download-url", params={"name": "gemma.tar.gz"}
        ).json()["download_url"]
        assert client.get(download_url).status_code == 502


def test_hub_download_failure_leaves_no_row(db, sample_member, fakes, monkeypatch):
    async def failing(method, url, user_info=None, **kwargs):
        return httpx.Response(503, text="Kaggle credentials not configured")

    monkeypatch.setattr(temp_kaggle_demo.hub_connect_service, "_make_authenticated_request", failing)
    with _client(db, sample_member) as client:
        response = _create(client)
    assert response.status_code == 503
    assert db.query(Model).filter(Model.surro_model_id >= temp_kaggle_demo.DEMO_ID_BASE).count() == 0
