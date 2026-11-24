"""프롬프트 생성과 조회 경로의 자동 등록이 겹쳐도 만든 사람이 작성자로 남는다.

생성 라우트는 MLOps 에 프롬프트를 만든 뒤 매핑을 저장한다. 그 사이 다른 요청의 조회가 같은 ID 를
admin 소유로 자동 등록하면, 생성 경로는 그 행을 그대로 돌려줘 작성자가 admin 으로 남았다(사이에
끼어들면 500). 요청 뒤에 생긴 자동 등록 행(registered_via='auto')은 생성자가 넘겨받고, 그 밖의
기존 행은 MLOps 재설치로 재사용된 ID 의 옛 매핑으로 보고 이력으로 남긴 뒤 새 행을 만든다.
"""
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.cruds.prompt import prompt_crud
from app.database import get_db
from app.main import app
from app.models import Member
from app.models.audit_log import AuditLog
from app.models.base import REGISTERED_VIA_AUTO
from app.models.prompt import Prompt
from app.schemas.prompt import ExternalPromptResponse
from tests.conftest import _engine, committed_session, make_member

USER_ID = "pr-claim-user"
OTHER_ID = "pr-claim-other"
ADMIN_ID = "pr-claim-admin"
MEMBERS = [USER_ID, OTHER_ID, ADMIN_ID]
SURRO_ID = 9101
NAME = "요약"
REUSED_ON_CREATE = "system:upstream-id-reused:create"

# 스레드 조율용 대기 상한. 넘었다는 것은 조율이 깨졌다는 뜻이다.
SYNC_TIMEOUT = 15.0


def _purge(session):
    session.query(AuditLog).filter(
        AuditLog.actor_member_id.in_(MEMBERS)
    ).delete(synchronize_session=False)
    session.query(Prompt).filter(
        Prompt.surro_prompt_id == SURRO_ID
    ).delete(synchronize_session=False)
    session.query(Member).filter(
        Member.member_id.in_(MEMBERS)
    ).delete(synchronize_session=False)


@pytest.fixture
def real_db():
    """커밋된 회원. 라우트의 rollback 이 준비 데이터를 되돌리지 않아야 한다."""
    with committed_session(_purge) as session:
        user = make_member(USER_ID)
        other = make_member(OTHER_ID)
        admin = make_member(ADMIN_ID, role="admin")
        session.add_all([user, other, admin])
        session.commit()
        yield session, user


@contextmanager
def _client(db, current_user):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _external():
    return ExternalPromptResponse(
        id=SURRO_ID, name=NAME, description=None, content="content", prompt_variable=None,
    )


def _add_mapping(db, owner, registered_via=None, created_at=None):
    row = Prompt(
        name=NAME, content="old", created_by=owner, surro_prompt_id=SURRO_ID,
        is_active=True, registered_via=registered_via,
    )
    if created_at is not None:
        row.created_at = created_at
    db.add(row)
    db.commit()


def _fake_create(monkeypatch, before_return=None):
    async def fake_create_prompt(**kwargs):
        if before_return:
            before_return()
        return _external()

    monkeypatch.setattr("app.routes.prompt.prompt_service.create_prompt", fake_create_prompt)


def _fake_list(monkeypatch):
    async def fake_get_prompts(page=None, page_size=None, user_info=None):
        return [_external()]

    monkeypatch.setattr("app.routes.prompt.prompt_service.get_prompts", fake_get_prompts)


def _post(client):
    return client.post(
        "/api/v1/prompts/",
        json={"prompt": {"name": NAME, "content": "content"}},
    )


def _mappings():
    """라우트 세션과 무관하게 커밋된 매핑 전체를 id 순으로 읽는다."""
    check = Session(bind=_engine)
    try:
        return check.query(Prompt).filter(
            Prompt.surro_prompt_id == SURRO_ID
        ).order_by(Prompt.id).all()
    finally:
        check.close()


def _active(rows):
    return [r for r in rows if r.deleted_at is None]


def test_list_auto_registration_is_marked(real_db, monkeypatch):
    db, user = real_db
    _fake_list(monkeypatch)

    with _client(db, user) as client:
        assert client.get("/api/v1/prompts").status_code == 200

    [mapping] = _mappings()
    assert mapping.created_by == ADMIN_ID
    assert mapping.registered_via == REGISTERED_VIA_AUTO


@pytest.mark.parametrize("owner", [ADMIN_ID, OTHER_ID], ids=["admin", "fallback-member"])
def test_create_reclaims_mapping_auto_registered_during_request(real_db, monkeypatch, owner):
    """MLOps 생성 뒤 다른 조회가 먼저 자동 등록한 행을 넘겨받는다.

    admin 이 없으면 자동 등록 소유자는 조회한 일반 사용자다. 소유자가 아니라 표시로 판단한다.
    """
    db, user = real_db
    _fake_create(monkeypatch, before_return=lambda: _add_mapping(db, owner, REGISTERED_VIA_AUTO))

    with _client(db, user) as client:
        response = _post(client)

    assert response.status_code == 200
    assert response.json()["created_by"] == USER_ID
    [mapping] = _mappings()
    assert mapping.created_by == USER_ID
    assert mapping.registered_via is None
    assert mapping.content == "content"
    audit = db.query(AuditLog).filter(
        AuditLog.actor_member_id == USER_ID, AuditLog.resource_id == str(SURRO_ID),
    ).one()
    assert audit.metadata_json["ownership_reclaimed"] is True


def test_create_reclaims_mapping_inserted_between_lookup_and_insert(real_db, monkeypatch):
    """옛 매핑 정리와 INSERT 사이에 자동 등록이 끼어들어도 다시 시도해 넘겨받는다 (예전에는 500)."""
    db, user = real_db
    _fake_create(monkeypatch)
    real_retire = prompt_crud._retire_active_mapping
    seen = {"first": True}

    def racing_retire(db, surro_prompt_id):
        real_retire(db, surro_prompt_id)
        if seen["first"]:
            seen["first"] = False
            # 다른 요청의 조회가 같은 ID 를 자동 등록하고 먼저 커밋한 상황
            _add_mapping(db, ADMIN_ID, REGISTERED_VIA_AUTO)

    monkeypatch.setattr(prompt_crud, "_retire_active_mapping", racing_retire)

    with _client(db, user) as client:
        response = _post(client)

    assert response.status_code == 200
    assert response.json()["created_by"] == USER_ID
    [mapping] = _active(_mappings())
    assert mapping.created_by == USER_ID


@pytest.mark.parametrize(
    "registered_via", [None, REGISTERED_VIA_AUTO], ids=["member-row", "old-auto-row"],
)
def test_create_retires_mapping_of_reused_id(real_db, monkeypatch, registered_via):
    """요청 전부터 있던 같은 ID 매핑은 재사용된 ID 의 옛 매핑이다. 덮어쓰지 않고 이력으로 남긴다.

    자동 등록 행이어도 요청 전에 생겼다면 이 요청과 겹친 것이 아니므로 넘겨받지 않는다.
    """
    db, user = real_db
    _add_mapping(
        db, OTHER_ID, registered_via, created_at=datetime.utcnow() - timedelta(days=30),
    )
    _fake_create(monkeypatch)

    with _client(db, user) as client:
        response = _post(client)

    assert response.status_code == 200
    old, new = _mappings()
    assert old.created_by == OTHER_ID
    assert old.content == "old"
    assert old.deleted_at is not None
    assert old.deleted_by == REUSED_ON_CREATE
    assert new.created_by == USER_ID
    assert new.deleted_at is None
    assert new.registered_via is None


@pytest.mark.postgres
@pytest.mark.skipif(
    _engine.dialect.name != "postgresql",
    reason="실제 트랜잭션 경합은 PostgreSQL 에서만 재현한다 — TEST_DATABASE_URL 필요",
)
def test_list_during_create_does_not_take_authorship(real_db, monkeypatch):
    """MLOps 생성과 매핑 저장 사이에 다른 요청의 목록 조회가 끝까지 실행돼도 생성자가 작성자다."""
    _, user = real_db
    caller = SimpleNamespace(member_id=user.member_id, role="user", name=user.name)
    list_status = {}

    def list_in_other_request():
        # 생성 요청과 별개의 요청·세션으로 목록을 조회해 자동 등록을 끝까지 커밋시킨다
        def run():
            with TestClient(app) as client:
                list_status["code"] = client.get("/api/v1/prompts").status_code

        worker = threading.Thread(target=run)
        worker.start()
        worker.join(timeout=SYNC_TIMEOUT)
        assert not worker.is_alive(), "목록 요청이 끝나지 않았다"

    _fake_list(monkeypatch)
    _fake_create(monkeypatch, before_return=list_in_other_request)

    def per_request_db():
        session = Session(bind=_engine)  # 요청마다 독립 세션 = 독립 트랜잭션
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = per_request_db
    app.dependency_overrides[get_current_user] = lambda: caller
    try:
        with TestClient(app) as client:
            response = _post(client)
    finally:
        app.dependency_overrides.clear()

    assert list_status == {"code": 200}
    assert response.status_code == 200
    [mapping] = _mappings()
    assert mapping.created_by == USER_ID
    assert mapping.registered_via is None
