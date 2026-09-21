import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
from io import BytesIO

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import settings
from app.cruds.knowledge_base import knowledge_base_crud
from app.database import get_db
from app.main import app
from app.services.knowledge_base_service import knowledge_base_service


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


def _make_upload():
    return UploadFile(BytesIO(b"doc content"), filename="doc.csv")


def test_create_knowledge_base_uses_dedicated_timeout(monkeypatch):
    captured = {}

    async def fake_request(method, url, user_info=None, **kwargs):
        captured.update(kwargs)
        return _Response({
            "id": 1, "name": "kb", "description": None, "collection_name": "col",
            "embedding_model_id": 13, "language_id": 1, "chunk_size": 500,
            "chunk_overlap": 50, "chunk_type_id": 1, "search_method_id": 1,
            "top_k": 3, "threshold": 0.4, "files": [],
        })

    monkeypatch.setattr(knowledge_base_service, "_make_authenticated_request", fake_request)

    asyncio.run(knowledge_base_service.create_knowledge_base(
        name="kb", file=_make_upload(), language_id=1, embedding_model_id=13,
        chunk_size=500, chunk_overlap=50, chunk_type_id=1, search_method_id=1,
        top_k=3, threshold=0.4,
    ))

    timeout = captured.get("timeout")
    assert isinstance(timeout, httpx.Timeout), "KB 생성은 전용 타임아웃을 써야 함"
    assert timeout.read == settings.PROXY_KB_INGEST_TIMEOUT
    assert timeout.write == settings.PROXY_KB_INGEST_TIMEOUT, "파일 업로드라 write도 늘려야 함"
    assert timeout.connect == settings.PROXY_CONNECT_TIMEOUT


def test_add_file_uses_dedicated_timeout(monkeypatch):
    captured = {}

    async def fake_request(method, url, user_info=None, **kwargs):
        captured.update(kwargs)
        return _Response({
            "id": 1, "name": "kb", "description": None, "collection_name": "col",
            "embedding_model_id": 13, "language_id": 1, "chunk_size": 500,
            "chunk_overlap": 50, "chunk_type_id": 1, "search_method_id": 1,
            "top_k": 3, "threshold": 0.4, "files": [],
        })

    monkeypatch.setattr(knowledge_base_service, "_make_authenticated_request", fake_request)

    asyncio.run(knowledge_base_service.add_file(1, _make_upload()))

    timeout = captured.get("timeout")
    assert isinstance(timeout, httpx.Timeout), "파일 추가도 생성과 동일한 동기 경로라 전용 타임아웃을 써야 함"
    assert timeout.read == settings.PROXY_KB_INGEST_TIMEOUT
    assert timeout.write == settings.PROXY_KB_INGEST_TIMEOUT
    assert timeout.connect == settings.PROXY_CONNECT_TIMEOUT


def test_create_knowledge_base_timeout_returns_504_with_message(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        raise httpx.ReadTimeout("")

    monkeypatch.setattr(knowledge_base_service, "_make_authenticated_request", fake_request)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(knowledge_base_service.create_knowledge_base(
            name="kb", file=_make_upload(), language_id=1, embedding_model_id=13,
            chunk_size=500, chunk_overlap=50, chunk_type_id=1, search_method_id=1,
            top_k=3, threshold=0.4,
        ))

    err = exc_info.value
    assert getattr(err, "status_code", None) == 504
    assert getattr(err, "detail", "") == "Knowledge base creation timed out", (
        "타임아웃은 빈 detail이 아니라 명확한 메시지를 줘야 함"
    )


def test_create_knowledge_base_non_timeout_error_unaffected(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        return _Response({"detail": "bad request"}, status_code=400)

    monkeypatch.setattr(knowledge_base_service, "_make_authenticated_request", fake_request)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(knowledge_base_service.create_knowledge_base(
            name="kb", file=_make_upload(), language_id=1, embedding_model_id=13,
            chunk_size=500, chunk_overlap=50, chunk_type_id=1, search_method_id=1,
            top_k=3, threshold=0.4,
        ))

    err = exc_info.value
    assert getattr(err, "status_code", None) == 400
    assert getattr(err, "detail", None) == "bad request", "기존 4xx 처리 흐름은 그대로 유지돼야 함"


def test_make_authenticated_request_connect_error_returns_503(monkeypatch):
    monkeypatch.setattr(knowledge_base_service, "access_token", "tok")
    monkeypatch.setattr(
        knowledge_base_service, "token_expires_at", datetime.now() + timedelta(hours=1)
    )

    async def fake_get(url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(knowledge_base_service.client, "get", fake_get)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(
            knowledge_base_service._make_authenticated_request("GET", "http://x/kb")
        )

    err = exc_info.value
    assert getattr(err, "status_code", None) == 503
    assert getattr(err, "detail", "") == "Knowledge base service unavailable"


def test_make_authenticated_request_connect_timeout_returns_503(monkeypatch):
    """ConnectError(즉시 거절)뿐 아니라 ConnectTimeout(응답 없이 먹통)도 503이어야 함.

    httpx.ConnectTimeout은 ConnectError의 하위 클래스가 아니라 별도 예외라서
    빠뜨리기 쉽다 (놓치면 조회/삭제/검색류 엔드포인트는 500으로 샌다).
    """
    monkeypatch.setattr(knowledge_base_service, "access_token", "tok")
    monkeypatch.setattr(
        knowledge_base_service, "token_expires_at", datetime.now() + timedelta(hours=1)
    )

    async def fake_get(url, **kwargs):
        raise httpx.ConnectTimeout("timed out")

    monkeypatch.setattr(knowledge_base_service.client, "get", fake_get)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(
            knowledge_base_service._make_authenticated_request("GET", "http://x/kb")
        )

    err = exc_info.value
    assert getattr(err, "status_code", None) == 503
    assert getattr(err, "detail", "") == "Knowledge base service unavailable"


def test_authenticate_connect_error_returns_503(monkeypatch):
    async def fake_post(url, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(knowledge_base_service.client, "post", fake_post)

    with pytest.raises(Exception) as exc_info:
        asyncio.run(knowledge_base_service._authenticate())

    err = exc_info.value
    assert getattr(err, "status_code", None) == 503
    assert getattr(err, "detail", "") == "Authentication service unavailable"


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


def test_delete_knowledge_base_route_passes_through_503(monkeypatch, db, sample_member):
    knowledge_base_crud.create_knowledge_base(
        db=db,
        name="kb-for-delete-test",
        description=None,
        created_by=sample_member.member_id,
        surro_knowledge_id=777,
        collection_name="col_777",
    )

    async def fake_delete(knowledge_base_id, user_info=None):
        raise HTTPException(status_code=503, detail="Knowledge base service unavailable")

    monkeypatch.setattr(knowledge_base_service, "delete_knowledge_base", fake_delete)

    with _client_with_overrides(db, sample_member) as client:
        response = client.delete("/api/v1/knowledge-bases/777")

    assert response.status_code == 503
