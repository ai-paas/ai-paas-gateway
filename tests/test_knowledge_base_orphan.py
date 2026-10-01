"""고아 Knowledge Base 관리자 라우트.

고아만 노출 / active 매핑 미노출 / 매핑 있는 id 삭제 거부 /
보호 대상 409·force 시 삭제 + 시도 abandoned /
토큰 없는 KB 는 살아 있는 시도가 있어도 보호되지 않음.
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.common.kb_attempt_token import attach_token, make_token
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


def _external(kb_id, name="kb", created_at=None, token_for=None):
    return ExternalKnowledgeBaseBriefResponse(
        id=kb_id,
        name=name,
        description=(attach_token(None, make_token(token_for.id, token_for.request_id))
                     if token_for is not None else None),
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


def _attempt(db, member_id, snapshot=None, started_at=T0, state=AttemptState.ORPHAN_SUSPECT,
             request_id="req-1"):
    a = KnowledgeBaseCreateAttempt(
        member_id=member_id,
        name="사내규정_2026",
        filename="규정.pdf",
        request_id=request_id,
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
    attempt = _attempt(db, admin_member.member_id)
    upstream = [_external(407, token_for=attempt)]

    with _client(db, admin_member, upstream) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is True, "살아 있는 시도의 토큰을 가진 KB 는 복구 대기로 표시돼야 한다"
    assert admin_member.member_id in item["protected_by"]


def test_list_orphans_marks_pending_create_as_protected(db, admin_member, sample_member):
    """생성이 진행 중인 KB 는 업스트림에 이미 보이지만 매핑은 아직 없다 — 고아가 아니다."""
    attempt = _attempt(db, sample_member.member_id, state=AttemptState.PENDING)

    with _client(db, admin_member, upstream=[_external(407, token_for=attempt)]) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is True
    assert sample_member.member_id in item["protected_by"]


def test_list_orphans_protects_every_kb_carrying_a_live_token(db, admin_member, sample_member):
    """같은 토큰을 가진 KB 가 둘이면(업스트림에서 description 복사) 둘 다 보호한다 — 어느 쪽이 진짜인지 모른다."""
    attempt = _attempt(db, sample_member.member_id, state=AttemptState.PENDING)
    upstream = [_external(407, token_for=attempt), _external(408, token_for=attempt)]

    with _client(db, admin_member, upstream) as client:
        items = client.get(ORPHANS).json()["data"]

    assert [i["is_protected"] for i in items] == [True, True]


def test_list_orphans_protects_tokened_kb_with_unknown_created_at(db, admin_member, sample_member):
    """업스트림이 created_at 을 주지 않아도 토큰이 주인을 알려 준다 — 보호 판정에 시각은 필요 없다."""
    attempt = _attempt(db, sample_member.member_id, state=AttemptState.PENDING)
    kb = _external(407, token_for=attempt)
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
    """생성 시각을 모르는 KB 라도 진행 중인 시도의 토큰을 가졌으면 force 없이 지울 수 없다."""
    attempt = _attempt(db, sample_member.member_id, state=AttemptState.PENDING)
    kb = _external(407, token_for=attempt)
    kb.created_at = None
    delete_calls = []

    with _client(db, admin_member, upstream=[kb], delete_calls=delete_calls) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert delete_calls == [], "업스트림 DELETE 가 불리면 안 된다"


def test_list_orphans_does_not_protect_kb_without_token(db, admin_member, sample_member):
    """토큰 없는 KB 는 살아 있는 시도가 있어도 보호되지 않는다.

    어떤 시도도 그 KB 를 복구할 수 없으므로, 보호하면 복구되지도 않으면서 삭제만 막힌다.
    """
    _attempt(db, sample_member.member_id, state=AttemptState.PENDING)

    with _client(db, admin_member, [_external(407)]) as client:
        item = client.get(ORPHANS).json()["data"][0]

    assert item["is_protected"] is False
    assert item["protected_by"] is None


def test_list_orphans_does_not_protect_kb_whose_attempt_has_ended(db, admin_member):
    """토큰의 주인 시도가 끝났으면(포기·TTL 경과) 보호하지 않는다 — 더는 가져갈 시도가 없다."""
    abandoned = _attempt(db, admin_member.member_id, state=AttemptState.ABANDONED,
                         request_id="req-abandoned")
    expired = _attempt(db, admin_member.member_id, request_id="req-expired",
                       started_at=NOW - timedelta(minutes=settings.KB_ATTEMPT_TTL_MINUTES + 1))
    upstream = [_external(407, token_for=abandoned), _external(408, token_for=expired)]

    with _client(db, admin_member, upstream) as client:
        items = client.get(ORPHANS).json()["data"]

    assert [i["is_protected"] for i in items] == [False, False]


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
    attempt = _attempt(db, admin_member.member_id)
    upstream = [_external(407, token_for=attempt)]

    with _client(db, admin_member, upstream) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert "force" in res.json()["detail"]


def test_delete_protected_with_force_abandons_attempt(db, admin_member):
    attempt = _attempt(db, admin_member.member_id)
    upstream = [_external(407, name="사내규정_2026", token_for=attempt)]

    with _client(db, admin_member, upstream) as client:
        res = client.delete(f"{ORPHANS}/407?force=true")

    assert res.status_code == 200
    body = res.json()
    assert body["forced"] is True
    assert body["abandoned_attempts"] == 1

    db.refresh(attempt)
    assert attempt.state == AttemptState.ABANDONED, (
        "붙을 대상이 사라진 시도를 남기면 ATTEMPT_TTL 동안 복구를 기다린다"
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
    attempt = _attempt(db, sample_member.member_id)
    delete_calls = []

    def recovery_finishes_first():
        _mapping(db, sample_member.member_id, surro_id=407)
        attempt.state = AttemptState.RECOVERED
        db.flush()

    with _client(db, admin_member, upstream=[_external(407, token_for=attempt)],
                 on_list=recovery_finishes_first, delete_calls=delete_calls) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert delete_calls == [], "업스트림 DELETE 가 불리면 안 된다"


def test_delete_rejects_while_create_is_pending(db, admin_member, sample_member):
    """생성이 진행 중인 KB 는 force 없이 지울 수 없다.

    지워 버리면 생성 라우트는 그대로 매핑을 써서, 업스트림에 없는 KB 카드가 사용자 목록에 남는다.
    """
    attempt = _attempt(db, sample_member.member_id, state=AttemptState.PENDING)
    delete_calls = []

    with _client(db, admin_member, upstream=[_external(407, token_for=attempt)],
                 delete_calls=delete_calls) as client:
        res = client.delete(f"{ORPHANS}/407")

    assert res.status_code == 409
    assert delete_calls == []


def test_delete_abandons_protectors_before_calling_upstream(db, admin_member):
    """force 삭제는 업스트림 DELETE 보다 먼저 시도를 끊어야 한다.

    이 순서라야 락을 놓은 뒤에도 진행 중인 복구가 사라진 KB 에 매핑을 붙이지 못한다.
    """
    attempt = _attempt(db, admin_member.member_id)
    states_at_delete = []

    def fake_delete_recording_state(knowledge_base_id, user_info=None):
        db.refresh(attempt)
        states_at_delete.append(attempt.state)

    with _client(db, admin_member, upstream=[_external(407, name="사내규정_2026", token_for=attempt)]) as client:
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


def test_force_delete_cuts_only_the_kbs_own_attempt_before_deleting(db, admin_member, sample_member):
    """force 삭제는 이 KB 의 토큰을 가진 시도만, 업스트림 DELETE 전에 끊는다.

    DELETE 는 락 밖에서 일어나므로 안전성은 선점이 보장한다 — 락 안에서 주인 시도를 끊어 커밋한
    뒤에 DELETE 를 부른다. 토큰이 주인을 특정하므로 같은 시각에 진행 중인 무관한 생성은 건드리지
    않는다. 시간 창으로 끊으면 그 사용자의 자동 복구까지 함께 사라진다.
    """
    owner = _attempt(db, sample_member.member_id, request_id="req-owner")
    bystander = _attempt(db, sample_member.member_id, state=AttemptState.PENDING,
                         request_id="req-bystander")
    states_at_delete = []

    def inspect(_kb_id):
        db.refresh(owner)
        db.refresh(bystander)
        states_at_delete.append((owner.state, bystander.state))

    with _client(db, admin_member, upstream=[_external(407, token_for=owner)],
                 on_delete=inspect) as client:
        res = client.delete(f"{ORPHANS}/407?force=true")

    assert res.status_code == 200
    assert res.json()["abandoned_attempts"] == 1
    assert states_at_delete == [(AttemptState.ABANDONED, AttemptState.PENDING)]


def test_attempt_started_during_upstream_delete_cannot_claim_the_kb(db, admin_member, sample_member):
    """DELETE 를 await 하는 사이에 시작된 생성 시도는 이 KB 를 가져갈 수 없다.

    선점이 성립하려면 끊어 놓은 뒤로 후보가 다시 생기지 않아야 한다. 새 시도의 토큰은 이 KB 에
    실려 있지 않으므로 후보가 될 수 없다.
    """
    from app.cruds.knowledge_base import knowledge_base_crud

    owner = _attempt(db, sample_member.member_id, request_id="req-owner")
    kb = _external(407, token_for=owner)
    claimants_after_new_attempt = []

    def start_new_attempt(_kb_id):
        _attempt(db, sample_member.member_id, started_at=datetime.now(timezone.utc),
                 state=AttemptState.PENDING, request_id="req-new")
        live = knowledge_base_crud.get_live_attempts(db, datetime.now(timezone.utc))
        claimants_after_new_attempt.append(knowledge_base_crud.find_protecting_attempts(kb, live))

    with _client(db, admin_member, upstream=[kb], on_delete=start_new_attempt) as client:
        res = client.delete(f"{ORPHANS}/407?force=true")

    assert res.status_code == 200
    assert claimants_after_new_attempt == [[]], "뒤늦게 시작한 시도가 후보가 되면 선점이 무의미하다"


def test_force_delete_of_kb_without_created_at_cuts_only_its_token_owner(db, admin_member, sample_member):
    """created_at 없는 KB 도 토큰의 주인 시도는 끊고, 무관한 시도는 남긴다.

    토큰 복구는 시각을 보지 않는다. 주인 시도를 남겨 두면 락 밖 DELETE 를 기다리는 사이에
    복구가 이 KB 에 매핑을 붙일 수 있다. 반대로 판정 결측을 이유로 전부 끊으면 무관한 생성의
    복구 기회가 영구히 사라진다.
    """
    owner = _attempt(db, sample_member.member_id, request_id="req-owner")
    bystander = _attempt(db, sample_member.member_id, state=AttemptState.PENDING,
                         request_id="req-bystander")
    kb = _external(407, token_for=owner)
    kb.created_at = None

    with _client(db, admin_member, [kb]) as client:
        res = client.delete(f"{ORPHANS}/407?force=true")

    assert res.status_code == 200
    assert res.json()["abandoned_attempts"] == 1
    db.refresh(owner)
    db.refresh(bystander)
    assert owner.state == AttemptState.ABANDONED
    assert bystander.state == AttemptState.PENDING


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
    attempt = _attempt(db, admin_member.member_id)

    with _client(db, admin_member, upstream=[_external(407, name="사내규정_2026", token_for=attempt)],
                 deleted=False) as client:
        assert client.delete(f"{ORPHANS}/407?force=true").status_code == 404

    db.refresh(attempt)
    assert attempt.state == AttemptState.ABANDONED, "끊긴 시도는 되살리지 않는다"

    # 자원은 갇히지 않는다 — 여전히 고아로 보이고, 이제 force 없이 회수할 수 있다.
    with _client(db, admin_member, upstream=[_external(407, name="사내규정_2026", token_for=attempt)]) as client:
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
