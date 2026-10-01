"""생성 시도 ↔ 업스트림 KB 상관 토큰.

앞쪽 두 테스트는 게이트웨이가 생성 결과를 받지 못한 상황을 생성 POST 부터 목록 GET 까지 그대로
재현한다. 업스트림 대역은 받은 description 을 가공 없이 저장한다는 전제만 흉내 낸다.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.common.kb_attempt_token import (
    MAX_USER_DESCRIPTION,
    attach_token,
    attempt_token,
    make_token,
    split_token,
)
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


# ---------- 토큰 ----------

_T = datetime(2026, 9, 30, 3, 0, 0, 123456, tzinfo=timezone.utc)


def test_token_is_deterministic_and_distinct_per_attempt():
    assert make_token(1, "req-a", _T) == make_token(1, "req-a", _T)
    assert make_token(1, "req-a", _T) != make_token(2, "req-a", _T)
    assert len(make_token(1, "req-a", _T)) == 16
    int(make_token(1, "req-a", _T), 16)


def test_reused_attempt_id_gets_a_different_token():
    """DB 복원으로 id 가 다시 발급돼도, 요청이나 시작 시각이 다르면 토큰이 겹치지 않는다.

    클라이언트가 X-Request-ID 를 고정해 보내면 request_id 만으로는 구분되지 않는다.
    """
    assert make_token(101, "req-before", _T) != make_token(101, "req-after", _T)
    assert make_token(101, "fixed", _T) != make_token(101, "fixed", _T + timedelta(days=3))
    assert len(make_token(101, None, _T)) == 16


def test_token_does_not_depend_on_how_the_db_returns_the_time():
    """SQLite 는 naive, PostgreSQL 은 aware(세션 타임존)로 돌려준다 — 같은 시각이면 같은 토큰이다."""
    kst = timezone(timedelta(hours=9))
    naive_utc = _T.replace(tzinfo=None)
    assert make_token(1, "r", _T) == make_token(1, "r", naive_utc) == make_token(1, "r", _T.astimezone(kst))


@pytest.mark.parametrize("original", [None, "", "사내 규정 모음", "끝이 공백인 설명 "])
def test_attach_then_split_restores_user_description(original):
    """빈 설명은 토큰만 저장되고, 읽을 때는 None 으로 돌아온다."""
    token = make_token(7, "req-a", _T)
    restored, found = split_token(attach_token(original, token))
    assert found == token
    assert restored == (original or None)


def test_split_leaves_text_without_a_valid_token_untouched():
    """형식이 정확히 맞지 않으면 사용자 텍스트다 — 잘라내면 사용자 설명이 사라진다."""
    for text in ["설명", "설명 [kbt:xyz]", "설명 [kbt:0123456789abcdef] 뒤에 글자",
                 "설명 [kbt:0123456789ABCDEF]", "설명[kbt:0123456789abcdef]",
                 "설명 [kbt:0123456789abcdef]\n"]:
        assert split_token(text) == (text, None)


def test_user_description_limit_leaves_room_for_the_token():
    longest = attach_token("가" * MAX_USER_DESCRIPTION, make_token(1, "req-a", _T))
    assert len(longest) == 255
    assert MAX_USER_DESCRIPTION == 232


def test_upstream_schemas_hide_the_token_from_description():
    """업스트림 응답은 모두 이 두 스키마로 파싱된다 — 여기서 떼어내면 이후 어느 경로로도 나가지 않는다."""
    tagged = attach_token("설명", make_token(3, "req-a", _T))
    brief = ExternalKnowledgeBaseBriefResponse(
        id=1, name="n", description=tagged, collection_name="c",
        chunk_size=1, chunk_overlap=0, top_k=1, threshold=0.1,
    )
    detail = ExternalKnowledgeBaseDetailResponse(
        id=1, name="n", description=tagged, collection_name="c", embedding_model_id=1,
        language_id=1, chunk_size=1, chunk_overlap=0, chunk_type_id=1, search_method_id=1,
        top_k=1, threshold=0.1,
    )
    for parsed in (brief, detail):
        assert parsed.description == "설명"
        assert parsed.attempt_token == make_token(3, "req-a", _T)
        assert "attempt_token" not in parsed.model_dump()
        assert "kbt:" not in parsed.model_dump_json()


# ---------- 생성 경로 ----------

def test_create_sends_the_attempt_token_in_description(db, sample_member, upstream):
    with _as(db, sample_member) as client:
        _create(client, description="사내 규정")

    attempt = db.query(KnowledgeBaseCreateAttempt).one()
    assert upstream.sent_descriptions == [attach_token("사내 규정", attempt_token(attempt))]


def test_create_without_description_still_sends_a_token(db, sample_member, upstream):
    with _as(db, sample_member) as client:
        _create(client)

    attempt = db.query(KnowledgeBaseCreateAttempt).one()
    assert upstream.sent_descriptions == [attach_token(None, attempt_token(attempt))]


def test_create_does_not_list_upstream_first(db, sample_member, upstream):
    """생성 전에 업스트림 목록을 부르지 않는다 — 그 조회가 실패하면 복구가 불가능해지던 구조를 없앤다."""
    with _as(db, sample_member) as client:
        _create(client)

    assert upstream.list_calls == 0


def test_too_long_description_is_rejected_before_anything_happens(db, sample_member, upstream):
    """토큰을 붙이면 업스트림 한도를 넘는 설명은 시도 기록도, 업스트림 호출도 없이 거부한다.

    업스트림까지 보내면, 그 실패가 500 으로 오는 경우 생기지도 않은 KB 를 기다리는 시도가 남는다.
    """
    with _as(db, sample_member) as client:
        res = _create(client, description="가" * (MAX_USER_DESCRIPTION + 1))

    assert res.status_code == 422
    assert db.query(KnowledgeBaseCreateAttempt).count() == 0
    assert upstream.sent_descriptions == []


def test_description_at_the_limit_fits_the_upstream_column(db, sample_member, upstream):
    with _as(db, sample_member) as client:
        assert _create(client, description="가" * MAX_USER_DESCRIPTION).status_code == 504

    assert len(upstream.sent_descriptions[0]) == 255


def test_token_never_reaches_the_user(db, sample_member, upstream):
    """업스트림에는 토큰이 붙은 채 저장돼 있어도 사용자에게 나가는 응답과 게이트웨이 DB 에는 없어야 한다."""
    upstream.times_out = False
    with _as(db, sample_member) as client:
        created = _create(client, description="사내 규정")
        listed = client.get(KB_LIST)
        detail = client.get(f"{KB_LIST}/407")
        renamed = client.put(f"{KB_LIST}/407", json={"name": "새 이름"})

    assert "kbt:" in upstream.rows[0]["description"], "전제: 업스트림에는 토큰이 남아 있다"
    for res in (created, listed, detail, renamed):
        assert res.status_code in (200, 201), res.text
        assert "kbt:" not in res.text
    assert created.json()["description"] == "사내 규정"
    assert db.query(KnowledgeBase).one().description == "사내 규정"
