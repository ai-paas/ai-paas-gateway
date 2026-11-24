"""생성 요청과 목록 자동 등록이 겹쳐도 만든 사람이 워크플로우를 갖는다.

생성 라우트는 MLOps 에 워크플로우를 만든 뒤 매핑을 저장한다. 그 사이 다른 요청의 목록 조회가
같은 워크플로우를 admin 소유로 자동 등록하면, 생성 요청은 유니크 위반으로 실패하고 만든 사람은
자기 워크플로우에 403 을 받았다. 자동 등록 행(registered_via='auto')만 생성자가 넘겨받고,
사람이 만든 행이나 표시가 없는 기존 행과 충돌하면 409 로 거절한다.
"""
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.cruds.workflow import REGISTERED_VIA_AUTO, workflow_crud
from app.database import get_db
from app.main import app
from app.models import Member
from app.models.audit_log import AuditLog
from app.models.workflow import Workflow
from app.schemas.workflow import ExternalWorkflowBriefResponse
from tests.conftest import _engine, committed_session, make_member

USER_ID = "wf-claim-user"
OTHER_ID = "wf-claim-other"
ADMIN_ID = "wf-claim-admin"
MEMBERS = [USER_ID, OTHER_ID, ADMIN_ID]
SURRO_ID = "wf-claim-1"

# 스레드 조율용 대기 상한. 넘었다는 것은 조율이 깨졌다는 뜻이다.
SYNC_TIMEOUT = 15.0


def _purge(session):
    session.query(AuditLog).filter(
        AuditLog.actor_member_id.in_(MEMBERS)
    ).delete(synchronize_session=False)
    session.query(Workflow).filter(
        Workflow.created_by.in_(MEMBERS)
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


def _existing(db, owner, registered_via=None):
    db.add(Workflow(
        name="wf", created_by=owner, surro_workflow_id=SURRO_ID, registered_via=registered_via,
    ))
    db.commit()


def _active_mappings():
    """라우트 세션과 무관하게 커밋된 활성 매핑을 읽는다."""
    check = Session(bind=_engine)
    try:
        return check.query(Workflow).filter(
            Workflow.surro_workflow_id == SURRO_ID,
            Workflow.deleted_at.is_(None),
        ).all()
    finally:
        check.close()


def _fake_create(monkeypatch, before_return=None):
    async def fake_create_workflow(**kwargs):
        if before_return:
            before_return()
        return SimpleNamespace(
            id=SURRO_ID, name=kwargs["name"], description=None, category=None,
            status="DRAFT", service_id=None, is_template=False, template_id=None,
        )

    monkeypatch.setattr(
        "app.routes.workflow.workflow_service.create_workflow", fake_create_workflow
    )


def _fake_clone(monkeypatch):
    async def fake_clone_template(**kwargs):
        return {"id": SURRO_ID, "name": kwargs["workflow_name"], "description": None}

    monkeypatch.setattr(
        "app.routes.workflow.workflow_service.clone_template", fake_clone_template
    )


def _fake_list(monkeypatch):
    async def fake_get_workflows(**kwargs):
        return [ExternalWorkflowBriefResponse(
            id=SURRO_ID, name="wf", status="DRAFT", creator_id=1, is_template=False,
        )]

    monkeypatch.setattr(
        "app.routes.workflow.workflow_service.get_workflows", fake_get_workflows
    )


def test_list_auto_registration_is_marked(real_db, monkeypatch):
    db, user = real_db
    _fake_list(monkeypatch)

    with _client(db, user) as client:
        assert client.get("/api/v1/workflows").status_code == 200

    [mapping] = _active_mappings()
    assert mapping.created_by == ADMIN_ID
    assert mapping.registered_via == REGISTERED_VIA_AUTO


def test_create_reclaims_auto_registered_mapping(real_db, monkeypatch):
    db, user = real_db
    _existing(db, ADMIN_ID, registered_via=REGISTERED_VIA_AUTO)
    _fake_create(monkeypatch)

    with _client(db, user) as client:
        response = client.post("/api/v1/workflows", json={"name": "wf"})

    assert response.status_code == 201
    assert response.json()["created_by"] == USER_ID
    [mapping] = _active_mappings()
    assert mapping.created_by == USER_ID
    assert mapping.registered_via is None
    audit = db.query(AuditLog).filter(
        AuditLog.actor_member_id == USER_ID, AuditLog.resource_id == SURRO_ID,
    ).one()
    assert audit.metadata_json["ownership_reclaimed"] is True


@pytest.mark.parametrize("owner", [OTHER_ID, ADMIN_ID], ids=["member", "legacy-admin"])
def test_create_does_not_take_unmarked_mapping(real_db, monkeypatch, owner):
    """사람이 만든 행, 표시가 없는 기존 admin 행과 충돌하면 넘겨받지 않고 409 다."""
    db, user = real_db
    _existing(db, owner)
    _fake_create(monkeypatch)

    with _client(db, user) as client:
        response = client.post("/api/v1/workflows", json={"name": "wf"})

    assert response.status_code == 409
    assert [w.created_by for w in _active_mappings()] == [owner]


def test_clone_reclaims_auto_registered_mapping(real_db, monkeypatch):
    db, user = real_db
    _existing(db, ADMIN_ID, registered_via=REGISTERED_VIA_AUTO)
    _fake_clone(monkeypatch)

    with _client(db, user) as client:
        response = client.post(
            "/api/v1/workflows/templates/tpl-1/clone", params={"workflow_name": "wf"},
        )

    assert response.status_code == 200
    assert response.json()["db_created_by"] == USER_ID
    assert [w.created_by for w in _active_mappings()] == [USER_ID]


def test_clone_reports_mapping_conflict(real_db, monkeypatch):
    """예전에는 저장 실패를 삼키고 200 을 줘, 사용자는 성공으로 알고 403 을 받았다."""
    db, user = real_db
    _existing(db, OTHER_ID)
    _fake_clone(monkeypatch)

    with _client(db, user) as client:
        response = client.post(
            "/api/v1/workflows/templates/tpl-1/clone", params={"workflow_name": "wf"},
        )

    assert response.status_code == 409
    assert [w.created_by for w in _active_mappings()] == [OTHER_ID]


def test_clone_reports_mapping_save_failure(real_db, monkeypatch):
    db, user = real_db
    _fake_clone(monkeypatch)

    def broken_create(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(workflow_crud, "create_workflow", broken_create)

    with _client(db, user) as client:
        response = client.post(
            "/api/v1/workflows/templates/tpl-1/clone", params={"workflow_name": "wf"},
        )

    assert response.status_code == 500


@pytest.mark.postgres
@pytest.mark.skipif(
    _engine.dialect.name != "postgresql",
    reason="실제 트랜잭션 경합은 PostgreSQL 에서만 재현한다 — TEST_DATABASE_URL 필요",
)
def test_list_during_create_does_not_take_ownership(real_db, monkeypatch):
    """MLOps 생성과 매핑 저장 사이에 다른 요청의 목록 조회가 끝까지 실행돼도 생성자가 갖는다."""
    _, user = real_db
    caller = SimpleNamespace(member_id=user.member_id, role="user", name=user.name)
    list_status = {}

    def list_in_other_request():
        # 생성 요청과 별개의 요청·세션으로 목록을 조회해 자동 등록을 끝까지 커밋시킨다
        def run():
            with TestClient(app) as client:
                list_status["code"] = client.get("/api/v1/workflows").status_code

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
            response = client.post("/api/v1/workflows", json={"name": "wf"})
    finally:
        app.dependency_overrides.clear()

    assert list_status == {"code": 200}
    assert response.status_code == 201
    [mapping] = _active_mappings()
    assert mapping.created_by == USER_ID
    assert mapping.registered_via is None
