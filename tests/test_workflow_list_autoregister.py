"""워크플로우 목록의 자동 등록이 실패해도 목록 API 가 500 이 되지 않는다."""
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.cruds.workflow import workflow_crud
from app.database import get_db
from app.main import app
from app.models import Member
from app.models.workflow import Workflow
from app.schemas.workflow import ExternalWorkflowBriefResponse
from tests.conftest import _engine
from tests.test_knowledge_base_lock_concurrency import _run

USER_ID = "wf-reg-user"
ADMIN_ID = "wf-reg-admin"

# 스레드 조율용 대기 상한. 넘었다는 것은 조율이 깨졌다는 뜻이다.
SYNC_TIMEOUT = 15.0


def _purge(session):
    session.query(Workflow).filter(
        Workflow.created_by.in_([USER_ID, ADMIN_ID])
    ).delete(synchronize_session=False)
    session.query(Member).filter(
        Member.member_id.in_([USER_ID, ADMIN_ID])
    ).delete(synchronize_session=False)
    session.commit()


@pytest.fixture
def real_db():
    """실제 commit/rollback 이 동작하는 세션 + 커밋된 사용자·관리자.

    공용 `db` fixture 는 외부 트랜잭션에 rollback_only 로 참여하므로, 라우트의
    `db.rollback()` 이 테스트 준비 데이터까지 되돌려 버린다.
    """
    connection = _engine.connect()
    session = Session(bind=connection)
    _purge(session)
    user = Member(
        name="wf reg user", member_id=USER_ID, email=f"{USER_ID}@example.com",
        password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
        role="user", is_active=True,
    )
    admin = Member(
        name="wf reg admin", member_id=ADMIN_ID, email=f"{ADMIN_ID}@example.com",
        password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
        role="admin", is_active=True,
    )
    session.add_all([user, admin])
    session.commit()
    try:
        yield session, user, admin
    finally:
        session.rollback()
        _purge(session)
        session.close()
        connection.close()


def _brief(surro_id: str) -> ExternalWorkflowBriefResponse:
    return ExternalWorkflowBriefResponse(
        id=surro_id, name=surro_id, status="DRAFT", creator_id=1, is_template=False,
    )


def _active_mappings(surro_id: str):
    """라우트 세션과 무관하게 커밋된 활성 매핑을 읽는다."""
    check = Session(bind=_engine)
    try:
        return check.query(Workflow).filter(
            Workflow.surro_workflow_id == surro_id,
            Workflow.deleted_at.is_(None),
        ).all()
    finally:
        check.close()


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


def test_list_survives_auto_register_conflict(real_db, monkeypatch):
    db, user, admin = real_db

    async def fake_get_workflows(**kwargs):
        return [_brief("wf-race"), _brief("wf-ok")]

    monkeypatch.setattr(
        "app.routes.workflow.workflow_service.get_workflows", fake_get_workflows
    )

    real_create = workflow_crud.create_workflow

    def racing_create(db, name, description, created_by, surro_workflow_id):
        if surro_workflow_id == "wf-race":
            # 다른 요청이 같은 워크플로우를 먼저 등록하고 커밋한 상황
            db.add(Workflow(name=name, created_by=USER_ID, surro_workflow_id=surro_workflow_id))
            db.commit()
        return real_create(
            db=db, name=name, description=description,
            created_by=created_by, surro_workflow_id=surro_workflow_id,
        )

    monkeypatch.setattr(workflow_crud, "create_workflow", racing_create)

    with _client(db, user) as client:
        response = client.get("/api/v1/workflows")

    assert response.status_code == 200
    # 소유자는 DB 에서 확인한다. 목록 응답은 호출자 범위에 따라 항목이 빠질 수 있다.
    # 먼저 커밋한 쪽의 소유가 유지되고, 충돌하지 않은 항목은 정상 등록된다
    assert [w.created_by for w in _active_mappings("wf-race")] == [USER_ID]
    assert [w.created_by for w in _active_mappings("wf-ok")] == [ADMIN_ID]


@pytest.mark.postgres
@pytest.mark.skipif(
    _engine.dialect.name != "postgresql",
    reason="실제 트랜잭션 경합은 PostgreSQL 에서만 재현한다 — TEST_DATABASE_URL 필요",
)
def test_concurrent_lists_register_missing_workflow_once(real_db, monkeypatch):
    """두 목록 요청이 같은 누락 워크플로우를 동시에 등록해도 둘 다 200 이고 매핑은 하나다.

    SQLite 와 달리 PostgreSQL 은 늦은 INSERT 를 먼저 들어온 트랜잭션이 끝날 때까지
    기다리게 한 뒤 실패시킨다. 독립 세션 둘을 스레드로 돌려야 이 경합이 생긴다.
    """
    async def fake_get_workflows(**kwargs):
        return [_brief("wf-concurrent")]

    monkeypatch.setattr(
        "app.routes.workflow.workflow_service.get_workflows", fake_get_workflows
    )

    # 두 요청을 INSERT 직전에 맞춰 세운다. 매핑 조회 직후에 세우면 INSERT 가 실제로
    # 겹치는지는 스케줄링에 달려 경합이 재현되지 않을 수 있다.
    barrier = threading.Barrier(2, timeout=SYNC_TIMEOUT)
    real_create = workflow_crud.create_workflow

    def synced_create(*args, **kwargs):
        barrier.wait()
        return real_create(*args, **kwargs)

    monkeypatch.setattr(workflow_crud, "create_workflow", synced_create)

    def per_request_db():
        session = Session(bind=_engine)  # 요청마다 독립 세션 = 독립 트랜잭션
        try:
            yield session
        finally:
            session.close()

    # 전역 override 는 스레드를 띄우기 전에 한 번만 건다. 스레드 안에서 바꾸면 서로 덮어쓴다.
    caller = SimpleNamespace(member_id=USER_ID, role="user", name="wf reg user")
    app.dependency_overrides[get_db] = per_request_db
    app.dependency_overrides[get_current_user] = lambda: caller

    results = {}

    def call(name):
        with TestClient(app, raise_server_exceptions=False) as client:
            results[name] = client.get("/api/v1/workflows").status_code

    try:
        _run(lambda: call("A"), lambda: call("B"))
    finally:
        app.dependency_overrides.clear()

    # 라우트가 등록 실패를 삼키므로 barrier 가 깨져도 응답은 200 일 수 있다. 따로 확인한다.
    assert not barrier.broken, "두 요청이 동시에 INSERT 에 들어가지 못했다 — 경합이 재현되지 않았다"
    assert results == {"A": 200, "B": 200}

    active = _active_mappings("wf-concurrent")
    assert len(active) == 1
    assert active[0].created_by == ADMIN_ID
