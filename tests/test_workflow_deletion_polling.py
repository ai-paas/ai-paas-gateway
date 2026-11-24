"""워크플로우 삭제/배포중지 완료 확인(finalize-*) 폴링 계약 회귀 테스트.

배경: 프론트가 `finalize-deletion`을 `status == "completed"`까지 반복 호출해야
삭제가 끝난다. 게이트웨이가 그 폴링을 깨뜨리던 3가지 경로를 고정한다.
- 완료 후 재호출이 게이트웨이 매핑 조회에서 404로 끊기던 문제
- upstream이 `completed`만 주고 `deleted_from_db`를 안 줄 때 게이트웨이 매핑이 남던 문제
- upstream 404(이미 삭제됨)가 404로 전파되며 게이트웨이 매핑이 남던 문제
"""
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.cruds.workflow import workflow_crud
from app.database import get_db
from app.main import app
from app.services.workflow_service import workflow_service


@contextmanager
def _client_with_overrides(db, current_user):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _create_mapping(db, member, surro_workflow_id):
    return workflow_crud.create_workflow(
        db,
        name="wf-delete-polling",
        description=None,
        created_by=member.member_id,
        surro_workflow_id=surro_workflow_id,
    )


class _FakeResponse:
    """status_code만 보는 경로용 최소 httpx.Response 대역."""

    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


class TestFinalizeDeletionPolling:
    def test_repeated_polls_stay_200_after_completion(
        self, db, sample_member, monkeypatch
    ):
        """완료 후 한 번 더 폴링해도 404가 아니라 upstream까지 도달해 완료 응답."""
        _create_mapping(db, sample_member, "surro-poll-1")

        calls = []
        responses = [
            {"workflow_id": "surro-poll-1", "status": "in_progress",
             "deleted_from_db": False},
            {"workflow_id": "surro-poll-1", "status": "completed",
             "deleted_from_db": True},
            {"workflow_id": "surro-poll-1", "status": "completed",
             "deleted_from_db": True, "message": "Workflow already deleted"},
        ]

        async def fake_finalize(workflow_id, user_info=None):
            calls.append(workflow_id)
            return responses[min(len(calls) - 1, len(responses) - 1)]

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.finalize_deletion", fake_finalize
        )

        with _client_with_overrides(db, sample_member) as client:
            first = client.post("/api/v1/workflows/surro-poll-1/finalize-deletion")
            second = client.post("/api/v1/workflows/surro-poll-1/finalize-deletion")
            third = client.post("/api/v1/workflows/surro-poll-1/finalize-deletion")

        assert first.status_code == 200, first.text
        assert first.json()["status"] == "in_progress"
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "completed"
        # 완료 뒤 재호출도 게이트웨이에서 끊기지 않고 upstream까지 도달해야 한다
        assert third.status_code == 200, third.text
        assert len(calls) == 3
        # 매핑은 soft-delete 상태로 유지 (활성 목록에서는 제외)
        assert workflow_crud.get_workflow_by_surro_id(db, "surro-poll-1") is None

    def test_completed_without_deleted_from_db_still_removes_mapping(
        self, db, sample_member, monkeypatch
    ):
        """upstream이 deleted_from_db를 안 줘도 completed면 게이트웨이 매핑 정리."""
        _create_mapping(db, sample_member, "surro-poll-2")

        async def fake_finalize(workflow_id, user_info=None):
            return {"workflow_id": workflow_id, "status": "completed",
                    "message": "Workflow deleted"}

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.finalize_deletion", fake_finalize
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/surro-poll-2/finalize-deletion")

        assert response.status_code == 200, response.text
        assert workflow_crud.get_workflow_by_surro_id(db, "surro-poll-2") is None

    def test_upstream_404_is_normalized_to_completed(
        self, db, sample_member, monkeypatch
    ):
        """MLOps에 이미 없으면 404가 아니라 완료로 정규화되고 매핑도 정리된다."""
        _create_mapping(db, sample_member, "surro-poll-3")

        async def fake_request(method, url, user_info=None, **kwargs):
            return _FakeResponse(404, {"detail": "Workflow not found"})

        monkeypatch.setattr(
            workflow_service, "_make_authenticated_request", fake_request
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/surro-poll-3/finalize-deletion")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "completed"
        assert body["deleted_from_db"] is True
        assert workflow_crud.get_workflow_by_surro_id(db, "surro-poll-3") is None

    def test_unknown_id_is_still_404(self, db, sample_member, monkeypatch):
        """게이트웨이 매핑에 아예 없는 ID는 여전히 404."""
        async def fake_finalize(workflow_id, user_info=None):
            raise AssertionError("upstream을 호출하면 안 된다")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.finalize_deletion", fake_finalize
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/surro-does-not-exist/finalize-deletion")

        assert response.status_code == 404, response.text

    def test_soft_deleted_mapping_of_other_user_is_403(
        self, db, sample_member, admin_member, monkeypatch
    ):
        """soft-delete 매핑까지 조회 범위를 넓혀도 소유권 검사는 유지된다."""
        _create_mapping(db, admin_member, "surro-poll-4")
        workflow_crud.delete_workflow_by_surro_id(
            db, surro_workflow_id="surro-poll-4", deleted_by=admin_member.member_id
        )

        async def fake_finalize(workflow_id, user_info=None):
            raise AssertionError("권한 없는 사용자는 upstream까지 가면 안 된다")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.finalize_deletion", fake_finalize
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/surro-poll-4/finalize-deletion")

        assert response.status_code == 403, response.text
