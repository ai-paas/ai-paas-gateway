"""워크플로우 → 서비스 link 권한 검증 테스트.

3 라우트가 service_id를 받음:
- POST /workflows                 (service_id: UUID str)
- PUT  /workflows/{id}            (service_id: UUID str)
- POST /templates/{id}/clone      (service_id: int gateway PK)

각 라우트에서 다음을 검증:
- 다른 사용자 소유 service → 403
- 본인 소유 service → 정상 동작
- admin은 어느 service든 link 가능
- 존재하지 않는 service_id → 404
"""
from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.cruds.workflow import workflow_crud
from app.database import get_db
from app.main import app
from app.models.member import Member
from app.models.service import Service
from app.schemas.workflow import (
    ExternalWorkflowDetailResponse,
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


def _make_other_user(db) -> Member:
    other = Member(
        name="다른유저",
        member_id="otheruser",
        email="other@example.com",
        password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
        role="user",
        is_active=True,
    )
    db.add(other)
    db.flush()
    return other


def _make_service(db, member_id: str, surro_uuid: str, name: str = "svc") -> Service:
    svc = Service(
        name=name,
        description=None,
        created_by=member_id,
        surro_service_id=surro_uuid,
    )
    db.add(svc)
    db.flush()
    return svc


def _external_response(name: str, service_id=None, surro_id="surro-uuid-x"):
    return ExternalWorkflowDetailResponse(
        id=surro_id,
        name=name,
        description=None,
        category=None,
        status="DRAFT",
        service_id=service_id,
        creator_id=1,
        is_template=False,
        template_id=None,
        components=[],
        component_connections=[],
    )


# ===== POST /workflows (create_workflow) =====

class TestCreateWorkflowServiceLinkAuth:
    def test_other_users_service_returns_403(
        self, db, sample_member, monkeypatch
    ):
        other = _make_other_user(db)
        _make_service(
            db, member_id=other.member_id, surro_uuid="surro-svc-other"
        )

        called = {"hit": False}

        async def fake_create(*args, **kwargs):
            called["hit"] = True
            return _external_response("wf")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.create_workflow", fake_create
        )

        payload = {"name": "wf", "service_id": "surro-svc-other"}
        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/", json=payload)

        assert response.status_code == 403, response.text
        # 외부 호출까지 가지 않아야 함
        assert called["hit"] is False

    def test_own_service_succeeds(self, db, sample_member, monkeypatch):
        _make_service(
            db, member_id=sample_member.member_id, surro_uuid="surro-svc-own"
        )

        async def fake_create(*args, **kwargs):
            return _external_response("wf", service_id="surro-svc-own")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.create_workflow", fake_create
        )

        payload = {"name": "wf", "service_id": "surro-svc-own"}
        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/", json=payload)

        assert response.status_code == 201, response.text
        assert response.json()["service_id"] == "surro-svc-own"

    def test_admin_can_link_any_service(
        self, db, sample_member, admin_member, monkeypatch
    ):
        # sample_member 소유 서비스를 admin이 link
        _make_service(
            db, member_id=sample_member.member_id, surro_uuid="surro-svc-foreign"
        )

        async def fake_create(*args, **kwargs):
            return _external_response("wf", service_id="surro-svc-foreign")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.create_workflow", fake_create
        )

        payload = {"name": "wf", "service_id": "surro-svc-foreign"}
        with _client_with_overrides(db, admin_member) as client:
            response = client.post("/api/v1/workflows/", json=payload)

        assert response.status_code == 201, response.text

    def test_unknown_service_uuid_returns_404(self, db, sample_member, monkeypatch):
        called = {"hit": False}

        async def fake_create(*args, **kwargs):
            called["hit"] = True
            return _external_response("wf")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.create_workflow", fake_create
        )

        payload = {"name": "wf", "service_id": "surro-svc-nonexistent"}
        with _client_with_overrides(db, sample_member) as client:
            response = client.post("/api/v1/workflows/", json=payload)

        assert response.status_code == 404, response.text
        assert called["hit"] is False


# ===== PUT /workflows/{id} (update_workflow) =====

class TestUpdateWorkflowServiceLinkAuth:
    def _seed_workflow(self, db, member_id: str, surro_id: str = "surro-wf-1"):
        return workflow_crud.create_workflow(
            db,
            name="wf-existing",
            description=None,
            created_by=member_id,
            surro_workflow_id=surro_id,
        )

    def test_other_users_service_returns_403(
        self, db, sample_member, monkeypatch
    ):
        self._seed_workflow(db, sample_member.member_id)
        other = _make_other_user(db)
        _make_service(
            db, member_id=other.member_id, surro_uuid="surro-svc-other"
        )

        called = {"hit": False}

        async def fake_update(*args, **kwargs):
            called["hit"] = True
            return _external_response("wf-updated")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.update_workflow", fake_update
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.put(
                "/api/v1/workflows/surro-wf-1",
                json={"service_id": "surro-svc-other"},
            )

        assert response.status_code == 403, response.text
        assert called["hit"] is False

    def test_own_service_succeeds(self, db, sample_member, monkeypatch):
        self._seed_workflow(db, sample_member.member_id)
        _make_service(
            db, member_id=sample_member.member_id, surro_uuid="surro-svc-own"
        )

        async def fake_update(*args, **kwargs):
            return _external_response("wf-updated", service_id="surro-svc-own")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.update_workflow", fake_update
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.put(
                "/api/v1/workflows/surro-wf-1",
                json={"service_id": "surro-svc-own"},
            )

        assert response.status_code == 200, response.text
        assert response.json()["service_id"] == "surro-svc-own"

    def test_admin_can_link_any_service(
        self, db, sample_member, admin_member, monkeypatch
    ):
        # admin이 자기 소유 워크플로우에 sample_member의 service link
        self._seed_workflow(db, admin_member.member_id, surro_id="surro-wf-admin")
        _make_service(
            db, member_id=sample_member.member_id, surro_uuid="surro-svc-foreign"
        )

        async def fake_update(*args, **kwargs):
            return _external_response("wf-updated", service_id="surro-svc-foreign")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.update_workflow", fake_update
        )

        with _client_with_overrides(db, admin_member) as client:
            response = client.put(
                "/api/v1/workflows/surro-wf-admin",
                json={"service_id": "surro-svc-foreign"},
            )

        assert response.status_code == 200, response.text

    def test_unknown_service_uuid_returns_404(self, db, sample_member, monkeypatch):
        self._seed_workflow(db, sample_member.member_id)

        called = {"hit": False}

        async def fake_update(*args, **kwargs):
            called["hit"] = True
            return _external_response("wf-updated")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.update_workflow", fake_update
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.put(
                "/api/v1/workflows/surro-wf-1",
                json={"service_id": "surro-svc-nonexistent"},
            )

        assert response.status_code == 404, response.text
        assert called["hit"] is False

    def test_explicit_null_service_id_forwards_unlink(
        self, db, sample_member, monkeypatch
    ):
        """클라이언트가 명시적 `service_id: null`을 보내면 MLOps에 None이 전달돼
        unlink 동작이 일어나야 한다."""
        from app.services.workflow_service import UNSET

        self._seed_workflow(db, sample_member.member_id)

        captured = {}

        async def fake_update(workflow_id, name=None, description=None,
                              category=None, status=None, service_id=UNSET,
                              workflow_definition=None, user_info=None):
            captured["service_id"] = service_id
            return _external_response("wf-updated", service_id=None)

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.update_workflow", fake_update
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.put(
                "/api/v1/workflows/surro-wf-1",
                json={"service_id": None},  # 명시적 null
            )

        assert response.status_code == 200, response.text
        # 핵심: 명시적 None이 service layer까지 전달돼야 함 (UNSET 아님)
        assert captured["service_id"] is None

    def test_omitted_service_id_does_not_forward(
        self, db, sample_member, monkeypatch
    ):
        """클라이언트가 service_id 키 자체를 안 보내면 service layer에 _UNSET이
        전달되어 외부 API에 service_id 키가 안 들어가야 한다."""
        from app.services.workflow_service import UNSET

        self._seed_workflow(db, sample_member.member_id)

        captured = {}

        async def fake_update(workflow_id, name=None, description=None,
                              category=None, status=None, service_id=UNSET,
                              workflow_definition=None, user_info=None):
            captured["service_id"] = service_id
            return _external_response("wf-updated")

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.update_workflow", fake_update
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.put(
                "/api/v1/workflows/surro-wf-1",
                json={"name": "rename-only"},  # service_id 키 자체 없음
            )

        assert response.status_code == 200, response.text
        # 핵심: UNSET이 그대로 전달되어 외부 API에 service_id 키가 들어가지 않음
        assert captured["service_id"] is UNSET


# ===== POST /templates/{id}/clone =====

class TestCloneTemplateServiceLinkAuth:
    def test_other_users_service_returns_403(
        self, db, sample_member, monkeypatch
    ):
        other = _make_other_user(db)
        other_svc = _make_service(
            db, member_id=other.member_id, surro_uuid="surro-svc-other"
        )

        called = {"hit": False}

        async def fake_clone(*args, **kwargs):
            called["hit"] = True
            return {"id": "surro-cloned", "name": "cloned"}

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.clone_template", fake_clone
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post(
                "/api/v1/workflows/templates/tpl-1/clone",
                params={"workflow_name": "cloned", "service_id": other_svc.id},
            )

        assert response.status_code == 403, response.text
        assert called["hit"] is False

    def test_own_service_succeeds(self, db, sample_member, monkeypatch):
        own_svc = _make_service(
            db, member_id=sample_member.member_id, surro_uuid="surro-svc-own"
        )

        captured = {}

        async def fake_clone(template_id, workflow_name, surro_service_id=None, user_info=None):
            captured["surro_service_id"] = surro_service_id
            return {
                "id": "surro-cloned",
                "name": workflow_name,
                "description": None,
            }

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.clone_template", fake_clone
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post(
                "/api/v1/workflows/templates/tpl-1/clone",
                params={"workflow_name": "cloned", "service_id": own_svc.id},
            )

        assert response.status_code == 200, response.text
        # PK가 UUID로 매핑되어 외부에 전달됨
        assert captured["surro_service_id"] == "surro-svc-own"

    def test_admin_can_link_any_service(
        self, db, sample_member, admin_member, monkeypatch
    ):
        foreign_svc = _make_service(
            db, member_id=sample_member.member_id, surro_uuid="surro-svc-foreign"
        )

        captured = {}

        async def fake_clone(template_id, workflow_name, surro_service_id=None, user_info=None):
            captured["surro_service_id"] = surro_service_id
            return {"id": "surro-cloned", "name": workflow_name, "description": None}

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.clone_template", fake_clone
        )

        with _client_with_overrides(db, admin_member) as client:
            response = client.post(
                "/api/v1/workflows/templates/tpl-1/clone",
                params={"workflow_name": "cloned", "service_id": foreign_svc.id},
            )

        assert response.status_code == 200, response.text
        assert captured["surro_service_id"] == "surro-svc-foreign"

    def test_unknown_service_pk_returns_404(self, db, sample_member, monkeypatch):
        called = {"hit": False}

        async def fake_clone(*args, **kwargs):
            called["hit"] = True
            return {"id": "surro-cloned", "name": "cloned"}

        monkeypatch.setattr(
            "app.routes.workflow.workflow_service.clone_template", fake_clone
        )

        with _client_with_overrides(db, sample_member) as client:
            response = client.post(
                "/api/v1/workflows/templates/tpl-1/clone",
                params={"workflow_name": "cloned", "service_id": 999999},
            )

        assert response.status_code == 404, response.text
        assert called["hit"] is False
