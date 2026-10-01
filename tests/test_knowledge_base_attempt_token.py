"""생성 시도 ↔ 업스트림 KB 상관 토큰.

앞쪽 두 테스트는 게이트웨이가 생성 결과를 받지 못한 상황을 생성 POST 부터 목록 GET 까지 그대로
재현한다. 업스트림 대역은 받은 description 을 가공 없이 저장한다는 전제만 흉내 낸다.
"""
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models import KnowledgeBase, KnowledgeBaseCreateAttempt
from app.schemas.knowledge_base import (
    ExternalKnowledgeBaseBriefResponse,
    ExternalKnowledgeBaseDetailResponse,
)
from app.services.knowledge_base_service import knowledge_base_service
from tests.test_knowledge_base_recovery import FILENAME, KB_LIST, NAME, _NoCloseSession


@pytest.fixture(autouse=True)
def _attempt_session(db, monkeypatch):
    import app.cruds.knowledge_base as crud_module

    monkeypatch.setattr(crud_module, "SessionLocal", lambda: _NoCloseSession(db))
    yield


class _TimingOutUpstream:
    """생성 요청을 끝까지 처리하지만, 기본값으로는 게이트웨이에 타임아웃(504)으로 답하는 업스트림.

    행은 업스트림 DB 에 저장된 모양 그대로 두고, 응답할 때마다 서비스와 같은 스키마로 새로 파싱한다.
    """

    def __init__(self):
        self.rows = []
        self.list_fails = False
        self.list_calls = 0
        self.sent_descriptions = []
        self.times_out = True

    def _row(self, kb_id):
        return next(r for r in self.rows if r["id"] == kb_id)

    async def get_knowledge_bases(self, *args, **kwargs):
        self.list_calls += 1
        if self.list_fails:
            raise HTTPException(status_code=502, detail="upstream busy")
        return [ExternalKnowledgeBaseBriefResponse(**r) for r in self.rows]

    async def create_knowledge_base(self, *, name, description=None, **kwargs):
        kb_id = 407 + len(self.rows)
        self.sent_descriptions.append(description)
        self.rows.append({
            "id": kb_id, "name": name, "description": description,
            "collection_name": f"col_{kb_id}", "embedding_model_id": 13, "language_id": 1,
            "chunk_size": 500, "chunk_overlap": 50, "chunk_type_id": 1, "search_method_id": 1,
            "top_k": 3, "threshold": 0.4, "created_at": datetime.now(timezone.utc),
            "files": [{"id": 1, "knowledge_base_id": kb_id, "name": FILENAME,
                       "partition_name": "p", "chunk_number": 3}],
        })
        if self.times_out:
            raise HTTPException(status_code=504, detail="timeout")
        return ExternalKnowledgeBaseDetailResponse(**self._row(kb_id))

    async def get_knowledge_base(self, knowledge_base_id, user_info=None):
        return ExternalKnowledgeBaseDetailResponse(**self._row(knowledge_base_id))

    async def update_knowledge_base(self, knowledge_base_id, name=None, description=None,
                                    user_info=None):
        row = self._row(knowledge_base_id)
        if name:
            row["name"] = name
        if description is not None:
            row["description"] = description
        return ExternalKnowledgeBaseDetailResponse(**row)


@pytest.fixture
def upstream(monkeypatch):
    fake = _TimingOutUpstream()
    for method in ("get_knowledge_bases", "create_knowledge_base",
                   "get_knowledge_base", "update_knowledge_base"):
        monkeypatch.setattr(knowledge_base_service, method, getattr(fake, method))
    return fake


@contextmanager
def _as(db, user):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


def _create(client, description=None):
    data = {
        "name": NAME, "language_id": "1", "embedding_model_id": "13", "chunk_size": "500",
        "chunk_overlap": "50", "chunk_type_id": "1", "search_method_id": "1",
        "top_k": "3", "threshold": "0.4",
    }
    if description is not None:
        data["description"] = description
    return client.post(KB_LIST, data=data,
                       files={"file": (FILENAME, b"doc", "application/pdf")})


def _owner_of(db, surro_id):
    kb = db.query(KnowledgeBase).filter(
        KnowledgeBase.surro_knowledge_id == surro_id
    ).one_or_none()
    return kb.created_by if kb else None


# ---------- 시나리오 ----------

@pytest.mark.xfail(strict=True, reason="기존 설계: 같은 이름의 동시 타임아웃은 양쪽 모두 복구를 포기한다")
def test_same_name_concurrent_timeouts_each_recover_to_their_owner(
        db, sample_member, admin_member, upstream):
    """alice 와 bob 이 같은 이름·파일로 연달아 생성했고 둘 다 타임아웃이 났다.

    업스트림은 두 KB 를 모두 만들었다. 각자 목록을 열면 자기 KB 가 자기 소유로 돌아와야 한다.
    이름·파일명·생성 시각으로는 두 KB 를 구별할 수 없다.
    """
    alice, bob = sample_member, admin_member
    with _as(db, alice) as client:
        assert _create(client).status_code == 504
    with _as(db, bob) as client:
        assert _create(client).status_code == 504

    with _as(db, alice) as client:
        assert client.get(KB_LIST).status_code == 200
    with _as(db, bob) as client:
        assert client.get(KB_LIST).status_code == 200

    assert _owner_of(db, 407) == alice.member_id
    assert _owner_of(db, 408) == bob.member_id


@pytest.mark.xfail(strict=True, reason="기존 설계: 생성 직전 목록 조회가 실패하면 그 시도는 복구 대상에서 빠진다")
def test_timeout_is_recovered_even_if_the_pre_create_list_failed(db, sample_member, upstream):
    """업스트림 목록 조회가 실패하던 때 생성이 타임아웃 났고, 업스트림은 KB 를 끝까지 만들었다.

    목록이 정상으로 돌아온 뒤 사용자가 목록을 열면 KB 가 복구돼야 한다.
    """
    upstream.list_fails = True
    with _as(db, sample_member) as client:
        assert _create(client).status_code == 504
    upstream.list_fails = False

    with _as(db, sample_member) as client:
        body = client.get(KB_LIST).json()

    assert [kb["surro_knowledge_id"] for kb in body["data"]] == [407]
    assert _owner_of(db, 407) == sample_member.member_id
