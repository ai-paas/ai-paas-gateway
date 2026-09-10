import asyncio

import httpx

from app.config import settings
from app.services.workflow_service import workflow_service


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


def test_test_rag_workflow_uses_dedicated_timeout(monkeypatch):
    captured = {}

    async def fake_request(method, url, user_info=None, **kwargs):
        captured.update(kwargs)
        return _Response({"workflow_id": "wf-1", "execution_order": [], "results": [], "final_result": None})

    monkeypatch.setattr(workflow_service, "_make_authenticated_request", fake_request)

    asyncio.run(workflow_service.test_rag_workflow(workflow_id="wf-1", text="hello"))

    timeout = captured.get("timeout")
    assert isinstance(timeout, httpx.Timeout), "test_rag_workflow는 전용 타임아웃을 써야 함"
    assert timeout.read == settings.PROXY_RAG_TIMEOUT
    assert timeout.read != settings.PROXY_TIMEOUT, "기본 PROXY_TIMEOUT(30s)이 아니라 별도 값이어야 함"
