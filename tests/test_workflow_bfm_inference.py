"""BFM(task 기반) 추론 엔드포인트 테스트 (api-spec 2026-07-01).

대상: /test/protein-classification · /test/fill-mask · /test/protein-structure-prediction

검증 포인트:
- JSON body가 schema → service layer 까지 손실 없이 전달되는지 (선택 파라미터 기본값 포함)
- service 응답(task 필드 + task별 result 스키마)이 게이트웨이 응답으로 정상 직렬화되는지
- 게이트웨이 DB 매핑이 없으면 404
- 본인 소유 워크플로우 또는 admin만 실행 가능한지
- 필수 입력 누락 시 게이트웨이 Pydantic 검증에서 422
- 구조예측 timeout과 upstream 5xx 매핑이 gateway 계약을 따르는지
"""
import asyncio
from contextlib import contextmanager

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.config import settings
from app.cruds.workflow import workflow_crud
from app.database import get_db
from app.main import app
from app.schemas.workflow import (
    WorkflowProteinClassificationTestResponse,
    WorkflowFillMaskTestResponse,
    WorkflowProteinStructurePredictionTestResponse,
)
from app.services.workflow_service import workflow_service


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


def _make_workflow(db, member, surro_id):
    workflow_crud.create_workflow(
        db,
        name=surro_id,
        description=None,
        created_by=member.member_id,
        surro_workflow_id=surro_id,
    )


@pytest.mark.parametrize(
    ("suffix", "request_kwargs"),
    [
        ("rag", {"data": {"text": "test"}}),
        ("ml", {"files": {"image": ("test.png", b"png", "image/png")}}),
        (
            "protein-classification",
            {"json": {"epitope": "GILGFVFTL", "cdr3b": "CASSIRSSYEQYF"}},
        ),
        ("fill-mask", {"json": {"sequence": "AB<mask>CD"}}),
        ("protein-structure-prediction", {"json": {"sequence": "MQIF"}}),
    ],
)
def test_inference_rejects_non_owner(
    db, sample_member, admin_member, suffix, request_kwargs
):
    surro_id = f"wf-foreign-{suffix}"
    _make_workflow(db, admin_member, surro_id)

    with _client_with_overrides(db, sample_member) as client:
        response = client.post(
            f"/api/v1/workflows/{surro_id}/test/{suffix}", **request_kwargs
        )

    assert response.status_code == 403, response.text
    assert response.json()["detail"] == "Permission denied"


@pytest.mark.parametrize(
    ("suffix", "service_method", "request_kwargs", "response_type"),
    [
        (
            "protein-classification",
            "test_protein_classification_workflow",
            {"json": {"epitope": "GILGFVFTL", "cdr3b": "CASSIRSSYEQYF"}},
            WorkflowProteinClassificationTestResponse,
        ),
        (
            "fill-mask",
            "test_fill_mask_workflow",
            {"json": {"sequence": "AB<mask>CD"}},
            WorkflowFillMaskTestResponse,
        ),
        (
            "protein-structure-prediction",
            "test_protein_structure_prediction_workflow",
            {"json": {"sequence": "MQIF"}},
            WorkflowProteinStructurePredictionTestResponse,
        ),
    ],
)
def test_admin_can_execute_other_users_bfm_workflow(
    db,
    sample_member,
    admin_member,
    monkeypatch,
    suffix,
    service_method,
    request_kwargs,
    response_type,
):
    surro_id = f"wf-admin-{suffix}"
    _make_workflow(db, sample_member, surro_id)

    async def fake(workflow_id, *args, **kwargs):
        return response_type(workflow_id=workflow_id, execution_order=[], results=[])

    monkeypatch.setattr(workflow_service, service_method, fake)

    with _client_with_overrides(db, admin_member) as client:
        response = client.post(
            f"/api/v1/workflows/{surro_id}/test/{suffix}", **request_kwargs
        )

    assert response.status_code == 200, response.text


class TestProteinClassification:
    _URL = "/api/v1/workflows/{}/test/protein-classification"

    def test_passthrough_and_serialization(self, db, sample_member, monkeypatch):
        _make_workflow(db, sample_member, "wf-pc-1")
        captured = {}

        async def fake(workflow_id, epitope, cdr3b, user_info=None):
            captured.update(
                workflow_id=workflow_id, epitope=epitope, cdr3b=cdr3b, user_info=user_info
            )
            return WorkflowProteinClassificationTestResponse(
                workflow_id=workflow_id,
                execution_order=["model-1a2b3c"],
                results=[
                    {
                        "component_id": "model-1a2b3c",
                        "component_name": "ESM2-ft",
                        "component_type": "MODEL",
                        "model_type": "BFM",
                        "task": "protein-classification",
                        "result": {
                            "predictions": [
                                {
                                    "label": 0,
                                    "score": 0.5027,
                                    "probabilities": {"0": 0.5027, "1": 0.4973},
                                }
                            ],
                            "input_info": {"epitope": epitope, "cdr3b": cdr3b},
                        },
                    }
                ],
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.test_protein_classification_workflow",
            fake,
        )

        with _client_with_overrides(db, sample_member) as client:
            resp = client.post(
                self._URL.format("wf-pc-1"),
                json={"epitope": "GILGFVFTL", "cdr3b": "CASSIRSSYEQYF"},
            )

        assert resp.status_code == 200, resp.text
        assert captured["workflow_id"] == "wf-pc-1"
        assert captured["epitope"] == "GILGFVFTL"
        assert captured["cdr3b"] == "CASSIRSSYEQYF"
        assert captured["user_info"]["member_id"] == sample_member.member_id

        body = resp.json()
        assert body["workflow_id"] == "wf-pc-1"
        r0 = body["results"][0]
        assert r0["model_type"] == "BFM"
        assert r0["task"] == "protein-classification"
        pred = r0["result"]["predictions"][0]
        assert pred["label"] == 0
        assert pred["probabilities"] == {"0": 0.5027, "1": 0.4973}

    def test_404_when_workflow_not_mapped(self, db, sample_member):
        with _client_with_overrides(db, sample_member) as client:
            resp = client.post(
                self._URL.format("unknown-wf"),
                json={"epitope": "X", "cdr3b": "Y"},
            )
        assert resp.status_code == 404, resp.text

    def test_422_when_required_field_missing(self, db, sample_member):
        _make_workflow(db, sample_member, "wf-pc-2")
        with _client_with_overrides(db, sample_member) as client:
            resp = client.post(
                self._URL.format("wf-pc-2"),
                json={"epitope": "GILGFVFTL"},  # cdr3b 누락
            )
        assert resp.status_code == 422, resp.text


class TestFillMask:
    _URL = "/api/v1/workflows/{}/test/fill-mask"

    def test_passthrough_default_top_k(self, db, sample_member, monkeypatch):
        _make_workflow(db, sample_member, "wf-fm-1")
        captured = {}

        async def fake(workflow_id, sequence, top_k=5, user_info=None):
            captured.update(workflow_id=workflow_id, sequence=sequence, top_k=top_k)
            return WorkflowFillMaskTestResponse(
                workflow_id=workflow_id,
                execution_order=["model-9f8e7d"],
                results=[
                    {
                        "component_id": "model-9f8e7d",
                        "component_name": "ESM2-base",
                        "component_type": "MODEL",
                        "model_type": "BFM",
                        "task": "fill-mask",
                        "result": {
                            "predictions": [
                                {
                                    "position": 10,
                                    "predictions": [
                                        {"token": "L", "score": 0.42},
                                        {"token": "V", "score": 0.19},
                                    ],
                                }
                            ],
                            "input_info": {"sequence": sequence, "top_k": top_k},
                        },
                    }
                ],
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.test_fill_mask_workflow", fake
        )

        with _client_with_overrides(db, sample_member) as client:
            resp = client.post(
                self._URL.format("wf-fm-1"),
                json={"sequence": "MKTAYIAKQR<mask>ISFVKSHFSRQLEERLGL"},
            )

        assert resp.status_code == 200, resp.text
        # top_k 미지정 시 게이트웨이 기본값 5가 service까지 전달돼야 함
        assert captured["top_k"] == 5
        assert captured["sequence"].count("<mask>") == 1

        body = resp.json()
        pos = body["results"][0]["result"]["predictions"][0]
        assert pos["position"] == 10
        assert pos["predictions"][0]["token"] == "L"

    def test_custom_top_k_passthrough(self, db, sample_member, monkeypatch):
        _make_workflow(db, sample_member, "wf-fm-2")
        captured = {}

        async def fake(workflow_id, sequence, top_k=5, user_info=None):
            captured["top_k"] = top_k
            return WorkflowFillMaskTestResponse(
                workflow_id=workflow_id, execution_order=[], results=[]
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.test_fill_mask_workflow", fake
        )

        with _client_with_overrides(db, sample_member) as client:
            resp = client.post(
                self._URL.format("wf-fm-2"),
                json={"sequence": "AB<mask>CD", "top_k": 3},
            )

        assert resp.status_code == 200, resp.text
        assert captured["top_k"] == 3

    def test_explicit_null_top_k_rejected(self, db, sample_member, monkeypatch):
        _make_workflow(db, sample_member, "wf-fm-null")
        captured = {}

        async def fake(workflow_id, sequence, top_k=5, user_info=None):
            captured["top_k"] = top_k
            return WorkflowFillMaskTestResponse(
                workflow_id=workflow_id, execution_order=[], results=[]
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.test_fill_mask_workflow", fake
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post(
                self._URL.format("wf-fm-null"),
                json={"sequence": "AB<mask>CD", "top_k": None},
            )

        assert response.status_code == 422, response.text
        assert "top_k" not in captured

    def test_422_when_sequence_missing(self, db, sample_member):
        _make_workflow(db, sample_member, "wf-fm-3")
        with _client_with_overrides(db, sample_member) as client:
            resp = client.post(self._URL.format("wf-fm-3"), json={"top_k": 5})
        assert resp.status_code == 422, resp.text


class TestProteinStructurePrediction:
    _URL = "/api/v1/workflows/{}/test/protein-structure-prediction"

    def test_passthrough_defaults_and_serialization(self, db, sample_member, monkeypatch):
        _make_workflow(db, sample_member, "wf-sp-1")
        captured = {}

        async def fake(
            workflow_id, sequence, num_loops=3, num_sampling_steps=50, user_info=None
        ):
            captured.update(
                sequence=sequence,
                num_loops=num_loops,
                num_sampling_steps=num_sampling_steps,
            )
            return WorkflowProteinStructurePredictionTestResponse(
                workflow_id=workflow_id,
                execution_order=["model-3c2b1a"],
                results=[
                    {
                        "component_id": "model-3c2b1a",
                        "component_name": "ESMFold2",
                        "component_type": "MODEL",
                        "model_type": "BFM",
                        "task": "protein-structure-prediction",
                        "result": {
                            "predictions": [
                                {
                                    "pdb": "ATOM      1  N   MET A   1     ...",
                                    "plddt_mean": 0.72,
                                    "ptm": 0.81,
                                    "iptm": 0.0,
                                }
                            ],
                            "input_info": {
                                "sequence": sequence,
                                "num_loops": num_loops,
                                "num_sampling_steps": num_sampling_steps,
                            },
                        },
                    }
                ],
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.test_protein_structure_prediction_workflow",
            fake,
        )

        with _client_with_overrides(db, sample_member) as client:
            resp = client.post(
                self._URL.format("wf-sp-1"),
                json={"sequence": "MQIFVKTLTGKTITLEVEPSDTIENVKAKIQDKEGIPPDQQRLIFAGKQLEDGRTLSDYNIQKESTLHLVLRLRGG"},
            )

        assert resp.status_code == 200, resp.text
        # 선택 파라미터 미지정 시 게이트웨이 기본값(3, 50)이 service까지 전달돼야 함
        assert captured["num_loops"] == 3
        assert captured["num_sampling_steps"] == 50

        body = resp.json()
        pred = body["results"][0]["result"]["predictions"][0]
        assert pred["pdb"].startswith("ATOM")
        assert pred["plddt_mean"] == 0.72
        assert pred["iptm"] == 0.0

    def test_404_when_workflow_not_mapped(self, db, sample_member):
        with _client_with_overrides(db, sample_member) as client:
            resp = client.post(
                self._URL.format("unknown-wf"), json={"sequence": "MQIF"}
            )
        assert resp.status_code == 404, resp.text

    def test_explicit_null_options_rejected(self, db, sample_member, monkeypatch):
        _make_workflow(db, sample_member, "wf-sp-null")
        captured = {}

        async def fake(
            workflow_id, sequence, num_loops=3, num_sampling_steps=50, user_info=None
        ):
            captured.update(
                num_loops=num_loops,
                num_sampling_steps=num_sampling_steps,
            )
            return WorkflowProteinStructurePredictionTestResponse(
                workflow_id=workflow_id, execution_order=[], results=[]
            )

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.test_protein_structure_prediction_workflow",
            fake,
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post(
                self._URL.format("wf-sp-null"),
                json={
                    "sequence": "MQIF",
                    "num_loops": None,
                    "num_sampling_steps": None,
                },
            )

        assert response.status_code == 422, response.text
        assert captured == {}


def test_structure_prediction_uses_configured_timeout(monkeypatch):
    captured = {}

    async def fake_request(method, url, user_info=None, **kwargs):
        captured.update(method=method, url=url, user_info=user_info, **kwargs)
        return httpx.Response(
            200,
            json={
                "workflow_id": "wf-timeout",
                "execution_order": [],
                "results": [],
            },
        )

    monkeypatch.setattr(workflow_service, "_make_authenticated_request", fake_request)

    asyncio.run(
        workflow_service.test_protein_structure_prediction_workflow(
            "wf-timeout", "MQIF", user_info={"member_id": "testuser"}
        )
    )

    timeout = captured["timeout"]
    assert timeout.read == settings.PROXY_STRUCTURE_PREDICTION_TIMEOUT
    assert timeout.connect == settings.PROXY_CONNECT_TIMEOUT


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        (
            "test_protein_classification_workflow",
            ("wf-upstream-error", "GILGFVFTL", "CASSIRSSYEQYF"),
        ),
        ("test_fill_mask_workflow", ("wf-upstream-error", "AB<mask>CD")),
        (
            "test_protein_structure_prediction_workflow",
            ("wf-upstream-error", "MQIF"),
        ),
    ],
)
def test_bfm_upstream_5xx_maps_to_502(monkeypatch, method_name, args):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(503, text="KServe is not ready")

    monkeypatch.setattr(workflow_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(getattr(workflow_service, method_name)(*args))

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "upstream service error"


@pytest.mark.parametrize("status_code", [201, 401])
def test_bfm_unexpected_or_auth_upstream_status_maps_to_502(
    monkeypatch, status_code
):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(status_code, json={"detail": "do not expose"})

    monkeypatch.setattr(workflow_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            workflow_service.test_fill_mask_workflow(
                "wf-upstream-error", "AB<mask>CD"
            )
        )

    assert exc_info.value.status_code == 502
    assert exc_info.value.detail == "upstream service error"


def test_bfm_4xx_uses_structured_detail(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(400, json={"detail": "invalid mask token"})

    monkeypatch.setattr(workflow_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            workflow_service.test_fill_mask_workflow(
                "wf-upstream-error", "AB<mask>CD"
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "invalid mask token"


def test_bfm_plain_text_4xx_is_not_exposed(monkeypatch):
    async def fake_request(method, url, user_info=None, **kwargs):
        return httpx.Response(400, text="internal upstream details")

    monkeypatch.setattr(workflow_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            workflow_service.test_fill_mask_workflow(
                "wf-upstream-error", "AB<mask>CD"
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "upstream request rejected"


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        (
            "test_protein_classification_workflow",
            ("wf-upstream-timeout", "GILGFVFTL", "CASSIRSSYEQYF"),
        ),
        ("test_fill_mask_workflow", ("wf-upstream-timeout", "AB<mask>CD")),
        (
            "test_protein_structure_prediction_workflow",
            ("wf-upstream-timeout", "MQIF"),
        ),
    ],
)
def test_bfm_timeout_maps_to_504(monkeypatch, method_name, args):
    async def fake_request(method, url, user_info=None, **kwargs):
        raise httpx.ReadTimeout("slow upstream")

    monkeypatch.setattr(workflow_service, "_make_authenticated_request", fake_request)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(getattr(workflow_service, method_name)(*args))

    assert exc_info.value.status_code == 504
    assert exc_info.value.detail == "upstream service timeout"


def test_bfm_response_accepts_typed_component_error():
    response = WorkflowFillMaskTestResponse(
        workflow_id="wf-error",
        execution_order=["model-error"],
        results=[
            {
                "component_id": "model-error",
                "component_name": "ESM2-base",
                "component_type": "MODEL",
                "model_type": "BFM",
                "error": "inference failed",
            }
        ],
    )

    assert response.results[0].error == "inference failed"


def test_gateway_openapi_documents_bfm_contract():
    spec = app.openapi()

    for suffix in (
        "protein-classification",
        "fill-mask",
        "protein-structure-prediction",
    ):
        operation = spec["paths"][
            f"/api/v1/workflows/{{surro_workflow_id}}/test/{suffix}"
        ]["post"]
        assert "application/json" in operation["requestBody"]["content"]
        assert "created_by" in operation["description"]
        assert "502" in operation["description"]
        assert "422" in operation["description"]

    for schema_name, task in (
        ("ProteinClassificationComponentResult", "protein-classification"),
        ("FillMaskComponentResult", "fill-mask"),
        ("StructurePredictionComponentResult", "protein-structure-prediction"),
    ):
        component_schema = spec["components"]["schemas"][schema_name]
        assert {"model_type", "task", "result"} <= set(component_schema["required"])
        assert component_schema["properties"]["model_type"]["const"] == "BFM"
        assert component_schema["properties"]["task"]["const"] == task

    model_create = spec["paths"]["/api/v1/models"]["post"]
    body_ref = model_create["requestBody"]["content"]["multipart/form-data"]["schema"][
        "$ref"
    ]
    body_schema = spec["components"]["schemas"][body_ref.rsplit("/", 1)[-1]]
    task_description = body_schema["properties"]["task"]["description"]
    for task in (
        "embedding",
        "text-generation",
        "object-detection",
        "fill-mask",
        "protein-classification",
        "protein-structure-prediction",
        "vqa",
    ):
        assert task in task_description

    response_task_description = spec["components"]["schemas"][
        "ModelCreateResponse"
    ]["properties"]["task"]["description"]
    assert "protein-structure-prediction" in response_task_description
