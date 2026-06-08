from contextlib import contextmanager
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.models import Member
from app.database import get_db
from app.main import app
from app.cruds.prompt import prompt_crud
from app.schemas.prompt import ExternalPromptResponse, PromptVariableReadSchema


def _external_prompt(prompt_id: int, name: str, content: str, description: str | None = None, variables=None):
    return ExternalPromptResponse(
        id=prompt_id,
        name=name,
        description=description,
        content=content,
        prompt_variable=variables,
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


class TestPromptSyncRoutes:
    def test_list_syncs_shared_prompts_to_admin_mapping(self, db, sample_member, admin_member, monkeypatch):
        async def fake_get_prompts(page=None, page_size=None, user_info=None):
            assert user_info is not None
            return [
                _external_prompt(1, "shared-1", "content-1", "desc-1"),
                _external_prompt(2, "shared-2", "content-2", "desc-2"),
            ]

        monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompts", fake_get_prompts)

        with _client_with_overrides(db, sample_member) as client:
            response = client.get("/api/v1/prompts")

        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 2
        assert {item["surro_prompt_id"] for item in body["data"]} == {1, 2}

        prompt_1 = prompt_crud.get_prompt_by_surro_id(db, 1)
        prompt_2 = prompt_crud.get_prompt_by_surro_id(db, 2)
        assert prompt_1 is not None and prompt_1.created_by == admin_member.member_id
        assert prompt_2 is not None and prompt_2.created_by == admin_member.member_id

    def test_list_sync_uses_active_admin_member_dynamically(self, db, sample_member, admin_member, monkeypatch):
        admin_member.is_active = False
        custom_admin = Member(
            name="ops admin",
            member_id="opsadmin",
            email="opsadmin@example.com",
            password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
            role="admin",
            is_active=True,
        )
        db.add(custom_admin)
        db.commit()

        async def fake_get_prompts(page=None, page_size=None, user_info=None):
            return [_external_prompt(11, "shared-11", "content-11", "desc-11")]

        monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompts", fake_get_prompts)

        with _client_with_overrides(db, sample_member) as client:
            response = client.get("/api/v1/prompts")

        assert response.status_code == 200
        mapping = prompt_crud.get_prompt_by_surro_id(db, 11)
        assert mapping is not None
        assert mapping.created_by == custom_admin.member_id

    def test_list_soft_deletes_stale_prompt_mappings_on_admin_sync(self, db, sample_member, admin_member, monkeypatch):
        prompt_crud.create_mapping_from_external(
            db=db,
            surro_prompt_id=99,
            member_id=admin_member.member_id,
            name="stale",
            description="stale",
            content="stale",
        )

        async def fake_get_prompts(page=None, page_size=None, user_info=None):
            return [_external_prompt(1, "shared-1", "content-1", "desc-1")]

        monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompts", fake_get_prompts)

        with _client_with_overrides(db, admin_member) as client:
            response = client.get("/api/v1/prompts")

        assert response.status_code == 200
        stale = prompt_crud.get_prompt_by_surro_id(db, 99, include_deleted=True)
        assert stale is not None
        assert stale.is_active is False
        assert stale.deleted_at is not None
        assert stale.deleted_by == admin_member.member_id

    def test_list_non_admin_does_not_soft_delete_hidden_prompt(self, db, sample_member, admin_member, monkeypatch):
        prompt_crud.create_mapping_from_external(
            db=db,
            surro_prompt_id=1,
            member_id=admin_member.member_id,
            name="shared-1",
            description="desc-1",
            content="content-1",
        )
        prompt_crud.create_mapping_from_external(
            db=db,
            surro_prompt_id=2,
            member_id=admin_member.member_id,
            name="shared-2",
            description="desc-2",
            content="content-2",
        )

        async def fake_get_prompts(page=None, page_size=None, user_info=None):
            return [_external_prompt(1, "shared-1", "content-1", "desc-1")]

        monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompts", fake_get_prompts)

        with _client_with_overrides(db, sample_member) as client:
            response = client.get("/api/v1/prompts")

        assert response.status_code == 200
        still_active = prompt_crud.get_prompt_by_surro_id(db, 2, include_deleted=True)
        assert still_active is not None
        assert still_active.is_active is True
        assert still_active.deleted_at is None

    def test_detail_backfills_missing_mapping_as_admin(self, db, sample_member, admin_member, monkeypatch):
        external = _external_prompt(
            10,
            "detail-shared",
            "detail-content",
            "detail-desc",
            [PromptVariableReadSchema(id=1, name="context", prompt_id=10)],
        )

        async def fake_get_prompt(prompt_id, user_info=None):
            assert user_info is not None
            return external if prompt_id == 10 else None

        monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompt", fake_get_prompt)

        with _client_with_overrides(db, sample_member) as client:
            response = client.get("/api/v1/prompts/10")

        assert response.status_code == 200
        body = response.json()
        assert body["surro_prompt_id"] == 10
        assert body["created_by"] == admin_member.member_id
        assert body["prompt_variable"][0]["name"] == "context"

        mapping = prompt_crud.get_prompt_by_surro_id(db, 10)
        assert mapping is not None
        assert mapping.created_by == admin_member.member_id

    def test_update_allows_shared_prompt_with_admin_mapping(self, db, sample_member, admin_member, monkeypatch):
        prompt_crud.create_mapping_from_external(
            db=db,
            surro_prompt_id=20,
            member_id=admin_member.member_id,
            name="before",
            description="before-desc",
            content="before-content",
        )

        current_external = _external_prompt(20, "before", "before-content", "before-desc")
        updated_external = _external_prompt(20, "after", "after-content", "after-desc")

        async def fake_get_prompt(prompt_id, user_info=None):
            return current_external if prompt_id == 20 else None

        async def fake_update_prompt(prompt_id, name=None, description=None, content=None, prompt_variable=None, user_info=None):
            assert prompt_id == 20
            assert name == "after"
            assert description == "after-desc"
            assert content == "after-content"
            return updated_external

        monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompt", fake_get_prompt)
        monkeypatch.setattr("app.routes.prompt.prompt_service.update_prompt", fake_update_prompt)

        with _client_with_overrides(db, sample_member) as client:
            response = client.put(
                "/api/v1/prompts/20",
                json={"name": "after", "description": "after-desc", "content": "after-content"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["name"] == "after"

        updated = prompt_crud.get_prompt_by_surro_id(db, 20)
        assert updated is not None
        assert updated.name == "after"
        assert updated.content == "after-content"

    def test_delete_soft_deletes_local_mapping(self, db, sample_member, admin_member, monkeypatch):
        prompt_crud.create_mapping_from_external(
            db=db,
            surro_prompt_id=30,
            member_id=admin_member.member_id,
            name="delete-me",
            description="delete-me",
            content="delete-me",
        )

        async def fake_get_prompt(prompt_id, user_info=None):
            return _external_prompt(30, "delete-me", "delete-me", "delete-me") if prompt_id == 30 else None

        async def fake_delete_prompt(prompt_id, user_info=None):
            return prompt_id == 30

        monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompt", fake_get_prompt)
        monkeypatch.setattr("app.routes.prompt.prompt_service.delete_prompt", fake_delete_prompt)

        with _client_with_overrides(db, sample_member) as client:
            response = client.delete("/api/v1/prompts/30")

        assert response.status_code == 204
        deleted = prompt_crud.get_prompt_by_surro_id(db, 30, include_deleted=True)
        assert deleted is not None
        assert deleted.is_active is False
        assert deleted.deleted_at is not None
        assert deleted.deleted_by == sample_member.member_id
