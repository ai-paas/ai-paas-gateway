"""
서비스 상세 응답의 워크플로우 컴포넌트 기반 KB/모델/프롬프트 보강 테스트.

monkeypatch 경로는 인스턴스 직접 import 위치 기준:
- app.services.service_service.workflow_service
- app.services.service_service.knowledge_base_service
- app.services.service_service.model_service
- app.services.service_service.prompt_service
- app.services.service_service.knowledge_base_crud
- app.services.service_service.model_crud
- app.services.service_service.prompt_crud
"""
from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models.service import Service
from app.schemas.service import ExternalServiceDetailResponse


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


_SERVICE_UUID = "87cded99-326a-4b6b-a2e2-71944cf89d02"
_WF1 = "1e9d0785-34eb-4a64-9a71-9ddbf6f7eb72"
_WF2 = "367db9e7-39dc-44bb-a095-1755040d242c"


def _seed_service(db, member):
    db.add(
        Service(
            name="aipaas-gw-test-service",
            description="gateway test",
            tags=["test"],
            created_by=member.member_id,
            surro_service_id=_SERVICE_UUID,
        )
    )
    db.flush()


def _service_payload(workflow_ids: List[str]) -> Dict[str, Any]:
    workflows = []
    for wid in workflow_ids:
        workflows.append(
            {
                "created_at": "2026-05-12T11:33:09",
                "updated_at": "2026-05-19T17:51:51",
                "id": wid,
                "name": f"wf-{wid[:8]}",
                "description": None,
                "status": "DRAFT",
                "service_id": _SERVICE_UUID,
                "creator_id": 1,
                "is_template": False,
                "template_id": None,
                "category": None,
            }
        )
    return {
        "created_at": "2026-04-14T20:28:55",
        "updated_at": "2026-04-14T20:28:55",
        "id": _SERVICE_UUID,
        "name": "aipaas-gw-test-service",
        "description": "gateway test",
        "tags": ["test"],
        "creator_id": 1,
        "creator": {
            "id": 1,
            "username": "tester",
            "name": "tester",
        },
        "workflows": workflows,
        "monitoring_data": None,
    }


def _make_component(
    *,
    comp_type: str,
    comp_id: str = "comp-1",
    workflow_id: str = _WF1,
    model_id: Optional[int] = None,
    knowledge_base_id: Optional[int] = None,
    prompt_id: Optional[int] = None,
    model: Optional[Any] = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=comp_id,
        workflow_id=workflow_id,
        name=comp_id,
        type=comp_type,
        model_id=model_id,
        model=model,
        knowledge_base_id=knowledge_base_id,
        prompt_id=prompt_id,
        config=None,
        x=None,
        y=None,
    )


def _make_workflow_detail(
    wf_id: str, name: str, components: List[Any]
) -> SimpleNamespace:
    return SimpleNamespace(
        id=wf_id,
        name=name,
        components=components,
    )


def _fake_external_kb(kb_id: int, name: str = "kb-fake") -> SimpleNamespace:
    return SimpleNamespace(
        id=kb_id,
        name=name,
        description=f"desc-{kb_id}",
        collection_name=f"col-{kb_id}",
        embedding_model_id=10,
        search_method_id=2,
    )


def _fake_external_model(model_id: int, name: str = "model-fake") -> SimpleNamespace:
    return SimpleNamespace(
        id=model_id,
        name=name,
        description=f"model-desc-{model_id}",
        provider_info=SimpleNamespace(id=1, name="huggingface"),
        type_info=SimpleNamespace(id=1, name="llm"),
        format_info=SimpleNamespace(id=1, name="safetensors"),
        task="text-generation",
        visibility="public",
        created_at=datetime(2026, 4, 1, 12, 0, 0),
    )


def _fake_external_prompt(prompt_id: int, name: str = "prompt-fake") -> SimpleNamespace:
    return SimpleNamespace(
        id=prompt_id,
        name=name,
        description=f"prompt-desc-{prompt_id}",
        content="hello {{name}}",
        prompt_variable=[SimpleNamespace(id=1, name="name", prompt_id=prompt_id)],
    )


def _fake_db_kb(kb_id: int, created_by: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=kb_id,
        surro_knowledge_id=kb_id,
        created_at=datetime(2026, 5, 1, 9, 0, 0),
        created_by=created_by,
    )


def _fake_db_prompt(prompt_id: int, created_by: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=prompt_id,
        surro_prompt_id=prompt_id,
        created_at=datetime(2026, 5, 2, 10, 0, 0),
        created_by=created_by,
    )


def _patch_upstream_service(monkeypatch, payload: Dict[str, Any]):
    async def fake_get_service(service_id, user_info=None):
        return ExternalServiceDetailResponse(**payload)

    monkeypatch.setattr(
        "app.routes.service.service_service.get_service", fake_get_service
    )


def _patch_workflow_lookup(monkeypatch, mapping: Dict[str, Any]):
    """workflow_id -> workflow detail 또는 Exception 인스턴스."""

    async def fake_get_workflow(workflow_id, user_info=None):
        result = mapping.get(workflow_id)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(
        "app.services.service_service.workflow_service.get_workflow",
        fake_get_workflow,
    )


# ---------------------------------------------------------------------------
# 1. KB/모델/프롬프트 컴포넌트 각 1개 → 3 리스트에 1건씩.
# ---------------------------------------------------------------------------
def test_enrich_returns_kb_model_and_prompt(db, sample_member, monkeypatch):
    _seed_service(db, sample_member)
    _patch_upstream_service(monkeypatch, _service_payload([_WF1]))

    components = [
        _make_component(comp_type="KNOWLEDGE_BASE", comp_id="c-kb", knowledge_base_id=4),
        _make_component(
            comp_type="MODEL",
            comp_id="c-model",
            model_id=7,
            prompt_id=12,
        ),
    ]
    _patch_workflow_lookup(
        monkeypatch, {_WF1: _make_workflow_detail(_WF1, "wf-one", components)}
    )

    monkeypatch.setattr(
        "app.services.service_service.knowledge_base_crud.get_active_knowledge_base_by_surro_id",
        lambda db, surro_knowledge_id: _fake_db_kb(surro_knowledge_id, sample_member.member_id),
    )
    monkeypatch.setattr(
        "app.services.service_service.model_crud.check_model_ownership",
        lambda db, model_id, member_id: True,
    )
    monkeypatch.setattr(
        "app.services.service_service.prompt_crud.get_prompt_by_surro_id",
        lambda db, surro_prompt_id: _fake_db_prompt(surro_prompt_id, sample_member.member_id),
    )

    async def fake_get_kb(kb_id, user_info=None):
        return _fake_external_kb(kb_id)

    async def fake_get_model(model_id, user_info=None):
        return _fake_external_model(model_id)

    async def fake_get_prompt(prompt_id, user_info=None):
        return _fake_external_prompt(prompt_id)

    monkeypatch.setattr(
        "app.services.service_service.knowledge_base_service.get_knowledge_base",
        fake_get_kb,
    )
    monkeypatch.setattr(
        "app.services.service_service.model_service.get_model", fake_get_model
    )
    monkeypatch.setattr(
        "app.services.service_service.prompt_service.get_prompt", fake_get_prompt
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{_SERVICE_UUID}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["knowledge_bases"]) == 1
    assert data["knowledge_bases"][0]["id"] == 4
    assert data["knowledge_bases"][0]["type"] == "RAG"
    assert data["knowledge_bases"][0]["workflow_refs"] == [
        {"id": _WF1, "name": "wf-one"}
    ]
    assert len(data["models"]) == 1
    assert data["models"][0]["id"] == 7
    assert data["models"][0]["provider"] == "huggingface"
    assert data["models"][0]["model_type"] == "llm"
    assert len(data["prompts"]) == 1
    assert data["prompts"][0]["id"] == 12
    assert data["prompts"][0]["variables"] == ["name"]


# ---------------------------------------------------------------------------
# 2. 두 워크플로우가 동일 model_id 공유 → models 1건 + workflow_refs 길이 2.
# ---------------------------------------------------------------------------
def test_enrich_dedupes_shared_model_across_workflows(db, sample_member, monkeypatch):
    _seed_service(db, sample_member)
    _patch_upstream_service(monkeypatch, _service_payload([_WF1, _WF2]))

    _patch_workflow_lookup(
        monkeypatch,
        {
            _WF1: _make_workflow_detail(
                _WF1,
                "wf-one",
                [_make_component(comp_type="MODEL", comp_id="c1", model_id=100)],
            ),
            _WF2: _make_workflow_detail(
                _WF2,
                "wf-two",
                [_make_component(comp_type="MODEL", comp_id="c2", model_id=100)],
            ),
        },
    )
    monkeypatch.setattr(
        "app.services.service_service.model_crud.check_model_ownership",
        lambda db, model_id, member_id: True,
    )

    call_counter = {"n": 0}

    async def fake_get_model(model_id, user_info=None):
        call_counter["n"] += 1
        return _fake_external_model(model_id)

    monkeypatch.setattr(
        "app.services.service_service.model_service.get_model", fake_get_model
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{_SERVICE_UUID}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["models"]) == 1
    assert data["models"][0]["id"] == 100
    refs = data["models"][0]["workflow_refs"]
    assert len(refs) == 2
    assert {r["id"] for r in refs} == {_WF1, _WF2}
    assert call_counter["n"] == 1  # 동일 ID는 한 번만 단건 조회


# ---------------------------------------------------------------------------
# 3. 컴포넌트 model inline embed → model_service.get_model 호출 0회.
# ---------------------------------------------------------------------------
def test_enrich_uses_inline_model_when_available(db, sample_member, monkeypatch):
    _seed_service(db, sample_member)
    _patch_upstream_service(monkeypatch, _service_payload([_WF1]))

    inline_model = _fake_external_model(50, name="inline-model")
    _patch_workflow_lookup(
        monkeypatch,
        {
            _WF1: _make_workflow_detail(
                _WF1,
                "wf-one",
                [
                    _make_component(
                        comp_type="MODEL",
                        comp_id="c1",
                        model_id=50,
                        model=inline_model,
                    )
                ],
            ),
        },
    )
    monkeypatch.setattr(
        "app.services.service_service.model_crud.check_model_ownership",
        lambda db, model_id, member_id: True,
    )

    call_counter = {"n": 0}

    async def fake_get_model(model_id, user_info=None):
        call_counter["n"] += 1
        return _fake_external_model(model_id)

    monkeypatch.setattr(
        "app.services.service_service.model_service.get_model", fake_get_model
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{_SERVICE_UUID}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert len(data["models"]) == 1
    assert data["models"][0]["name"] == "inline-model"
    assert call_counter["n"] == 0


# ---------------------------------------------------------------------------
# 4. KB 단건 호출 raise → 그 KB만 누락, 응답 200.
# ---------------------------------------------------------------------------
def test_enrich_best_effort_on_kb_failure(db, sample_member, monkeypatch):
    _seed_service(db, sample_member)
    _patch_upstream_service(monkeypatch, _service_payload([_WF1]))

    _patch_workflow_lookup(
        monkeypatch,
        {
            _WF1: _make_workflow_detail(
                _WF1,
                "wf-one",
                [
                    _make_component(
                        comp_type="KNOWLEDGE_BASE",
                        comp_id="c-kb1",
                        knowledge_base_id=1,
                    ),
                    _make_component(
                        comp_type="KNOWLEDGE_BASE",
                        comp_id="c-kb2",
                        knowledge_base_id=2,
                    ),
                ],
            ),
        },
    )
    monkeypatch.setattr(
        "app.services.service_service.knowledge_base_crud.get_active_knowledge_base_by_surro_id",
        lambda db, surro_knowledge_id: _fake_db_kb(surro_knowledge_id, sample_member.member_id),
    )

    async def fake_get_kb(kb_id, user_info=None):
        if kb_id == 1:
            raise RuntimeError("upstream boom")
        return _fake_external_kb(kb_id)

    monkeypatch.setattr(
        "app.services.service_service.knowledge_base_service.get_knowledge_base",
        fake_get_kb,
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{_SERVICE_UUID}")

    assert response.status_code == 200, response.text
    data = response.json()
    ids = [kb["id"] for kb in data["knowledge_bases"]]
    assert ids == [2]  # 1번은 누락, 2번만 노출


# ---------------------------------------------------------------------------
# 5. workflow detail raise → 해당 wf 컴포넌트 누락, 응답 200.
# ---------------------------------------------------------------------------
def test_enrich_best_effort_on_workflow_detail_failure(db, sample_member, monkeypatch):
    _seed_service(db, sample_member)
    _patch_upstream_service(monkeypatch, _service_payload([_WF1, _WF2]))

    _patch_workflow_lookup(
        monkeypatch,
        {
            _WF1: RuntimeError("wf1 down"),
            _WF2: _make_workflow_detail(
                _WF2,
                "wf-two",
                [_make_component(comp_type="MODEL", comp_id="c1", model_id=9)],
            ),
        },
    )
    monkeypatch.setattr(
        "app.services.service_service.model_crud.check_model_ownership",
        lambda db, model_id, member_id: True,
    )

    async def fake_get_model(model_id, user_info=None):
        return _fake_external_model(model_id)

    monkeypatch.setattr(
        "app.services.service_service.model_service.get_model", fake_get_model
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{_SERVICE_UUID}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert [m["id"] for m in data["models"]] == [9]
    assert data["models"][0]["workflow_refs"] == [{"id": _WF2, "name": "wf-two"}]


# ---------------------------------------------------------------------------
# 6. 권한 누락 — KB created_by != member_id, not admin → 누락. admin은 통과.
# ---------------------------------------------------------------------------
def test_enrich_skips_kb_when_user_lacks_permission(db, sample_member, monkeypatch):
    _seed_service(db, sample_member)
    _patch_upstream_service(monkeypatch, _service_payload([_WF1]))
    _patch_workflow_lookup(
        monkeypatch,
        {
            _WF1: _make_workflow_detail(
                _WF1,
                "wf-one",
                [
                    _make_component(
                        comp_type="KNOWLEDGE_BASE",
                        comp_id="c-kb",
                        knowledge_base_id=99,
                    )
                ],
            ),
        },
    )
    # 다른 사용자가 소유한 KB
    monkeypatch.setattr(
        "app.services.service_service.knowledge_base_crud.get_active_knowledge_base_by_surro_id",
        lambda db, surro_knowledge_id: _fake_db_kb(surro_knowledge_id, "other-user"),
    )

    kb_call_counter = {"n": 0}

    async def fake_get_kb(kb_id, user_info=None):
        kb_call_counter["n"] += 1
        return _fake_external_kb(kb_id)

    monkeypatch.setattr(
        "app.services.service_service.knowledge_base_service.get_knowledge_base",
        fake_get_kb,
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{_SERVICE_UUID}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["knowledge_bases"] == []
    assert kb_call_counter["n"] == 0  # 권한 거부면 단건 호출도 안 함


def test_enrich_admin_bypasses_kb_ownership_check(db, admin_member, monkeypatch):
    _seed_service(db, admin_member)
    _patch_upstream_service(monkeypatch, _service_payload([_WF1]))
    _patch_workflow_lookup(
        monkeypatch,
        {
            _WF1: _make_workflow_detail(
                _WF1,
                "wf-one",
                [
                    _make_component(
                        comp_type="KNOWLEDGE_BASE",
                        comp_id="c-kb",
                        knowledge_base_id=42,
                    )
                ],
            ),
        },
    )
    # 다른 사용자가 소유했지만 호출자는 admin
    monkeypatch.setattr(
        "app.services.service_service.knowledge_base_crud.get_active_knowledge_base_by_surro_id",
        lambda db, surro_knowledge_id: _fake_db_kb(surro_knowledge_id, "other-user"),
    )

    async def fake_get_kb(kb_id, user_info=None):
        return _fake_external_kb(kb_id)

    monkeypatch.setattr(
        "app.services.service_service.knowledge_base_service.get_knowledge_base",
        fake_get_kb,
    )

    with _client_with_overrides(db, admin_member) as client:
        response = client.get(f"/api/v1/services/{_SERVICE_UUID}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert [kb["id"] for kb in data["knowledge_bases"]] == [42]


# ---------------------------------------------------------------------------
# 7. catalog 모델 — ownership 없어도 통과. 일반 모델은 skip.
# ---------------------------------------------------------------------------
def test_enrich_allows_catalog_model_without_ownership(db, sample_member, monkeypatch):
    from app.models.model import Model

    catalog_model_id = 7777
    db.add(
        Model(
            name="catalog-llm",
            description="public catalog",
            created_by="catalog-admin",
            surro_model_id=catalog_model_id,
            is_catalog=True,
        )
    )
    db.flush()

    _seed_service(db, sample_member)
    _patch_upstream_service(monkeypatch, _service_payload([_WF1]))
    _patch_workflow_lookup(
        monkeypatch,
        {
            _WF1: _make_workflow_detail(
                _WF1,
                "wf-one",
                [
                    _make_component(
                        comp_type="MODEL", comp_id="c1", model_id=catalog_model_id
                    ),
                    _make_component(
                        comp_type="MODEL", comp_id="c2", model_id=8888
                    ),
                ],
            ),
        },
    )

    def fake_ownership(db, model_id, member_id):
        return False  # ownership 항상 없음

    monkeypatch.setattr(
        "app.services.service_service.model_crud.check_model_ownership", fake_ownership
    )

    async def fake_get_model(model_id, user_info=None):
        return _fake_external_model(model_id)

    monkeypatch.setattr(
        "app.services.service_service.model_service.get_model", fake_get_model
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{_SERVICE_UUID}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert [m["id"] for m in data["models"]] == [catalog_model_id]


# ---------------------------------------------------------------------------
# 8. 컴포넌트 없는 워크플로우 → 3 리스트 모두 빈 배열.
# ---------------------------------------------------------------------------
def test_enrich_returns_empty_when_no_referenceable_components(
    db, sample_member, monkeypatch
):
    _seed_service(db, sample_member)
    _patch_upstream_service(monkeypatch, _service_payload([_WF1]))
    _patch_workflow_lookup(
        monkeypatch,
        {
            _WF1: _make_workflow_detail(
                _WF1,
                "wf-one",
                [
                    _make_component(comp_type="START", comp_id="start"),
                    _make_component(comp_type="END", comp_id="end"),
                ],
            ),
        },
    )

    with _client_with_overrides(db, sample_member) as client:
        response = client.get(f"/api/v1/services/{_SERVICE_UUID}")

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["knowledge_bases"] == []
    assert data["models"] == []
    assert data["prompts"] == []
