"""복구가 도중에 실패했을 때 목록 조회가 살아남는지 — 실제 rollback 경로 검증.

전역 `db` fixture 는 외부 트랜잭션에 rollback_only 로 참여해, 라우트가 호출하는
`db.rollback()` 이 테스트 준비 데이터까지 되돌린다(tests/conftest.py 의 `db` 주석 참고).
그래서 준비 데이터를 실제로 commit 하는 `committed_session`(tests/conftest.py)을 쓴다.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import AttemptState, AuditLog, KnowledgeBase, KnowledgeBaseCreateAttempt, Member
from app.cruds.knowledge_base import knowledge_base_crud as crud
from tests.conftest import committed_session, make_member
from tests.test_knowledge_base_recovery import (
    FILENAME,
    NAME,
    _NoCloseSession,
    _brief,
    _client,
)

KB_LIST = "/api/v1/knowledge-bases"

NOW = datetime.now(timezone.utc)
T0 = NOW - timedelta(hours=2)


def _purge(session):
    # 복구가 남기는 감사로그까지 지우지 않으면 다음 테스트의 AuditLog 조회에 섞인다.
    session.query(AuditLog).delete()
    session.query(KnowledgeBaseCreateAttempt).delete()
    session.query(KnowledgeBase).delete()
    session.query(Member).filter(Member.member_id == "rec-user").delete()


@pytest.fixture
def real_db(monkeypatch):
    """커밋된 회원 1명.

    시도 레코드 CRUD 는 SessionLocal() 을 쓰므로 같은 세션을 보도록 함께 바꾼다.
    """
    import app.cruds.knowledge_base as crud_module

    with committed_session(_purge) as session:
        member = make_member("rec-user", name="복구 테스터")
        session.add(member)
        session.commit()
        monkeypatch.setattr(crud_module, "SessionLocal", lambda: _NoCloseSession(session))
        yield session, member


def _attempt(session, member_id, started_at, request_id):
    """롤백 경로를 검증하므로 준비 데이터는 flush 가 아니라 commit 해야 한다."""
    a = KnowledgeBaseCreateAttempt(
        member_id=member_id, name=NAME, filename=FILENAME, request_id=request_id,
        upstream_snapshot=[1, 2], state=AttemptState.ORPHAN_SUSPECT, started_at=started_at,
    )
    session.add(a)
    session.commit()
    return a.id


def test_list_survives_failure_after_partial_recovery(real_db, monkeypatch):
    """하나를 복구해 커밋한 뒤 다음에서 실패해도 목록이 깨지지 않아야 한다.

    복구의 커밋이 세션에 올려둔 객체를 만료시키므로, 롤백하고 다시 읽지 않으면 응답
    조립이 지연 로드를 시도하다 깨진다.
    """
    session, member = real_db
    a1 = _attempt(session, member.member_id, started_at=T0, request_id="req-1")
    a2 = _attempt(session, member.member_id,
                  started_at=T0 + timedelta(minutes=90), request_id="req-2")
    upstream = [_brief(407, token_for=session.get(KnowledgeBaseCreateAttempt, a1)),
                _brief(408, token_for=session.get(KnowledgeBaseCreateAttempt, a2))]

    calls = []
    real_try_lock = crud.try_lock_surro_knowledge_id

    def fail_on_second_claim(db, surro_id):
        calls.append(surro_id)
        if len(calls) == 2:
            raise RuntimeError("claim hiccup")
        return real_try_lock(db, surro_id)
    monkeypatch.setattr(crud, "try_lock_surro_knowledge_id", fail_on_second_claim)

    with _client(session, member, upstream) as client:
        res = client.get(KB_LIST)

    assert res.status_code == 200, "복구가 도중에 실패해도 목록은 살아야 한다"
    assert len(calls) == 2, "두 시도 모두 처리를 시도해야 한다"
    assert [x["surro_knowledge_id"] for x in res.json()["data"]] == [407], \
        "먼저 복구된 KB 가 응답에 담겨야 한다 — 롤백 후 다시 읽는다"

    session.expire_all()
    assert session.get(KnowledgeBaseCreateAttempt, a1).state == AttemptState.RECOVERED
    assert session.get(KnowledgeBaseCreateAttempt, a2).state == AttemptState.ORPHAN_SUSPECT, \
        "실패한 쪽은 그대로 남아 다음 조회에서 다시 시도된다"


def test_list_survives_db_error_during_recovery(real_db, monkeypatch):
    """복구 도중 DB 오류로 세션 트랜잭션이 무효가 돼도 목록이 살아야 한다.

    flush 실패는 SQLAlchemy 가 트랜잭션을 비활성으로 표시하므로, 롤백하지 않으면 이후
    응답 조립의 지연 로드가 PendingRollbackError 로 깨져 사용자가 목록 자체를 못 본다.
    앞 테스트(일반 예외)는 데이터가 낡는 데 그치지만, 이쪽은 500 이 된다.
    """
    session, member = real_db
    # 기존 KB 가 한 건은 있어야 한다. 응답 조립이 지연 로드할 객체가 없으면 세션이 죽어도
    # 아무 일도 일어나지 않아, 정작 막으려는 증상이 재현되지 않는다.
    session.add(KnowledgeBase(
        name=NAME, collection_name="col_500", created_by=member.member_id,
        surro_knowledge_id=500, is_active=True,
    ))
    session.commit()

    a1 = _attempt(session, member.member_id, started_at=T0, request_id="req-1")
    a2 = _attempt(session, member.member_id,
                  started_at=T0 + timedelta(minutes=90), request_id="req-2")
    upstream = [
        _brief(500, created_at=T0),
        _brief(407, token_for=session.get(KnowledgeBaseCreateAttempt, a1)),
        _brief(408, token_for=session.get(KnowledgeBaseCreateAttempt, a2)),
    ]

    calls = []
    real_try_lock = crud.try_lock_surro_knowledge_id

    def break_session_on_second_claim(db, surro_id):
        calls.append(surro_id)
        if len(calls) == 2:
            # NOT NULL 을 전부 위반해 flush 를 실패시킨다.
            session.add(KnowledgeBaseCreateAttempt())
            session.flush()
        return real_try_lock(db, surro_id)
    monkeypatch.setattr(crud, "try_lock_surro_knowledge_id", break_session_on_second_claim)

    with _client(session, member, upstream) as client:
        res = client.get(KB_LIST)

    assert res.status_code == 200, "세션 트랜잭션이 무효가 돼도 목록은 살아야 한다"
    assert sorted(x["surro_knowledge_id"] for x in res.json()["data"]) == [407, 500]
