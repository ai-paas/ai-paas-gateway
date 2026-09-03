import asyncio
from io import BytesIO

from fastapi import UploadFile

from app.main import app
from app.schemas.dataset import DatasetCreateRequest, DatasetKindEnum
from app.services.dataset_service import dataset_service


class _Response:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self):
        return self._payload


def test_dataset_kind_openapi_contract():
    app.openapi_schema = None
    spec = app.openapi()
    schemas = spec["components"]["schemas"]

    assert "/api/v1/datasets/kinds" in spec["paths"]
    assert schemas["DatasetKindEnum"]["enum"] == [
        "object-detection",
        "protein-classification",
    ]
    for schema_name in (
        "Body_validate_dataset_api_v1_datasets_validate_post",
        "Body_create_dataset_api_v1_datasets_post",
    ):
        assert "dataset_kind" in schemas[schema_name]["required"]
    assert "kind" in schemas["DatasetReadSchema"]["properties"]


def test_dataset_kind_is_forwarded_to_mlops(monkeypatch):
    captured = []

    async def fake_request(method, url, user_info=None, **kwargs):
        captured.append((method, url, kwargs))
        if url.endswith("/datasets/kinds"):
            return _Response([
                {
                    "name": "object-detection",
                    "description": "객체 감지 데이터셋",
                    "accepted_formats": ["coco"],
                    "supported_models": ["yolox_s"],
                }
            ])
        return _Response({"is_valid": True, "message": "ok"})

    class FakeClient:
        async def post(self, url, **kwargs):
            captured.append(("POST", url, kwargs))
            return _Response({
                "id": 1,
                "name": "protein",
                "kind": "protein-classification",
                "dataset_registry": {
                    "id": 1,
                    "artifact_path": "datasets/1",
                    "uri": "mlflow-artifacts:/datasets/1",
                    "dataset_id": 1,
                },
            })

    async def fake_token():
        return "test-token"

    monkeypatch.setattr(dataset_service, "_make_authenticated_request", fake_request)
    monkeypatch.setattr(dataset_service, "_get_valid_token", fake_token)
    monkeypatch.setattr(dataset_service, "client", FakeClient())

    async def run():
        kinds = await dataset_service.get_dataset_kinds()
        assert kinds[0].name is DatasetKindEnum.OBJECT_DETECTION

        await dataset_service.validate_dataset(
            file=UploadFile(BytesIO(b"zip"), filename="dataset.zip"),
            dataset_kind=DatasetKindEnum.OBJECT_DETECTION,
        )
        await dataset_service.create_dataset(
            dataset_data=DatasetCreateRequest(
                name="protein",
                dataset_kind=DatasetKindEnum.PROTEIN_CLASSIFICATION,
            ),
            file=UploadFile(BytesIO(b"zip"), filename="dataset.zip"),
        )

    asyncio.run(run())

    validate_call = next(call for call in captured if call[1].endswith("/datasets/validate"))
    create_call = next(call for call in captured if call[1].endswith("/datasets"))
    assert validate_call[2]["data"] == {"dataset_kind": "object-detection"}
    assert create_call[2]["data"]["dataset_kind"] == "protein-classification"
