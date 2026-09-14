import asyncio
from io import BytesIO

import httpx
import pytest
from fastapi import UploadFile

from app.config import settings
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
    assert timeout.read == settings.PROXY_KB_CREATE_TIMEOUT
    assert timeout.write == settings.PROXY_KB_CREATE_TIMEOUT, "파일 업로드라 write도 늘려야 함"
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
