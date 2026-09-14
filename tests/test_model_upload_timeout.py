import asyncio
from io import BytesIO

import httpx
from fastapi import UploadFile

from app.config import settings
from app.schemas.model import ModelCreateRequest
from app.services.model_service import model_service


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


def test_create_model_with_file_uses_upload_timeout_and_streams(monkeypatch):
    captured = {}

    class FakeClient:
        async def post(self, url, **kwargs):
            captured.update(kwargs)
            return _Response({"id": 1, "name": "custom-model"})

    async def fake_token():
        return "test-token"

    monkeypatch.setattr(model_service, "client", FakeClient())
    monkeypatch.setattr(model_service, "_get_valid_token", fake_token)

    upload = UploadFile(BytesIO(b"weights"), filename="model.bin")

    async def run():
        await model_service.create_model(
            model_data=ModelCreateRequest(
                name="custom-model", provider_id=2, type_id=1, format_id=1,
            ),
            file=upload,
        )

    asyncio.run(run())

    assert "files" in captured, "파일 첨부 시 multipart files가 전달되어야 함"
    filename, file_obj, content_type = captured["files"]["file"]
    assert filename == "model.bin"
    assert file_obj is upload.file, "bytes로 미리 읽지 말고 UploadFile.file을 그대로 스트리밍해야 함"

    assert isinstance(captured.get("timeout"), httpx.Timeout), (
        "파일 첨부 요청은 PROXY_UPLOAD_TIMEOUT override를 써야 함"
    )
    timeout = captured["timeout"]
    assert timeout.read == settings.PROXY_UPLOAD_TIMEOUT, "read timeout은 PROXY_UPLOAD_TIMEOUT이어야 함"
    assert timeout.write == settings.PROXY_UPLOAD_TIMEOUT, "write timeout은 PROXY_UPLOAD_TIMEOUT이어야 함"
    assert timeout.connect == settings.PROXY_CONNECT_TIMEOUT, "connect timeout은 PROXY_CONNECT_TIMEOUT이어야 함"


def test_create_model_without_file_uses_default_timeout(monkeypatch):
    captured = {}

    async def fake_request(method, url, user_info=None, **kwargs):
        captured.update(kwargs)
        return _Response({"id": 2, "name": "catalog-model"})

    monkeypatch.setattr(model_service, "_make_authenticated_request", fake_request)

    async def run():
        await model_service.create_model(
            model_data=ModelCreateRequest(
                name="catalog-model", provider_id=1, type_id=1, format_id=1,
            ),
        )

    asyncio.run(run())

    assert "files" not in captured
    assert "timeout" not in captured, "파일 없는 요청은 클라이언트 기본 타임아웃(PROXY_TIMEOUT) 그대로 써야 함"


def test_create_model_with_file_reseeks_before_401_retry(monkeypatch):
    sent_bodies = []

    class FakeClient:
        async def post(self, url, **kwargs):
            file_obj = kwargs["files"]["file"][1]
            sent_bodies.append(file_obj.read())
            status_code = 401 if len(sent_bodies) == 1 else 200
            return _Response({"id": 3, "name": "custom-model"}, status_code=status_code)

    async def fake_token():
        return "test-token"

    monkeypatch.setattr(model_service, "client", FakeClient())
    monkeypatch.setattr(model_service, "_get_valid_token", fake_token)

    upload = UploadFile(BytesIO(b"weights"), filename="model.bin")

    async def run():
        await model_service.create_model(
            model_data=ModelCreateRequest(
                name="custom-model", provider_id=2, type_id=1, format_id=1,
            ),
            file=upload,
        )

    asyncio.run(run())

    assert len(sent_bodies) == 2, "401이면 한 번 재시도해야 함"
    assert sent_bodies[0] == b"weights"
    assert sent_bodies[1] == b"weights", (
        "재시도 전 파일 포인터를 되감지(seek(0)) 않으면 두 번째 전송이 빈 파일이 됨"
    )
