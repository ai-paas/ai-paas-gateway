"""고아 Knowledge Base 관리자 라우트.

고아만 노출 / active 매핑 미노출 / 매핑 있는 id 삭제 거부 /
보호 대상 409·force 시 삭제 + 시도 abandoned /
복구 창 밖 KB 는 살아 있는 시도가 있어도 보호되지 않음.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.auth import get_current_admin_user, get_current_user
from app.config import settings
from app.database import get_db
from app.main import app
from app.models import AttemptState, AuditLog, KnowledgeBase, KnowledgeBaseCreateAttempt
from app.schemas.knowledge_base import ExternalKnowledgeBaseBriefResponse
from app.services.knowledge_base_service import knowledge_base_service

ORPHANS = "/api/v1/knowledge-bases/admin/orphans"

NOW = datetime.now(timezone.utc)
T0 = NOW - timedelta(hours=3)
MAX_INGEST = timedelta(seconds=settings.KB_MAX_INGEST_SECONDS)


def _external(kb_id, name="kb", created_at=None):
    return ExternalKnowledgeBaseBriefResponse(
        id=kb_id,
        name=name,
        description=None,
        collection_name=f"kb_col_{kb_id}",
        chunk_size=500,
        chunk_overlap=50,
        top_k=3,
        threshold=0.4,
        created_at=created_at if created_at is not None else T0 + timedelta(minutes=30),
    )


@contextmanager
def _client(db, user, upstream, deleted=True, admin=True, on_list=None, delete_calls=None,
            on_delete=None):
    """업스트림 응답을 고정한 TestClient.

    `on_list` 는 업스트림 목록을 await 하는 동안, `on_delete` 는 업스트림 DELETE 를 await 하는
    동안 다른 작업이 끼어드는 상황을 재현한다 — 라우트가 그 await 전에 판정을 다시 했는지,
    선점을 끝냈는지 검증하는 용도다.
    `delete_calls` 를 주면 업스트림 DELETE 가 실제로 불렸는지 확인할 수 있다.
    """
    async def fake_list(*args, **kwargs):
        if on_list is not None:
            on_list()
        return upstream

    async def fake_delete(knowledge_base_id, user_info=None):
        if delete_calls is not None:
            delete_calls.append(knowledge_base_id)
        if on_delete is not None:
            on_delete(knowledge_base_id)
        return deleted

    original_list = knowledge_base_service.get_knowledge_bases
    original_delete = knowledge_base_service.delete_knowledge_base
    knowledge_base_service.get_knowledge_bases = fake_list
    knowledge_base_service.delete_knowledge_base = fake_delete

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user
    if admin:
        app.dependency_overrides[get_current_admin_user] = lambda: user
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        knowledge_base_service.get_knowledge_bases = original_list
        knowledge_base_service.delete_knowledge_base = original_delete


def _mapping(db, member_id, surro_id, name="kb"):
    kb = KnowledgeBase(
        name=name,
        collection_name=f"kb_col_{surro_id}",
        created_by=member_id,
        surro_knowledge_id=surro_id,
        is_active=True,
    )
    db.add(kb)
    db.flush()
    return kb


def _attempt(db, member_id, snapshot, started_at=T0, state=AttemptState.ORPHAN_SUSPECT):
    a = KnowledgeBaseCreateAttempt(
        member_id=member_id,
        name="사내규정_2026",
        filename="규정.pdf",
        request_id="req-1",
        upstream_snapshot=snapshot,
        state=state,
        started_at=started_at,
    )
    db.add(a)
    db.flush()
    return a


# ---------- 목록 ----------

def test_list_orphans_excludes_active_mappings(db, admin_member):
    _mapping(db, admin_member.member_id, surro_id=100)
    upstream = [_external(100), _external(407)]

    with _client(db, admin_member, upstream) as client:
        body = client.get(ORPHANS).json()

    assert body["total"] == 1, "active 매핑이 있는 건은 고아가 아니다"
    assert body["data"][0]["surro_knowledge_id"] == 407


def test_list_orphans_marks_protected(db, admin_member):
    _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])
    upstream = [_external(407, created_at=T0 + timedelta(minutes=30))]

    with _client(db, admin_member, upstream) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is True, "창 안에 생긴 미지 KB 는 복구 대기로 표시돼야 한다"
    assert admin_member.member_id in item["protected_by"]


def test_list_orphans_marks_pending_create_as_protected(db, admin_member, sample_member):
    """생성이 진행 중인 KB 는 업스트림에 이미 보이지만 매핑은 아직 없다 — 고아가 아니다."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2, 3], state=AttemptState.PENDING)

    with _client(db, admin_member, upstream=[_external(407)]) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is True
    assert sample_member.member_id in item["protected_by"]


def test_list_orphans_marks_snapshotless_pending_create_as_protected(db, admin_member, sample_member):
    """스냅샷 없이 생성 중인 KB 도 보호 대상으로 보여야 한다.

    여기서 보호되지 않으면 관리자는 "안전하게 지울 수 있는 고아" 로 읽고 남이 만드는 중인 KB 를 지운다.
    """
    _attempt(db, sample_member.member_id, snapshot=None, state=AttemptState.PENDING)

    with _client(db, admin_member, [_external(407)]) as client:
        body = client.get(ORPHANS).json()

    assert body["data"][0]["is_protected"] is True
    assert sample_member.member_id in body["data"][0]["protected_by"]


def test_list_orphans_protects_kb_with_unknown_created_at(db, admin_member, sample_member):
    """업스트림이 created_at 을 주지 않으면 시간 창 판정 자체가 불가능하다 — 보호 쪽으로 떨어진다.

    생성 시각을 모른다는 것은 "이 KB 가 진행 중인 시도의 결과물이 아니다" 를 확인할 수 없다는
    뜻이다. 정리 잡은 이미 같은 결측을 보수적으로 다뤄 대상에서 제외하는데, 관리자 삭제만
    반대로 동작하면 자동으로는 못 지우는 KB 를 수동으로는 언제나 지울 수 있게 된다.
    """
    _attempt(db, sample_member.member_id, snapshot=None, state=AttemptState.PENDING)
    kb = _external(407)
    kb.created_at = None

    with _client(db, admin_member, [kb]) as client:
        body = client.get(ORPHANS).json()

    assert body["data"][0]["is_protected"] is True
    assert sample_member.member_id in body["data"][0]["protected_by"]


def test_list_orphans_does_not_protect_unknown_created_at_without_live_attempts(db, admin_member):
    """살아 있는 시도가 없으면 created_at 을 몰라도 보호하지 않는다.

    보호의 근거는 "진행 중인 시도의 결과물일 수 있다" 이므로, 진행 중인 시도가 하나도 없으면
    근거가 없다. 여기까지 보호하면 관리자가 손댈 수 없는 KB 가 생긴다.
    """
    kb = _external(407)
    kb.created_at = None

    with _client(db, admin_member, [kb]) as client:
        body = client.get(ORPHANS).json()

    assert body["data"][0]["is_protected"] is False


def test_delete_rejects_unknown_created_at_while_a_create_is_live(db, admin_member, sample_member):
    """생성 시각을 모르는 KB 는 진행 중인 시도가 있는 한 force 없이 지울 수 없다."""
    _attempt(db, sample_member.member_id, snapshot=None, state=AttemptState.PENDING)
    kb = _external(407)
    kb.created_at = None
    delete_calls = []

    with _client(db, admin_member, upstream=[kb], delete_calls=delete_calls) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert delete_calls == [], "업스트림 DELETE 가 불리면 안 된다"


def test_list_orphans_outside_recovery_window_is_not_protected(db, admin_member):
    """복구 창 밖 KB 는 살아 있는 시도가 있어도 보호되지 않는다.

    보호 범위가 복구 범위보다 넓으면, 복구되지도 않으면서 삭제만 막히는 구간이 생긴다.
    """
    _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])
    upstream = [_external(407, created_at=T0 + MAX_INGEST + timedelta(minutes=1))]

    with _client(db, admin_member, upstream) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is False
    assert item["protected_by"] is None


def test_list_orphans_ignores_attempt_that_already_knew_the_kb(db, admin_member):
    """스냅샷에 이미 있던 id 는 그 시도의 결과일 수 없다."""
    _attempt(db, admin_member.member_id, snapshot=[407])
    upstream = [_external(407)]

    with _client(db, admin_member, upstream) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is False


def test_list_orphans_refuses_empty_upstream(db, admin_member):
    """빈 응답을 '전부 고아'로 해석하면 안 된다."""
    with _client(db, admin_member, upstream=[]) as client:
        assert client.get(ORPHANS).status_code == 503


def test_list_orphans_requires_admin(db, sample_member):
    with _client(db, sample_member, upstream=[_external(407)], admin=False) as client:
        assert client.get(ORPHANS).status_code == 403


# ---------- 삭제 ----------

def test_delete_rejects_when_active_mapping_exists(db, admin_member):
    _mapping(db, admin_member.member_id, surro_id=100)

    with _client(db, admin_member, upstream=[_external(100)]) as client:
        res = client.delete(f"{ORPHANS}/100")

    assert res.status_code == 409, "매핑이 있으면 고아가 아니므로 일반 삭제 경로를 써야 한다"


def test_delete_rejects_protected_without_force(db, admin_member):
    _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])
    upstream = [_external(407, created_at=T0 + timedelta(minutes=30))]

    with _client(db, admin_member, upstream) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert "force" in res.json()["detail"]


def test_delete_protected_with_force_abandons_attempt(db, admin_member):
    attempt = _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])
    upstream = [_external(407, name="사내규정_2026", created_at=T0 + timedelta(minutes=30))]

    with _client(db, admin_member, upstream) as client:
        res = client.delete(f"{ORPHANS}/407?force=true")

    assert res.status_code == 200
    body = res.json()
    assert body["forced"] is True
    assert body["abandoned_attempts"] == 1

    db.refresh(attempt)
    assert attempt.state == AttemptState.ABANDONED, (
        "붙을 대상이 사라진 시도를 남기면 ATTEMPT_TTL 동안 무관한 고아를 계속 보호한다"
    )
    assert attempt.finished_at is not None

    log = db.query(AuditLog).filter(AuditLog.resource_id == "407").one()
    assert log.action == "delete"
    assert log.metadata_json["forced"] is True
    assert log.metadata_json["orphan"] is True


def test_delete_rejects_when_recovery_completed_during_upstream_call(db, admin_member, sample_member):
    """업스트림 목록을 await 하는 사이 자동 복구가 끝나면 삭제하지 않는다.

    복구가 끝나면 시도는 recovered 가 되어 보호 판정에서 빠진다. 매핑을 다시 확인하지
    않으면 방금 정상 소유자가 생긴 KB 를 force 없이 지우게 된다.
    """
    attempt = _attempt(db, sample_member.member_id, snapshot=[1, 2, 3])
    delete_calls = []

    def recovery_finishes_first():
        _mapping(db, sample_member.member_id, surro_id=407)
        attempt.state = AttemptState.RECOVERED
        db.flush()

    with _client(db, admin_member, upstream=[_external(407)],
                 on_list=recovery_finishes_first, delete_calls=delete_calls) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert delete_calls == [], "업스트림 DELETE 가 불리면 안 된다"


def test_delete_rejects_while_create_is_pending(db, admin_member, sample_member):
    """생성이 진행 중인 KB 는 force 없이 지울 수 없다."""
    _attempt(db, sample_member.member_id, snapshot=[1, 2, 3], state=AttemptState.PENDING)
    delete_calls = []

    with _client(db, admin_member, upstream=[_external(407)],
                 delete_calls=delete_calls) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert delete_calls == []


def test_delete_rejects_while_snapshotless_create_is_pending(db, admin_member, sample_member):
    """스냅샷 없이 생성이 진행 중인 KB 는 force 없이 지울 수 없다.

    지워 버리면 생성 라우트는 그대로 매핑을 써서, 업스트림에 없는 KB 카드가 사용자 목록에 남는다.
    """
    _attempt(db, sample_member.member_id, snapshot=None, state=AttemptState.PENDING)
    delete_calls = []

    with _client(db, admin_member, upstream=[_external(407)],
                 delete_calls=delete_calls) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert delete_calls == [], "업스트림 DELETE 가 불리면 안 된다"


def test_delete_abandons_protectors_before_calling_upstream(db, admin_member):
    """force 삭제는 업스트림 DELETE 보다 먼저 시도를 끊어야 한다.

    이 순서라야 락을 놓은 뒤에도 진행 중인 복구가 사라진 KB 에 매핑을 붙이지 못한다.
    """
    attempt = _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])
    states_at_delete = []

    def fake_delete_recording_state(knowledge_base_id, user_info=None):
        db.refresh(attempt)
        states_at_delete.append(attempt.state)

    with _client(db, admin_member, upstream=[_external(407, name="사내규정_2026")]) as client:
        original = knowledge_base_service.delete_knowledge_base

        async def spy(knowledge_base_id, user_info=None):
            fake_delete_recording_state(knowledge_base_id, user_info)
            return True

        knowledge_base_service.delete_knowledge_base = spy
        try:
            res = client.delete(f"{ORPHANS}/407?force=true")
        finally:
            knowledge_base_service.delete_knowledge_base = original

    assert res.status_code == 200
    assert states_at_delete == [AttemptState.ABANDONED]


def test_every_live_attempt_is_cut_before_upstream_delete_starts(db, admin_member, sample_member):
    """업스트림 DELETE 가 시작되는 시점에는 이 KB 를 가져갈 수 있는 시도가 전부 끊겨 있어야 한다.

    DELETE 는 락 밖에서 일어난다 — 트랜잭션 범위 락은 commit 으로 풀리고, 업스트림 HTTP 호출을
    트랜잭션 안에 둘 수는 없다. 그래서 안전성은 락이 아니라 선점이 보장한다: 락 안에서 후보를
    모두 끊어 커밋한 뒤에 DELETE 를 부른다. 스냅샷이 없어 판정할 수 없는 시도도 후보이므로
    함께 끊겨야 하며, 하나라도 살아남으면 사라진 KB 에 매핑이 붙는다.
    """
    with_snapshot = _attempt(db, sample_member.member_id, snapshot=[1, 2, 3])
    without_snapshot = _attempt(db, sample_member.member_id, snapshot=None,
                                state=AttemptState.PENDING)
    states_at_delete = []

    def inspect(_kb_id):
        db.refresh(with_snapshot)
        db.refresh(without_snapshot)
        states_at_delete.append((with_snapshot.state, without_snapshot.state))

    with _client(db, admin_member, upstream=[_external(407, name="사내규정_2026")],
                 on_delete=inspect) as client:
        res = client.delete(f"{ORPHANS}/407?force=true")

    assert res.status_code == 200
    assert states_at_delete == [(AttemptState.ABANDONED, AttemptState.ABANDONED)],         "DELETE 시점에 살아 있는 시도가 남으면 선점이 불완전하다"


def test_attempt_started_during_upstream_delete_cannot_claim_the_kb(db, admin_member, sample_member):
    """DELETE 를 await 하는 사이에 시작된 생성 시도는 이 KB 를 가져갈 수 없다.

    선점이 성립하려면 끊어 놓은 뒤로 후보가 다시 생기지 않아야 한다. 새 시도는 시작 시각이
    KB 생성 시각보다 뒤라 시간 창에서 탈락한다 — 스냅샷이 비어 있어도 마찬가지다.
    """
    from app.cruds.knowledge_base import knowledge_base_crud

    claimants_after_new_attempt = []

    def start_new_attempt(_kb_id):
        _attempt(db, sample_member.member_id, snapshot=None,
                 started_at=datetime.now(timezone.utc), state=AttemptState.PENDING)
        live = knowledge_base_crud.get_live_attempts(db, datetime.now(timezone.utc))
        claimants_after_new_attempt.append(
            knowledge_base_crud.find_protecting_attempts(_external(407), live)
        )

    with _client(db, admin_member, upstream=[_external(407)],
                 on_delete=start_new_attempt) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 200
    assert claimants_after_new_attempt == [[]], "뒤늦게 시작한 시도가 후보가 되면 선점이 무의미하다"


def test_force_delete_keeps_attempts_that_cannot_claim_the_kb(db, admin_member, sample_member):
    """force 삭제는 이 KB 를 가져갈 수 있는 시도만 끊는다.

    이름이 다른 시도는 복구가 이 KB 를 후보로 삼지 않는다. 그런 시도까지 끊으면 종결 상태는
    되돌릴 수 없어, 같은 시간대에 다른 KB 를 만들던 사용자의 복구 기회가 영구히 사라진다.
    """
    other = _attempt(db, sample_member.member_id, snapshot=[1, 2, 3])
    upstream = [_external(407, name="다른_KB", created_at=T0 + timedelta(minutes=30))]

    with _client(db, admin_member, upstream) as client:
        res = client.delete(f"{ORPHANS}/407?force=true")

    assert res.status_code == 200
    assert res.json()["forced"] is True
    assert res.json()["abandoned_attempts"] == 0
    db.refresh(other)
    assert other.state == AttemptState.ORPHAN_SUSPECT


def test_force_delete_of_kb_without_created_at_cuts_nothing(db, admin_member, sample_member):
    """created_at 없는 KB 는 복구 후보가 될 수 없으므로 선점할 시도도 없다.

    보호 판정은 결측을 보호로 읽어 모든 살아 있는 시도를 돌려준다. 그 목록을 그대로 끊으면
    force 삭제 한 번에 전 사용자의 진행 중 생성이 복구 불가가 된다.
    """
    pending = _attempt(db, sample_member.member_id, snapshot=None, state=AttemptState.PENDING)
    kb = _external(407, name="사내규정_2026")
    kb.created_at = None

    with _client(db, admin_member, [kb]) as client:
        res = client.delete(f"{ORPHANS}/407?force=true")

    assert res.status_code == 200
    assert res.json()["abandoned_attempts"] == 0
    db.refresh(pending)
    assert pending.state == AttemptState.PENDING


def test_delete_unprotected_orphan_succeeds(db, admin_member):
    upstream = [_external(407)]

    with _client(db, admin_member, upstream) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 200
    body = res.json()
    assert body["forced"] is False
    assert body["abandoned_attempts"] == 0


def test_delete_failure_leaves_kb_reclaimable(db, admin_member):
    """force 삭제가 업스트림에서 실패해도 자원이 갇히지는 않는다.

    끊긴 시도는 되살리지 않는다 — 삭제가 실제로 닿았는지 알 수 없어, 되살렸다가 사라진
    KB 에 매핑이 붙는 쪽이 더 나쁘다. 대신 KB 는 고아 목록에 그대로 남아 재삭제나 정리
    잡이 회수한다.
    """
    attempt = _attempt(db, admin_member.member_id, snapshot=[1, 2, 3])

    with _client(db, admin_member, upstream=[_external(407, name="사내규정_2026")],
                 deleted=False) as client:
        assert client.delete(f"{ORPHANS}/407?force=true").status_code == 404

    db.refresh(attempt)
    assert attempt.state == AttemptState.ABANDONED, "끊긴 시도는 되살리지 않는다"

    # 자원은 갇히지 않는다 — 여전히 고아로 보이고, 이제 force 없이 회수할 수 있다.
    with _client(db, admin_member, upstream=[_external(407, name="사내규정_2026")]) as client:
        item = client.get(ORPHANS).json()["data"][0]
        assert item["surro_knowledge_id"] == 407
        assert item["is_protected"] is False
        assert client.delete(f"{ORPHANS}/407").status_code == 200


def test_delete_refuses_empty_upstream(db, admin_member):
    with _client(db, admin_member, upstream=[]) as client:
        assert client.delete(f"{ORPHANS}/407").status_code == 503


def test_delete_returns_404_when_missing_upstream(db, admin_member):
    with _client(db, admin_member, upstream=[_external(100)]) as client:
        assert client.delete(f"{ORPHANS}/407").status_code == 404


def test_delete_returns_409_when_lock_is_contended(db, admin_member, monkeypatch):
    """관리자 삭제는 락 경합을 조용히 넘기지 않는다.

    복구처럼 건너뛰면 관리자는 200 과 함께 "지웠다" 는 응답을 받는데 KB 는 그대로 남는다.
    실패를 그대로 돌려주어 다시 시도하게 한다.
    """
    from app.cruds.knowledge_base import knowledge_base_crud

    monkeypatch.setattr(knowledge_base_crud, "try_lock_surro_knowledge_id", lambda *a, **k: False)
    delete_calls = []

    with _client(db, admin_member, upstream=[_external(407)],
                 delete_calls=delete_calls) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert delete_calls == [], "업스트림 DELETE 가 불리면 안 된다"
    assert db.query(AuditLog).filter(
        AuditLog.resource_id == "407"
    ).count() == 0, "삭제하지 않았으므로 감사 기록도 없어야 한다"


def test_delete_requires_admin(db, sample_member):
    with _client(db, sample_member, upstream=[_external(407)], admin=False) as client:
        assert client.delete(f"{ORPHANS}/407").status_code == 403
