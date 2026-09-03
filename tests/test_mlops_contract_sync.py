import asyncio
from contextlib import contextmanager

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.cruds.workflow import workflow_crud
from app.cruds.service import service_crud
from app.database import get_db
from app.main import app
from app.models import Service
from app.schemas.service import ServiceCreate
from app.services.service_service import service_service
from app.services.pipeline_service import pipeline_service
from app.services.workflow_service import workflow_service


PREDEFINED_MODEL_KEYS = [
    "hustvl/yolos-tiny",
    "hustvl/yolos-small",
    "facebook/detr-resnet-50",
    "facebook/detr-resnet-101",
    "Roboflow/rf-detr-large",
    "Roboflow/rf-detr-medium",
    "ahmgam/medllama3-v20:latest",
    "bge-m3",
    "facebook/esm2_t6_8M_UR50D",
    "multimolecule/rnafm",
    "ibm-research/MoLFormer-XL-both-10pct",
    "biohub/ESMC-300M",
    "biohub/ESMC-6B",
    "biohub/ESMFold2",
    "yolox_s",
    "yolox_m",
    "qwq:32b",
    "gpt-oss:20b",
    "deepseek-r1:32b",
    "granite4.1:30b",
    "lfm2:24b",
    "gemma4:27b",
    "qwen3.6:27b",
    "nemotron3:33b",
]


def _request_schema(spec, path, method):
    request_body = spec["paths"][path][method]["requestBody"]
    media_type, content = next(iter(request_body["content"].items()))
    schema = content["schema"]
    if "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].rsplit("/", 1)[-1]]
    return media_type, schema


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


def test_updated_mlops_write_contracts_are_exposed_in_openapi():
    app.openapi_schema = None
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    media_type, training = _request_schema(
        spec, "/api/v1/learning/training", "post"
    )
    assert media_type == "multipart/form-data"
    assert training["required"] == ["model_id"]
    assert set(training["properties"]) == {
        "dataset_file",
        "model_id",
        "train_name",
        "description",
        "dataset_id",
        "dataset_kind",
        "gpus",
        "batch_size",
        "epochs",
        "save_period",
        "weight_decay",
        "learning_rate",
    }

    _, model_create = _request_schema(spec, "/api/v1/models", "post")
    assert set(model_create["required"]) == {
        "name", "provider_id", "type_id", "format_id"
    }
    assert "repo_id" not in model_create["required"]
    assert schemas["PredefinedModelKey"]["enum"] == PREDEFINED_MODEL_KEYS
    assert "recommended_hparams" in schemas["ModelCreateResponse"]["properties"]
    assert "recommended_hparams" in schemas["ModelResponse"]["properties"]

    for path, method in (
        ("/api/v1/models/base-deployments/{model_id}/status", "put"),
        (
            "/api/v1/workflows/{surro_workflow_id}/components/{component_id}/deployment-status",
            "post",
        ),
    ):
        body_type, _ = _request_schema(spec, path, method)
        assert body_type == "application/json"

    for path in (
        "/api/v1/workflows/{surro_workflow_id}/execute",
        "/api/v1/workflows/{surro_workflow_id}/finalize-deletion",
        "/api/v1/workflows/{surro_workflow_id}/finalize-cleanup",
    ):
        operation = spec["paths"][path]["post"]
        assert "requestBody" not in operation
        assert [p for p in operation.get("parameters", []) if p["in"] != "path"] == []

    _, template_create = _request_schema(
        spec, "/api/v1/workflows/templates", "post"
    )
    assert "service_id" not in template_create["properties"]
    assert schemas["PromptVariableType"]["enum"] == ["context"]


def test_training_service_sends_multipart_even_for_existing_dataset(monkeypatch):
    captured = {}

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"experiment_id": 101}

    class Client:
        async def post(self, url, **kwargs):
            captured.update(url=url, kwargs=kwargs)
            return Response()

    async def token():
        return "test-token"

    monkeypatch.setattr(pipeline_service, "client", Client())
    monkeypatch.setattr(pipeline_service, "_get_valid_token", token)

    result = asyncio.run(
        pipeline_service.submit_training(
            {
                "model_id": 7,
                "dataset_id": 8,
                "dataset_kind": "object-detection",
                "epochs": "10",
            }
        )
    )

    assert result == {"experiment_id": 101}
    assert "data" not in captured["kwargs"]
    multipart = dict(captured["kwargs"]["files"])
    assert multipart["model_id"] == (None, "7")
    assert multipart["dataset_id"] == (None, "8")
    assert multipart["dataset_kind"] == (None, "object-detection")
    assert multipart["epochs"] == (None, "10")


def test_training_rejects_unmapped_model_before_upstream(db, sample_member):
    with _client_with_overrides(db, sample_member) as client:
        response = client.post(
            "/api/v1/learning/training",
            data={"model_id": "999"},
            files={"dataset_file": ("dataset.zip", b"zip", "application/zip")},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "Model not found or access denied"


def test_learning_pipeline_operations_reject_unmapped_experiment(
    db, sample_member
):
    with _client_with_overrides(db, sample_member) as client:
        registration = client.post(
            "/api/v1/learning/model/registration",
            json={
                "model_name": "model",
                "description": "description",
                "experiment_id": 999,
            },
        )
        training_status = client.get("/api/v1/learning/999/status")

    assert registration.status_code == 404
    assert training_status.status_code == 404
    assert registration.json()["detail"] == "Learning item not found or access denied"
    assert training_status.json()["detail"] == "Learning item not found or access denied"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/api/v1/workflows/wf-foreign"),
        ("get", "/api/v1/workflows/wf-foreign/status"),
        ("get", "/api/v1/workflows/wf-foreign/models"),
        ("post", "/api/v1/workflows/wf-foreign/execute"),
        ("post", "/api/v1/workflows/wf-foreign/finalize-deletion"),
        ("post", "/api/v1/workflows/wf-foreign/finalize-cleanup"),
    ],
)
def test_workflow_operations_reject_non_owner(
    db, sample_member, admin_member, method, path
):
    workflow_crud.create_workflow(
        db,
        name="foreign",
        description=None,
        created_by=admin_member.member_id,
        surro_workflow_id="wf-foreign",
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.request(method, path)

    assert response.status_code == 403
    assert response.json()["detail"] == "Permission denied"


def test_workflow_list_does_not_delete_mapping_missing_from_upstream(
    db, sample_member, monkeypatch
):
    workflow_crud.create_workflow(
        db,
        name="local-only",
        description=None,
        created_by=sample_member.member_id,
        surro_workflow_id="wf-local-only",
    )

    async def fake_get_workflows(**kwargs):
        return []

    monkeypatch.setattr(workflow_service, "get_workflows", fake_get_workflows)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/workflows/?page=1&size=20")

    assert response.status_code == 200, response.text
    assert workflow_crud.get_workflow_by_surro_id(db, "wf-local-only") is not None


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "put",
            "/api/v1/models/base-deployments/1/status",
            {
                "service_name": "service",
                "service_hostname": "service.local",
                "status": "ready",
            },
        ),
        (
            "post",
            "/api/v1/workflows/wf/components/component/deployment-status",
            {
                "service_name": "service",
                "service_hostname": "service.local",
                "model_name": "model",
                "status": "ready",
            },
        ),
    ],
)
def test_internal_deployment_status_requires_admin(
    db, sample_member, method, path, payload
):
    with _client_with_overrides(db, sample_member) as client:
        response = client.request(method, path, json=payload)

    assert response.status_code == 403
    assert response.json()["detail"] == "Admin access required"


def test_service_list_is_owner_scoped_and_uses_current_upstream_fields(
    db, sample_member, admin_member, monkeypatch
):
    own = Service(
        name="stale-name",
        description="stale-description",
        tags=["stale"],
        created_by=sample_member.member_id,
        surro_service_id="service-own",
    )
    foreign = Service(
        name="foreign",
        description="foreign",
        tags=[],
        created_by=admin_member.member_id,
        surro_service_id="service-foreign",
    )
    db.add_all([own, foreign])
    db.commit()

    async def fake_get_services(**kwargs):
        return {
            "items": [
                {
                    "id": "service-own",
                    "name": "current-name",
                    "description": "current-description",
                    "tags": ["current"],
                },
                {
                    "id": "service-foreign",
                    "name": "foreign",
                    "description": "foreign",
                    "tags": [],
                },
            ],
            "total": 2,
        }

    monkeypatch.setattr(service_service, "get_services", fake_get_services)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/services/?page=1&size=20")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] == 1
    assert body["data"][0]["surro_service_id"] == "service-own"
    assert body["data"][0]["name"] == "current-name"
    assert body["data"][0]["description"] == "current-description"
    assert body["data"][0]["tags"] == ["current"]


def test_service_resource_usage_rejects_non_owner(db, sample_member, admin_member):
    db.add(
        Service(
            name="foreign",
            description=None,
            tags=[],
            created_by=admin_member.member_id,
            surro_service_id="service-foreign",
        )
    )
    db.commit()

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(
            "/api/v1/services/service-foreign/resource-usages"
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Permission denied"


def test_service_delete_mapping_is_soft_delete(db, sample_member):
    row = Service(
        name="service-to-delete",
        description=None,
        tags=[],
        created_by=sample_member.member_id,
        surro_service_id="service-soft-delete",
    )
    db.add(row)
    db.commit()

    assert service_crud.delete_service_by_surro_id(
        db,
        "service-soft-delete",
        deleted_by=sample_member.member_id,
    )
    assert service_crud.get_service_by_surro_id(db, "service-soft-delete") is None

    deleted = db.query(Service).filter(Service.id == row.id).one()
    assert deleted.deleted_at is not None
    assert deleted.deleted_by == sample_member.member_id
    assert deleted.is_active is False


def test_recreate_service_preserves_soft_deleted_history(db, sample_member):
    old = service_crud.create_service(
        db=db,
        service=ServiceCreate(name="old-service", description=None, tags=[]),
        created_by=sample_member.member_id,
        surro_service_id="service-reused",
    )
    assert service_crud.delete_service_by_surro_id(
        db,
        "service-reused",
        deleted_by=sample_member.member_id,
    )

    current = service_crud.create_service(
        db=db,
        service=ServiceCreate(name="current-service", description=None, tags=[]),
        created_by=sample_member.member_id,
        surro_service_id="service-reused",
    )

    assert current.id != old.id
    db.refresh(old)
    assert old.deleted_at is not None
    assert old.is_active is False


def test_workflow_execute_preserves_structured_upstream_409(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(409, json={"detail": "already deployed"})

    monkeypatch.setattr(
        workflow_service, "_make_authenticated_request", fake_request
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(workflow_service.execute_workflow("wf-conflict"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "already deployed"


def test_workflow_request_timeout_maps_to_504(monkeypatch):
    class Client:
        async def get(self, url, **kwargs):
            raise httpx.ReadTimeout("slow")

    async def fake_token():
        return "test-token"

    monkeypatch.setattr(workflow_service, "client", Client())
    monkeypatch.setattr(workflow_service, "_get_valid_token", fake_token)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            workflow_service._make_authenticated_request(
                "GET", "https://upstream.invalid/workflows"
            )
        )

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "upstream service timeout"


def test_model_list_rejects_unknown_filter_type_before_upstream(
    db, sample_member, monkeypatch
):
    called = False

    async def fake_get_models(**kwargs):
        nonlocal called
        called = True
        return []

    monkeypatch.setattr("app.routes.model.model_service.get_models", fake_get_models)

    with _client_with_overrides(db, sample_member) as client:
        response = client.get("/api/v1/models?filter_type=unknown")

    assert response.status_code == 422
    assert called is False
