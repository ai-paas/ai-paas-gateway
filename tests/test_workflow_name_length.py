"""워크플로우 이름은 DB 컬럼(String(255))을 넘으면 MLOps 호출 전에 422 로 거절한다.

넘는 이름을 받으면 MLOps 에는 워크플로우가 생기고 게이트웨이 INSERT 만 실패해, 다음 목록
조회에서 admin 소유로 자동 등록된다.
"""
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.schemas.workflow import WorkflowCreateRequest

TOO_LONG = "a" * 256


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


def _forbid_upstream(monkeypatch, method):
    calls = []

    async def recorder(*args, **kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(f"app.routes.workflow.workflow_service.{method}", recorder)
    return calls


def test_create_rejects_name_over_255(db, sample_member, monkeypatch):
    calls = _forbid_upstream(monkeypatch, "create_workflow")

    with _client(db, sample_member) as client:
        response = client.post("/api/v1/workflows", json={"name": TOO_LONG})

    assert response.status_code == 422
    assert calls == []


def test_update_rejects_name_over_255(db, sample_member, monkeypatch):
    calls = _forbid_upstream(monkeypatch, "update_workflow")

    with _client(db, sample_member) as client:
        response = client.put("/api/v1/workflows/wf-any", json={"name": TOO_LONG})

    assert response.status_code == 422
    assert calls == []


def test_clone_rejects_name_over_255(db, sample_member, monkeypatch):
    calls = _forbid_upstream(monkeypatch, "clone_template")

    with _client(db, sample_member) as client:
        response = client.post(
            "/api/v1/workflows/templates/tpl-any/clone",
            params={"workflow_name": TOO_LONG},
        )

    assert response.status_code == 422
    assert calls == []


def test_name_of_255_is_accepted():
    assert WorkflowCreateRequest(name="a" * 255).name == "a" * 255
