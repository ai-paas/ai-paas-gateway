from app.schemas.hub_connect import ExtendedHubModelResponse, HubModelResponse


def test_hub_model_response_fills_hf_list_derived_fields():
    model = HubModelResponse(
        **{
            "author": "sentence-transformers",
            "downloads": 251654846,
            "gated": False,
            "id": "sentence-transformers/all-MiniLM-L6-v2",
            "availableInferenceProviders": [
                {
                    "provider": "hf-inference",
                    "task": "sentence-similarity",
                }
            ],
            "lastModified": "2026-06-01T06:29:13.000Z",
            "likes": 4911,
            "pipeline_tag": "sentence-similarity",
            "private": False,
            "numParameters": 22713728,
            "parameterDisplay": "22.7M",
            "parameterRange": "small",
        }
    )

    assert model.modelId == "sentence-transformers/all-MiniLM-L6-v2"
    assert model.task == "sentence-similarity"
    assert model.pipeline_tag == "sentence-similarity"
    assert model.numParameters == 22713728
    assert model.parameterDisplay == "22.7M"
    assert model.parameterRange == "small"


def test_hub_model_response_maps_alternate_upstream_field_names():
    model = HubModelResponse(
        **{
            "id": "owner/model/framework/variation",
            "model_id": "owner/model/framework/variation",
            "pipelineTag": "text-generation",
            "libraryName": "transformers",
            "created_at": "2026-01-02T03:04:05Z",
            "lastUpdated": "2026-02-03T04:05:06Z",
            "downloadCount": 123,
            "totalVotes": 45,
            "num_parameters": 7000000000,
            "parameter_display": "7B",
            "parameter_range": "large",
            "revision": "abc123",
            "tags": [{"id": "transformers"}, {"name": "pytorch"}, "safetensors"],
        }
    )

    assert model.modelId == "owner/model/framework/variation"
    assert model.task == "text-generation"
    assert model.pipeline_tag == "text-generation"
    assert model.library_name == "transformers"
    assert model.createdAt == "2026-01-02T03:04:05Z"
    assert model.lastModified == "2026-02-03T04:05:06Z"
    assert model.downloads == 123
    assert model.likes == 45
    assert model.numParameters == 7000000000
    assert model.parameterDisplay == "7B"
    assert model.parameterRange == "large"
    assert model.sha == "abc123"
    assert model.tags == ["transformers", "pytorch", "safetensors"]


def test_hub_model_response_uses_inference_provider_task_when_pipeline_tag_missing():
    model = HubModelResponse(
        **{
            "id": "owner/model",
            "availableInferenceProviders": [
                {
                    "provider": "hf-inference",
                    "task": "fill-mask",
                }
            ],
        }
    )

    assert model.pipeline_tag == "fill-mask"
    assert model.task == "fill-mask"


def test_extended_hub_model_response_maps_detail_metadata_when_available():
    model = ExtendedHubModelResponse(
        **{
            "id": "owner/model",
            "cardData": {
                "library_name": "sentence-transformers",
            },
            "createdDate": "2026-03-04T05:06:07Z",
            "commitSha": "def456",
            "parameter_count": 123456,
            "tags": [{"label": "sentence-transformers"}],
        }
    )

    assert model.library_name == "sentence-transformers"
    assert model.createdAt == "2026-03-04T05:06:07Z"
    assert model.sha == "def456"
    assert model.numParameters == 123456
    assert model.tags == ["sentence-transformers"]


def test_hub_model_response_keeps_missing_optional_fields_as_none():
    model = HubModelResponse(**{"id": "owner/model"})

    assert model.library_name is None
    assert model.createdAt is None
    assert model.lastModified is None
    assert model.sha is None
