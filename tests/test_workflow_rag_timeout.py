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
    assert timeout.write == settings.PROXY_TIMEOUT, "write timeout은 기본값(PROXY_TIMEOUT) 유지해야 함"
    assert timeout.connect == settings.PROXY_CONNECT_TIMEOUT


def test_test_rag_workflow_logs_component_error(monkeypatch, caplog):
    async def fake_request(method, url, user_info=None, **kwargs):
        return _Response({
            "workflow_id": "wf-1",
            "execution_order": ["kb", "llm"],
            "results": [
                {"component_id": "kb", "component_name": "KB", "component_type": "KNOWLEDGE_BASE",
                 "result": {"search_result": "..."}, "error": None},
                {"component_id": "llm", "component_name": "LLM", "component_type": "MODEL",
                 "error": "connection refused"},
            ],
            "final_result": None,
        })

    monkeypatch.setattr(workflow_service, "_make_authenticated_request", fake_request)

    with caplog.at_level("WARNING"):
        asyncio.run(workflow_service.test_rag_workflow(workflow_id="wf-1", text="hello"))

    assert any("connection refused" in r.message for r in caplog.records), (
        "부분 실패(KB 성공·LLM 실패)도 warning 로그에 남아야 함"
    )
