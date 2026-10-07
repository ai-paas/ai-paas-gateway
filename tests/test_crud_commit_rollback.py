"""매핑 CRUD 의 commit 이 실패해도 세션이 오염된 채 남지 않는다.

라우트는 업스트림 변경 뒤의 매핑 저장 실패를 삼키고 같은 세션으로 감사 로그·조회를 잇는다.
CRUD 가 rollback 없이 예외만 올리면 그 뒤 작업이 PendingRollbackError 로 실패한다.
"""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.cruds.dataset import dataset_crud
from app.cruds.experiment import experiment_crud
from app.cruds.knowledge_base import knowledge_base_crud
from app.cruds.model_improvement import model_improvement_crud
from app.database import get_db
from app.main import app
from app.models import Member
from app.models.audit_log import AuditLog
from app.models.dataset import Dataset
from app.models.experiment import Experiment
from app.models.knowledge_base import KnowledgeBase
from app.models.model_improvement import ModelImprovement
from tests.conftest import _engine

MEMBER_ID = "rb-user"
POISON_ID = "rb-poison"


def _purge(session):
    for model in (Dataset, Experiment, KnowledgeBase, ModelImprovement):
        session.query(model).filter(
            model.created_by == MEMBER_ID
        ).delete(synchronize_session=False)
    session.query(AuditLog).filter(
        AuditLog.actor_member_id == MEMBER_ID
    ).delete(synchronize_session=False)
    session.query(Member).filter(
        Member.member_id.in_([MEMBER_ID, POISON_ID])
    ).delete(synchronize_session=False)
    session.commit()


@pytest.fixture
def real_db():
    """CRUD 의 rollback 이 실제로 동작하는 세션. 운영 SessionLocal 과 같이 autoflush 를 끈다.

    공용 `db` fixture 는 외부 트랜잭션에 rollback_only 로 참여해 rollback 이 준비 데이터까지 되돌린다.
    """
    connection = _engine.connect()
    session = Session(bind=connection, autoflush=False)
    _purge(session)
    member = Member(
        name="rb user", member_id=MEMBER_ID, email=f"{MEMBER_ID}@example.com",
        password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
        role="user", is_active=True,
    )
    session.add(member)
    session.commit()
    try:
        yield session, member
    finally:
        session.rollback()
        _purge(session)
        session.close()
        connection.close()


def _poison(db):
    """다음 commit 의 flush 를 실패시킨다 (name NOT NULL 위반)."""
    db.add(Member(
        name=None, member_id=POISON_ID, email=f"{POISON_ID}@example.com",
        password_hash="x", role="user", is_active=True,
    ))


def _dataset(db, surro_id=7001):
    return dataset_crud.create_dataset_mapping(
        db, surro_dataset_id=surro_id, member_id=MEMBER_ID, dataset_name="ds",
    )


def _kb(db, surro_id=7101):
    return knowledge_base_crud.create_knowledge_base(
        db, name="kb", description=None, created_by=MEMBER_ID,
        surro_knowledge_id=surro_id, collection_name="col",
    )


CASES = {
    "dataset.create_dataset_mapping": (
        None,
        lambda db: dataset_crud.create_dataset_mapping(
            db, surro_dataset_id=7002, member_id=MEMBER_ID, dataset_name="new",
        ),
    ),
    "dataset.backfill_cache_if_changed": (
        _dataset,
        lambda db: dataset_crud.backfill_cache_if_changed(
            db, surro_dataset_id=7001, member_id=MEMBER_ID, name="renamed",
        ),
    ),
    "dataset.delete_dataset_mapping": (
        _dataset,
        lambda db: dataset_crud.delete_dataset_mapping(
            db, surro_dataset_id=7001, member_id=MEMBER_ID,
        ),
    ),
    "knowledge_base.update_knowledge_base_by_surro_id": (
        _kb,
        lambda db: knowledge_base_crud.update_knowledge_base_by_surro_id(
            db, surro_knowledge_id=7101, name="kb2", description=None,
            collection_name="col", updated_by=MEMBER_ID,
        ),
    ),
    "knowledge_base.delete_knowledge_base_by_surro_id": (
        _kb,
        lambda db: knowledge_base_crud.delete_knowledge_base_by_surro_id(
            db, surro_knowledge_id=7101, deleted_by=MEMBER_ID,
        ),
    ),
    "experiment.create_mapping": (
        None,
        lambda db: experiment_crud.create_mapping(
            db, surro_experiment_id=7201, member_id=MEMBER_ID, name="exp",
        ),
    ),
    "model_improvement.create_mapping": (
        None,
        lambda db: model_improvement_crud.create_mapping(
            db, task_id="rb-task", source_model_id=1, task_type="optimization",
            member_id=MEMBER_ID,
        ),
    ),
}


@pytest.mark.parametrize("case", list(CASES))
def test_failed_commit_leaves_session_usable(real_db, case):
    db, _ = real_db
    setup, call = CASES[case]
    if setup:
        setup(db)

    _poison(db)
    with pytest.raises(Exception):
        call(db)

    # rollback 됐다면 같은 세션으로 바로 조회할 수 있다
    assert db.query(Member).filter(Member.member_id == MEMBER_ID).one().member_id == MEMBER_ID
    assert db.query(Member).filter(Member.member_id == POISON_ID).first() is None


@contextmanager
def _client(db, member):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: member
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _poisoned(real_method):
    def wrapper(db, *args, **kwargs):
        _poison(db)
        return real_method(db, *args, **kwargs)
    return wrapper


def test_dataset_update_survives_mapping_sync_failure(real_db, monkeypatch):
    """매핑 동기화가 실패해도 이어지는 조회가 깨지지 않아 수정 응답이 200 이다."""
    db, member = real_db
    _dataset(db)
    # 운영에서는 인증 단계에서 읽은 회원이 만료되지 않은 채 라우트에 들어온다
    db.refresh(member)

    async def fake_update_dataset(dataset_id, dataset_data, user_info):
        return SimpleNamespace(
            id=dataset_id, name="renamed", description=None, kind=None,
            dataset_registry={"id": 1, "artifact_path": "a", "uri": "u", "dataset_id": dataset_id},
            created_at=None, updated_at=None, deleted_at=None,
            created_by=None, updated_by=None, deleted_by=None,
        )

    monkeypatch.setattr(
        "app.routes.dataset.dataset_service.update_dataset", fake_update_dataset
    )
    monkeypatch.setattr(
        dataset_crud, "backfill_cache_if_changed",
        _poisoned(dataset_crud.backfill_cache_if_changed),
    )

    with _client(db, member) as client:
        response = client.put("/api/v1/datasets/7001", json={"name": "renamed"})

    assert response.status_code == 200
    assert response.json()["created_by"] == MEMBER_ID


def test_dataset_delete_records_audit_after_mapping_failure(real_db, monkeypatch):
    """매핑 삭제가 실패해도 감사 로그는 남는다."""
    db, member = real_db
    _dataset(db)
    # 운영에서는 인증 단계에서 읽은 회원이 만료되지 않은 채 라우트에 들어온다
    db.refresh(member)

    async def fake_delete_dataset(dataset_id, user_info):
        return None

    monkeypatch.setattr(
        "app.routes.dataset.dataset_service.delete_dataset", fake_delete_dataset
    )
    monkeypatch.setattr(
        dataset_crud, "delete_dataset_mapping",
        _poisoned(dataset_crud.delete_dataset_mapping),
    )

    with _client(db, member) as client:
        response = client.delete("/api/v1/datasets/7001")

    assert response.status_code == 200
    audit = db.query(AuditLog).filter(
        AuditLog.actor_member_id == MEMBER_ID,
        AuditLog.resource_id == "7001",
    ).all()
    assert len(audit) == 1
