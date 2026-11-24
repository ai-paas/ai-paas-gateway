"""MLOps Workflow API v2 호환성 테스트.

목적:
- 새 spec(ref_id 기반 connection / body 없는 execute / query 없는 finalize-deletion / 제거된 inference)을
  따른 호출이 게이트웨이에서 422나 의도치 않은 5xx로 차단되지 않는지 검증.
- 새 페이로드 필드(`ref_id`, `source_ref_id`, `target_ref_id`, `description`, `config`)가
  schema → service layer 까지 손실 없이 도달하는지 확인.
"""
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.cruds.workflow import workflow_crud
from app.database import get_db
from app.main import app
from app.schemas.workflow import (
    ExternalWorkflowDetailResponse,
    ValidationCheckResponse,
    WorkflowExecuteResponse,
    WorkflowValidateResponse,
)


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


class TestWorkflowV2Compat:
    def test_create_workflow_passes_ref_id_payload_through_to_service(
        self, db, sample_member, monkeypatch
    ):
        """ref_id / source_ref_id / target_ref_id / description / config가
        service layer까지 그대로 전달되는지 확인."""
        captured = {}

        async def fake_create_workflow(
            name, description=None, category=None, service_id=None,
            workflow_definition=None, user_info=None,
        ):
            captured["workflow_definition"] = workflow_definition
            return ExternalWorkflowDetailResponse(
                id="surro-uuid-create-1",
                name=name,
                description=description,
                category=category,
                status="DRAFT",
                service_id=service_id,
                creator_id=1,
                is_template=False,
                template_id=None,
                components=[],
                component_connections=[],
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.create_workflow",
            fake_create_workflow,
        )

        payload = {
            "name": "wf-v2",
            "description": "v2 compat test",
            "workflow_definition": {
                "components": [
                    {"ref_id": "tmp-1", "name": "start", "type": "START"},
                    {
                        "ref_id": "tmp-2",
                        "name": "model",
                        "type": "MODEL",
                        "description": "model component",
                        "model_id": 100,
                        "prompt_id": 5,
                        "config": {"replicas": 2},
                        "x": -120,
                        "y": 240,
                    },
                    {"ref_id": "tmp-3", "name": "end", "type": "END"},
                ],
                "connections": [
                    {"source_ref_id": "tmp-1", "target_ref_id": "tmp-2"},
                    {"source_ref_id": "tmp-2", "target_ref_id": "tmp-3"},
                ],
            },
        }

        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/", json=payload)

        assert response.status_code == 201, response.text

        sent = captured["workflow_definition"]
        assert sent is not None
        assert [c["ref_id"] for c in sent["components"]] == ["tmp-1", "tmp-2", "tmp-3"]

        model_comp = sent["components"][1]
        assert model_comp["description"] == "model component"
        assert model_comp["model_id"] == 100
        assert model_comp["prompt_id"] == 5
        assert model_comp["config"] == {"replicas": 2}
        assert model_comp["x"] == -120
        assert model_comp["y"] == 240

        assert sent["connections"] == [
            {"source_ref_id": "tmp-1", "target_ref_id": "tmp-2"},
            {"source_ref_id": "tmp-2", "target_ref_id": "tmp-3"},
        ]

    def test_get_workflow_returns_component_coordinates_and_user_brief(
        self, db, sample_member, monkeypatch
    ):
        workflow_crud.create_workflow(
            db,
            name="wf-coordinates",
            description=None,
            created_by=sample_member.member_id,
            surro_workflow_id="surro-uuid-coordinates-1",
        )

        async def fake_get_workflow(workflow_id, user_info=None):
            assert workflow_id == "surro-uuid-coordinates-1"
            return ExternalWorkflowDetailResponse(
                id=workflow_id,
                name="wf-coordinates",
                description=None,
                category=None,
                status="DRAFT",
                service_id=None,
                creator_id=1,
                creator={
                    "id": 1,
                    "username": "surromind",
                    "name": "surromind",
                    "created_at": "2026-04-29T13:57:05",
                    "updated_at": "2026-04-29T13:57:05",
                },
                is_template=False,
                template_id=None,
                components=[
                    {
                        "id": "component-1",
                        "workflow_id": workflow_id,
                        "name": "model",
                        "type": "MODEL",
                        "description": "model component",
                        "model_id": 100,
                        "prompt_id": 5,
                        "config": {"replicas": 2},
                        "x": -120,
                        "y": 240,
                    }
                ],
                component_connections=[],
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.get_workflow",
            fake_get_workflow,
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.get("/api/v1/workflows/surro-uuid-coordinates-1")

        assert response.status_code == 200, response.text
        component = response.json()["components"][0]
        assert component["description"] == "model component"
        assert component["config"] == {"replicas": 2}
        assert component["x"] == -120
        assert component["y"] == 240

    def test_execute_without_body_is_not_422_at_gateway(
        self, db, sample_member, monkeypatch
    ):
        """body 없이 execute 호출 시 게이트웨이에서 422가 나지 않고, parameters가
        외부에 전달되지 않는지 확인."""
        workflow_crud.create_workflow(
            db,
            name="wf-exec",
            description=None,
            created_by=sample_member.member_id,
            surro_workflow_id="surro-uuid-exec-1",
        )

        captured = {}

        async def fake_execute(workflow_id, parameters=None, user_info=None):
            captured["parameters"] = parameters
            captured["workflow_id"] = workflow_id
            return WorkflowExecuteResponse(
                workflow_id=workflow_id,
                kubeflow_run_id="run-1",
                status="PENDING",
                message="ok",
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.execute_workflow",
            fake_execute,
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/surro-uuid-exec-1/execute")

        assert response.status_code == 200, response.text
        assert captured["workflow_id"] == "surro-uuid-exec-1"
        # MLOps v2는 body를 받지 않으므로 게이트웨이가 외부에 parameters를 전달하면 안 됨
        assert captured["parameters"] is None

    def test_finalize_deletion_without_run_id_is_not_422_at_gateway(
        self, db, sample_member, monkeypatch
    ):
        """run_id 없이 finalize-deletion 호출 시 게이트웨이에서 422가 나지 않고,
        run_id가 외부에 전달되지 않는지 확인."""
        workflow_crud.create_workflow(
            db,
            name="wf-finalize",
            description=None,
            created_by=sample_member.member_id,
            surro_workflow_id="surro-uuid-finalize-1",
        )

        captured = {}

        async def fake_finalize(workflow_id, run_id=None, user_info=None):
            captured["workflow_id"] = workflow_id
            captured["run_id"] = run_id
            return {
                "workflow_id": workflow_id,
                "status": "in_progress",
                "deleted_from_db": False,
                "message": "still running",
            }

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.finalize_deletion",
            fake_finalize,
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post(
                "/api/v1/workflows/surro-uuid-finalize-1/finalize-deletion"
            )

        assert response.status_code == 200, response.text
        assert captured["workflow_id"] == "surro-uuid-finalize-1"
        # MLOps v2는 run_id query를 받지 않으므로 외부 호출에도 None이어야 함
        assert captured["run_id"] is None

    def test_execute_with_body_does_not_forward_parameters_to_mlops(
        self, db, sample_member, monkeypatch
    ):
        """클라이언트가 parameters를 body에 실어 보내도 게이트웨이가 외부에는 전달하지
        않아야 한다 (MLOps v2 호환)."""
        workflow_crud.create_workflow(
            db,
            name="wf-exec-with-body",
            description=None,
            created_by=sample_member.member_id,
            surro_workflow_id="surro-uuid-exec-2",
        )

        captured = {}

        async def fake_execute(workflow_id, parameters=None, user_info=None):
            captured["parameters"] = parameters
            return WorkflowExecuteResponse(
                workflow_id=workflow_id,
                kubeflow_run_id="run-2",
                status="PENDING",
                message="ok",
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.execute_workflow",
            fake_execute,
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post(
                "/api/v1/workflows/surro-uuid-exec-2/execute",
                json={"parameters": {"replicas": 3, "gpu": True}},
            )

        assert response.status_code == 200, response.text
        # 외부에 보낸 parameters는 None이어야 한다 (사용자가 body에 보냈더라도 폐기)
        assert captured["parameters"] is None

    def test_finalize_deletion_with_run_id_query_does_not_forward_to_mlops(
        self, db, sample_member, monkeypatch
    ):
        """클라이언트가 run_id query를 보내도 게이트웨이가 외부에는 전달하지
        않아야 한다 (MLOps v2 호환)."""
        workflow_crud.create_workflow(
            db,
            name="wf-finalize-with-query",
            description=None,
            created_by=sample_member.member_id,
            surro_workflow_id="surro-uuid-finalize-2",
        )

        captured = {}

        async def fake_finalize(workflow_id, run_id=None, user_info=None):
            captured["run_id"] = run_id
            return {
                "workflow_id": workflow_id,
                "status": "completed",
                "deleted_from_db": False,
                "message": "ok",
            }

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.finalize_deletion",
            fake_finalize,
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post(
                "/api/v1/workflows/surro-uuid-finalize-2/finalize-deletion",
                params={"run_id": "legacy-run-123"},
            )

        assert response.status_code == 200, response.text
        # 외부에 보낸 run_id는 None이어야 한다 (사용자가 query로 보냈더라도 폐기)
        assert captured["run_id"] is None

    def test_validate_passes_workflow_definition_through_to_service(
        self, db, sample_member, monkeypatch
    ):
        """validate 라우트가 받은 workflow_definition을 그대로 service layer에 전달하고
        응답 스키마(valid/checks)가 정상 직렬화되는지 확인."""
        captured = {}

        async def fake_validate(workflow_definition, user_info=None):
            captured["workflow_definition"] = workflow_definition
            captured["user_info"] = user_info
            return WorkflowValidateResponse(
                valid=False,
                checks=[
                    ValidationCheckResponse(
                        rule="has_start", passed=True, message=None
                    ),
                    ValidationCheckResponse(
                        rule="has_end",
                        passed=False,
                        message="END component is missing",
                    ),
                ],
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.validate_workflow",
            fake_validate,
        )

        payload = {
            "workflow_definition": {
                "components": [
                    {"ref_id": "tmp-1", "name": "start", "type": "START"},
                    {
                        "ref_id": "tmp-2",
                        "name": "model",
                        "type": "MODEL",
                        "model_id": 7,
                    },
                ],
                "connections": [
                    {"source_ref_id": "tmp-1", "target_ref_id": "tmp-2"},
                ],
            }
        }

        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/validate", json=payload)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["valid"] is False
        assert len(body["checks"]) == 2
        assert body["checks"][1]["rule"] == "has_end"
        assert body["checks"][1]["passed"] is False
        assert body["checks"][1]["message"] == "END component is missing"

        # service layer까지 그대로 도달했는지
        sent = captured["workflow_definition"]
        assert [c["ref_id"] for c in sent["components"]] == ["tmp-1", "tmp-2"]
        assert sent["connections"] == [
            {"source_ref_id": "tmp-1", "target_ref_id": "tmp-2"}
        ]
        # 인증 컨텍스트가 전달되어야 함
        assert captured["user_info"]["member_id"] == sample_member.member_id

    def test_validate_rejects_payload_without_ref_id(self, db, sample_member):
        """ref_id 없는 component는 게이트웨이 Pydantic 검증에서 422 반환."""
        payload = {
            "workflow_definition": {
                "components": [
                    {"name": "no-ref", "type": "START"},  # ref_id 누락
                ],
                "connections": [],
            }
        }

        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/validate", json=payload)

        assert response.status_code == 422, response.text

    def test_deprecated_inference_returns_410_with_alternatives(
        self, db, sample_member
    ):
        """제거된 inference 엔드포인트 호출 시 410 + 대체 API 안내.

        인증된 호출 기준 — 다른 워크플로우 라우트와 동일하게 auth dependency를 갖는다."""
        with _client_with_overrides(db, sample_member) as client:
            response = client.post(
                "/api/v1/workflows/any-id/models/any-comp/inference"
            )

        assert response.status_code == 410, response.text
        detail = response.json()["detail"]
        assert "removed in MLOps v2" in detail["message"]
        assert "test/rag" in detail["alternatives"]["rag_workflow"]
        assert "test/ml" in detail["alternatives"]["ml_workflow"]
