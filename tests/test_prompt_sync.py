from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.models import Member
from app.database import get_db
from app.main import app
from app.cruds.prompt import prompt_crud
from app.models.prompt import Prompt
from app.schemas.prompt import ExternalPromptResponse, PromptVariableReadSchema
from tests.conftest import _engine


@pytest.fixture
def real_db():
    """엔진에 직접 바인딩한 세션 + commit 된 member 2명.

    전역 `db` fixture 는 외부 트랜잭션에 rollback_only 로 참여하므로, 라우트가
    호출하는 `session.rollback()` 이 테스트 준비 데이터까지 되돌려 버린다.
    rollback 경로를 검증하려면 실제 commit/rollback 이 동작하는 세션이 필요하다.
    커넥션을 직접 고정해야 TestClient 스레드에서도 같은 in-memory DB 를 본다.
    """
    connection = _engine.connect()
    session = Session(bind=connection)
    members = [
        Member(
            name="rollback tester", member_id="rb-user", email="rb-user@example.com",
            password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
            role="user", is_active=True,
        ),
        Member(
            name="rollback admin", member_id="rb-admin", email="rb-admin@example.com",
            password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
            role="admin", is_active=True,
        ),
    ]
    session.add_all(members)
    session.commit()
    try:
        yield session, members[0], members[1]
    finally:
        session.rollback()
        session.query(Prompt).delete()
        for member in members:
            session.query(Member).filter(Member.member_id == member.member_id).delete()
        session.commit()
        session.close()
        connection.close()


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

    def test_list_survives_unsyncable_external_prompt(self, real_db, monkeypatch):
        """한 건의 sync 실패가 세션을 오염시켜 목록 전체를 500으로 만들지 않는다.

        MLOps content 가 DB 컬럼 폭을 넘어 insert 가 실패했을 때, 라우트가
        rollback 하지 않으면 이후 항목과 본 조회까지 전부 500 이 된다.
        """
        db, sample_member, admin_member = real_db

        async def fake_get_prompts(page=None, page_size=None, user_info=None):
            return [
                _external_prompt(41, "ok-41", "content-41", "desc-41"),
                _external_prompt(42, "bad-42", "content-42", "desc-42"),
                _external_prompt(43, "ok-43", "content-43", "desc-43"),
            ]

        real_create = prompt_crud.create_mapping_from_external

        def flaky_create(db, surro_prompt_id, member_id, name, description, content, prompt_variable=None,
                         **kwargs):
            if surro_prompt_id == 42:
                # 실제 장애(varchar 초과)와 동일하게 flush 실패로 세션을 오염시킨다.
                db.add(Prompt(
                    name=name,
                    content=None,
                    created_by=member_id,
                    surro_prompt_id=surro_prompt_id,
                ))
                db.flush()
            return real_create(
                db=db,
                surro_prompt_id=surro_prompt_id,
                member_id=member_id,
                name=name,
                description=description,
                content=content,
                prompt_variable=prompt_variable,
                **kwargs,
            )

        monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompts", fake_get_prompts)
        monkeypatch.setattr(prompt_crud, "create_mapping_from_external", flaky_create)

        with _client_with_overrides(db, sample_member) as client:
            response = client.get("/api/v1/prompts")

        assert response.status_code == 200
        body = response.json()
        assert {item["surro_prompt_id"] for item in body["data"]} == {41, 43}
        assert body["total"] == 2
        assert prompt_crud.get_prompt_by_surro_id(db, 42, include_deleted=True) is None
        assert prompt_crud.get_prompt_by_surro_id(db, 43).created_by == admin_member.member_id

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

    def test_admin_list_keeps_mappings_when_external_list_is_empty(
        self, db, sample_member, admin_member, monkeypatch
    ):
        """업스트림이 일시적으로 빈 목록을 줘도 기존 매핑을 지우지 않는다."""
        prompt_crud.create_mapping_from_external(
            db=db,
            surro_prompt_id=7,
            member_id=sample_member.member_id,
            name="owned-by-user",
            description="d",
            content="c",
        )

        async def fake_get_prompts(page=None, page_size=None, user_info=None):
            return []

        monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompts", fake_get_prompts)

        with _client_with_overrides(db, admin_member) as client:
            response = client.get("/api/v1/prompts")

        assert response.status_code == 200
        kept = prompt_crud.get_prompt_by_surro_id(db, 7, include_deleted=True)
        assert kept.is_active is True
        assert kept.deleted_at is None
        assert kept.created_by == sample_member.member_id

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


def test_soft_delete_missing_mappings_keeps_all_on_empty_list(db, sample_member):
    """빈 외부 목록이면 아무것도 지우지 않는다 — 호출자 가드와 무관하게 CRUD 에서 막는다"""
    prompt_crud.create_mapping_from_external(
        db=db,
        surro_prompt_id=301,
        member_id=sample_member.member_id,
        name="kept-prompt",
        description=None,
        content="content",
    )

    n = prompt_crud.soft_delete_missing_mappings(db=db, active_surro_prompt_ids=[])

    assert n == 0
    kept = prompt_crud.get_prompt_by_surro_id(db, 301)
    assert kept is not None
    assert kept.created_by == sample_member.member_id


# ============================================================
# 조회마다 쓰기 없음 / 스냅샷 이후 변경 보호 / 동시 매핑 생성
# ============================================================

def _mapping(db, prompt_id, owner, name, content="content", variables=None):
    return prompt_crud.create_mapping_from_external(
        db=db, surro_prompt_id=prompt_id, member_id=owner, name=name,
        description=None, content=content, prompt_variable=variables,
    )


def test_sync_does_not_touch_unchanged_mapping(db, sample_member):
    """값이 같으면 updated_at 을 바꾸지 않는다 (변수 포함)."""
    variables = [PromptVariableReadSchema(id=1, name="v", prompt_id=401)]
    mapping = _mapping(db, 401, sample_member.member_id, "same", variables=variables)
    before = mapping.updated_at

    _mapping(db, 401, sample_member.member_id, "same", variables=variables)

    db.refresh(mapping)
    assert mapping.updated_at == before


def test_admin_cleanup_keeps_prompt_created_after_list_fetch(real_db, monkeypatch):
    """목록을 받은 뒤 만들어진 프롬프트는 목록에 없어도 지우지 않는다."""
    db, user, admin = real_db
    _mapping(db, 501, admin.member_id, "listed")

    async def fake_get_prompts(page=None, page_size=None, user_info=None):
        listed = [_external_prompt(501, "listed", "content")]
        # 목록 스냅샷 이후 다른 사용자가 프롬프트를 만들어 매핑까지 커밋했다
        _mapping(db, 502, user.member_id, "created-meanwhile")
        return listed

    monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompts", fake_get_prompts)

    with _client_with_overrides(db, admin) as client:
        response = client.get("/api/v1/prompts")

    assert response.status_code == 200
    kept = prompt_crud.get_prompt_by_surro_id(db, 502)
    assert kept is not None
    assert kept.created_by == user.member_id


def test_rename_during_list_fetch_keeps_owner(real_db, monkeypatch):
    """목록 조회와 이름 변경이 겹쳐도 재사용으로 판단하지 않고, 다음 조회에서도 소유자를 유지한다."""
    db, user, admin = real_db
    _mapping(db, 601, user.member_id, "before")
    responses = iter([
        "rename-during-fetch",   # 첫 조회: 스냅샷은 옛 이름, 그 사이 PUT 으로 이름 변경
        "fresh",                 # 다음 조회: 새 이름
    ])

    async def fake_get_prompts(page=None, page_size=None, user_info=None):
        if next(responses) == "rename-during-fetch":
            prompt_crud.backfill_cache_if_changed(db=db, surro_prompt_id=601, name="after")
            return [_external_prompt(601, "before", "content")]
        return [_external_prompt(601, "after", "content")]

    monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompts", fake_get_prompts)

    with _client_with_overrides(db, admin) as client:
        assert client.get("/api/v1/prompts").status_code == 200
        assert client.get("/api/v1/prompts").status_code == 200

    current = prompt_crud.get_prompt_by_surro_id(db, 601)
    assert current.created_by == user.member_id
    assert current.name == "after"
    reused = db.query(Prompt).filter(
        Prompt.surro_prompt_id == 601, Prompt.deleted_by == "system:upstream-id-reused"
    ).all()
    assert reused == []


def test_detail_mapping_returns_row_created_by_concurrent_request(real_db, monkeypatch):
    """조회와 INSERT 사이에 다른 요청이 같은 매핑을 만들면 500 대신 그 행을 쓴다."""
    db, user, admin = real_db
    real_get = prompt_crud.get_prompt_by_surro_id
    seen = {"first": True}

    def racing_get(db, surro_prompt_id, include_deleted=False):
        if seen["first"] and surro_prompt_id == 701 and not include_deleted:
            seen["first"] = False
            # "매핑 없음"을 읽은 직후 다른 요청이 먼저 커밋했다
            db.add(Prompt(
                name="p", content="c", created_by=admin.member_id,
                surro_prompt_id=701, is_active=True,
            ))
            db.commit()
            return None
        return real_get(db, surro_prompt_id, include_deleted=include_deleted)

    monkeypatch.setattr(prompt_crud, "get_prompt_by_surro_id", racing_get)

    async def fake_get_prompt(surro_prompt_id, user_info=None):
        return _external_prompt(701, "p", "c")

    monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompt", fake_get_prompt)

    with _client_with_overrides(db, user) as client:
        response = client.get("/api/v1/prompts/701")

    assert response.status_code == 200
    assert response.json()["created_by"] == admin.member_id
    active = db.query(Prompt).filter(
        Prompt.surro_prompt_id == 701, Prompt.deleted_at.is_(None)
    ).all()
    assert len(active) == 1


@pytest.mark.postgres
@pytest.mark.skipif(
    _engine.dialect.name != "postgresql",
    reason="실제 트랜잭션 경합은 PostgreSQL 에서만 재현한다 — TEST_DATABASE_URL 필요",
)
def test_concurrent_detail_requests_create_one_mapping(real_db, monkeypatch):
    """두 상세 조회가 같은 미매핑 프롬프트를 동시에 등록해도 둘 다 200 이고 매핑은 하나다."""
    import threading

    from tests.test_knowledge_base_lock_concurrency import SYNC_TIMEOUT, _run

    db, user, admin = real_db

    async def fake_get_prompt(surro_prompt_id, user_info=None):
        return _external_prompt(801, "p", "c")

    monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompt", fake_get_prompt)

    # 두 요청이 모두 "매핑 없음"을 읽은 뒤 INSERT 로 넘어가게 맞춘다
    barrier = threading.Barrier(2, timeout=SYNC_TIMEOUT)
    real_get = prompt_crud.get_prompt_by_surro_id

    def synced_get(db, surro_prompt_id, include_deleted=False):
        result = real_get(db, surro_prompt_id, include_deleted=include_deleted)
        if result is None and surro_prompt_id == 801 and not include_deleted:
            barrier.wait()
        return result

    monkeypatch.setattr(prompt_crud, "get_prompt_by_surro_id", synced_get)

    def per_request_db():
        session = Session(bind=_engine)
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = per_request_db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        member_id=user.member_id, role="user", name=user.name,
    )
    results = {}

    def call(name):
        with TestClient(app, raise_server_exceptions=False) as client:
            results[name] = client.get("/api/v1/prompts/801").status_code

    try:
        _run(lambda: call("A"), lambda: call("B"))
    finally:
        app.dependency_overrides.clear()

    assert not barrier.broken, "두 요청이 동시에 INSERT 에 들어가지 못했다 — 경합이 재현되지 않았다"
    assert results == {"A": 200, "B": 200}
    check = Session(bind=_engine)
    try:
        active = check.query(Prompt).filter(
            Prompt.surro_prompt_id == 801, Prompt.deleted_at.is_(None)
        ).all()
    finally:
        check.close()
    assert len(active) == 1


@pytest.mark.parametrize("route", ["detail", "update", "delete"])
def test_rename_during_single_fetch_keeps_owner(real_db, monkeypatch, route):
    """상세·수정·삭제가 단건 조회 중 다른 요청의 이름 변경과 겹쳐도 재사용으로 판단하지 않는다."""
    db, user, admin = real_db
    _mapping(db, 901, user.member_id, "before")

    async def fake_get_prompt(surro_prompt_id, user_info=None):
        # 단건 스냅샷은 옛 이름, 그 사이 다른 요청이 PUT 으로 이름을 바꿨다
        prompt_crud.backfill_cache_if_changed(db=db, surro_prompt_id=901, name="after")
        return _external_prompt(901, "before", "content")

    async def fake_update_prompt(prompt_id, name=None, description=None, content=None,
                                 prompt_variable=None, user_info=None):
        return _external_prompt(901, "after", content or "content")

    async def fake_delete_prompt(prompt_id, user_info=None):
        return True

    monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompt", fake_get_prompt)
    monkeypatch.setattr("app.routes.prompt.prompt_service.update_prompt", fake_update_prompt)
    monkeypatch.setattr("app.routes.prompt.prompt_service.delete_prompt", fake_delete_prompt)

    with _client_with_overrides(db, user) as client:
        if route == "detail":
            response = client.get("/api/v1/prompts/901")
        elif route == "update":
            response = client.put("/api/v1/prompts/901", json={"content": "edited"})
        else:
            response = client.delete("/api/v1/prompts/901")

    assert response.status_code in (200, 204)
    rows = db.query(Prompt).filter(Prompt.surro_prompt_id == 901).all()
    assert [r.deleted_by for r in rows if r.deleted_by == "system:upstream-id-reused"] == []
    assert {r.created_by for r in rows} == {user.member_id}
