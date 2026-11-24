"""advisory lock 의 실제 직렬화 동작 — PostgreSQL 이 있을 때만 돈다.

다른 KB 테스트는 SQLite 로 돈다. 그때 `try_lock_surro_knowledge_id` 는 락 SQL 을 실행하지
않고 곧바로 True 를 돌려주므로, 락이 조용히 no-op 이 되는 회귀를 구조적으로 잡지 못한다.
콜백 훅으로 재현하는 TOCTOU 도 단일 세션 안의 실행 순서일 뿐 동시성이 아니다.

이 파일은 엔진에 직결한 독립 세션 둘을 스레드로 병렬 실행해 실제 경합을 만든다. 공용 `db`
fixture 는 커넥션 하나·트랜잭션 하나를 라우트까지 공유하므로 여기서는 쓸 수 없다.

실행:
    TEST_DATABASE_URL=postgresql+psycopg2://postgres@127.0.0.1:55432/kbtest \\
        python -m pytest tests/test_knowledge_base_lock_concurrency.py
"""
import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from app.cruds.knowledge_base import knowledge_base_crud as crud
from app.models import AttemptState, KnowledgeBase, KnowledgeBaseCreateAttempt, Member
from app.routes.knowledge_base import _claim_candidate
from tests.conftest import _engine

pytestmark = pytest.mark.skipif(
    _engine.dialect.name != "postgresql",
    reason="advisory lock 은 PostgreSQL 에만 있다 — TEST_DATABASE_URL 을 지정해야 돈다",
)

SURRO = 990407
OTHER_SURRO = 990408
MEMBER_ID = "lock-concurrency-user"

# 스레드 조율용 대기 상한. 넘었다는 것은 조율이 깨졌다는 뜻이므로 단언으로 실패시킨다.
SYNC_TIMEOUT = 15.0
# 락을 쥔 채 상대가 시도해 보도록 붙잡아 두는 시간. 비대기 판정의 기준선이기도 하다.
HOLD_SECONDS = 2.0


def _purge(session):
    session.query(KnowledgeBase).filter(
        KnowledgeBase.surro_knowledge_id.in_([SURRO, OTHER_SURRO])
    ).delete(synchronize_session=False)
    session.query(KnowledgeBaseCreateAttempt).filter(
        KnowledgeBaseCreateAttempt.member_id == MEMBER_ID
    ).delete(synchronize_session=False)
    session.query(Member).filter(Member.member_id == MEMBER_ID).delete(
        synchronize_session=False
    )
    session.commit()


@pytest.fixture
def member():
    """FK 를 만족시킬 실제 커밋된 Member.

    이 파일의 테스트는 진짜로 커밋하므로 남긴 행을 직접 지워야 한다.
    """
    session = Session(bind=_engine)
    try:
        _purge(session)
        session.add(Member(
            name="락 동시성 테스터",
            member_id=MEMBER_ID,
            email=f"{MEMBER_ID}@example.com",
            password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
            role="user",
            is_active=True,
        ))
        session.commit()
        yield MEMBER_ID
    finally:
        _purge(session)
        session.close()


def _run(*workers):
    """워커들을 동시에 돌리고, 워커가 남긴 예외를 그대로 올린다.

    스레드 안의 실패는 기본적으로 조용히 묻히므로, 모아서 다시 던지지 않으면 테스트가
    통과한 것처럼 보인다.
    """
    errors = []

    def guard(fn):
        def wrapped():
            try:
                fn()
            except BaseException as exc:      # noqa: BLE001 - 스레드 경계에서 전부 잡아 올린다
                errors.append(exc)
        return wrapped

    threads = [threading.Thread(target=guard(w)) for w in workers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=SYNC_TIMEOUT * 2)
        assert not t.is_alive(), "워커가 끝나지 않았다 — 락 대기로 멈춰 있을 수 있다"
    if errors:
        raise errors[0]


def test_second_transaction_cannot_take_a_held_lock(member):
    """한 트랜잭션이 쥔 락을 다른 트랜잭션은 얻지 못한다.

    이 파일이 없으면 락이 실제로 직렬화하는지는 한 번도 확인되지 않는다 — SQLite 실행에서는
    락 SQL 자체가 나가지 않는다.
    """
    a_locked = threading.Event()
    b_probed = threading.Event()
    seen = {}

    def worker_a():
        session = Session(bind=_engine)
        try:
            assert crud.try_lock_surro_knowledge_id(session, SURRO) is True
            a_locked.set()
            assert b_probed.wait(SYNC_TIMEOUT), "B 가 시도하지 못했다"
        finally:
            session.rollback()
            session.close()

    def worker_b():
        session = Session(bind=_engine)
        try:
            assert a_locked.wait(SYNC_TIMEOUT), "A 가 락을 잡지 못했다"
            seen["while_held"] = crud.try_lock_surro_knowledge_id(session, SURRO)
            b_probed.set()
        finally:
            session.rollback()
            session.close()

    _run(worker_a, worker_b)

    assert seen["while_held"] is False, "같은 id 의 락이 동시에 두 트랜잭션에 잡혔다"


def test_try_lock_returns_immediately_while_held(member):
    """락이 잡혀 있어도 기다리지 않고 즉시 돌아온다.

    대기형이면 여기서 A 가 락을 놓을 때까지 멈춘다. 이 라우트들은 async 인데 세션이 동기라,
    그 대기가 이벤트 루프를 통째로 막아 A 의 업스트림 응답을 이어받을 주체가 사라진다.
    """
    a_locked = threading.Event()
    b_probed = threading.Event()
    seen = {}

    def worker_a():
        session = Session(bind=_engine)
        try:
            assert crud.try_lock_surro_knowledge_id(session, SURRO) is True
            a_locked.set()
            # B 가 시도를 마칠 때까지 쥐고 있는다. 락이 대기형이면 B 는 이 대기가 끝나야
            # 돌아오므로, B 가 잰 시간이 HOLD_SECONDS 근처로 올라간다.
            b_probed.wait(HOLD_SECONDS)
        finally:
            session.rollback()
            session.close()

    def worker_b():
        session = Session(bind=_engine)
        try:
            assert a_locked.wait(SYNC_TIMEOUT), "A 가 락을 잡지 못했다"
            started = time.monotonic()
            seen["result"] = crud.try_lock_surro_knowledge_id(session, SURRO)
            seen["elapsed"] = time.monotonic() - started
            b_probed.set()
        finally:
            session.rollback()
            session.close()

    _run(worker_a, worker_b)

    assert seen["result"] is False
    assert seen["elapsed"] < HOLD_SECONDS / 2, (
        f"락을 기다렸다 — {seen['elapsed']:.3f}s 만에 돌아왔어야 할 자리에서 멈췄다"
    )


def test_commit_releases_the_lock_and_publishes_the_mapping(member):
    """A 의 commit 이 락을 풀고, 그 뒤 락을 잡은 B 는 A 가 만든 매핑을 본다.

    두 번째 절반이 중요하다. B 의 트랜잭션은 A 가 커밋하기 **전에** 이미 시작돼 있다 —
    실제 복구 경로도 목록을 읽어 트랜잭션을 연 뒤에야 락을 잡는다. 격리 수준이 READ COMMITTED
    보다 높으면 B 의 재확인이 트랜잭션 시작 시점의 스냅샷을 읽어, 예외 없이 조용히 무력화된다.
    """
    b_opened = threading.Event()
    a_committed = threading.Event()
    seen = {}

    def worker_a():
        session = Session(bind=_engine)
        try:
            assert b_opened.wait(SYNC_TIMEOUT), "B 가 트랜잭션을 열지 못했다"
            assert crud.try_lock_surro_knowledge_id(session, SURRO) is True
            crud.create_knowledge_base(           # 내부 commit 이 락을 푼다
                db=session, name="락 테스트 KB", description=None,
                created_by=member, surro_knowledge_id=SURRO,
                collection_name=f"col_{SURRO}",
            )
            a_committed.set()
        finally:
            session.rollback()
            session.close()

    def worker_b():
        session = Session(bind=_engine)
        try:
            # 먼저 읽어 트랜잭션을 연다 — A 의 커밋보다 앞선 시점이다.
            seen["before"] = crud.get_active_knowledge_base_by_surro_id(session, SURRO)
            b_opened.set()
            assert a_committed.wait(SYNC_TIMEOUT), "A 가 커밋하지 못했다"
            seen["lock_after_commit"] = crud.try_lock_surro_knowledge_id(session, SURRO)
            row = crud.get_active_knowledge_base_by_surro_id(session, SURRO)
            seen["after"] = None if row is None else row.created_by
        finally:
            session.rollback()
            session.close()

    _run(worker_a, worker_b)

    assert seen["before"] is None
    assert seen["lock_after_commit"] is True, "commit 이 트랜잭션 범위 락을 풀지 못했다"
    assert seen["after"] == member, "락 안의 재확인이 다른 세션의 커밋을 보지 못했다"


def test_rollback_releases_the_lock(member):
    """rollback 도 트랜잭션 범위 락을 푼다 — 예외 경로에서 락이 남으면 안 된다."""
    a_rolled_back = threading.Event()
    seen = {}

    def worker_a():
        session = Session(bind=_engine)
        try:
            assert crud.try_lock_surro_knowledge_id(session, SURRO) is True
            session.rollback()
            a_rolled_back.set()
        finally:
            session.close()

    def worker_b():
        session = Session(bind=_engine)
        try:
            assert a_rolled_back.wait(SYNC_TIMEOUT), "A 가 롤백하지 못했다"
            seen["result"] = crud.try_lock_surro_knowledge_id(session, SURRO)
        finally:
            session.rollback()
            session.close()

    _run(worker_a, worker_b)

    assert seen["result"] is True


def test_locks_on_different_ids_do_not_block_each_other(member):
    """서로 다른 KB 의 락은 간섭하지 않는다 — 한 KB 의 복구가 다른 KB 를 멈춰 세우면 안 된다."""
    a_locked = threading.Event()
    b_probed = threading.Event()
    seen = {}

    def worker_a():
        session = Session(bind=_engine)
        try:
            assert crud.try_lock_surro_knowledge_id(session, SURRO) is True
            a_locked.set()
            assert b_probed.wait(SYNC_TIMEOUT), "B 가 시도하지 못했다"
        finally:
            session.rollback()
            session.close()

    def worker_b():
        session = Session(bind=_engine)
        try:
            assert a_locked.wait(SYNC_TIMEOUT), "A 가 락을 잡지 못했다"
            seen["other_id"] = crud.try_lock_surro_knowledge_id(session, OTHER_SURRO)
            b_probed.set()
        finally:
            session.rollback()
            session.close()

    _run(worker_a, worker_b)

    assert seen["other_id"] is True


def test_event_loop_stays_responsive_while_another_transaction_holds_the_lock(member):
    """락이 잡혀 있는 동안에도 이벤트 루프가 멈추지 않는다.

    라우트는 async 인데 세션은 동기 드라이버다. 대기하는 락을 async 핸들러 안에서 부르면
    루프 스레드가 통째로 멈춰, 같은 루프에 걸린 다른 콜백이 전부 밀린다. 그 콜백 중에는
    락을 쥔 요청의 업스트림 응답 처리도 들어 있어, 서로를 풀어 줄 주체가 사라진다.

    락 획득 결과만 보는 테스트로는 이 증상이 드러나지 않는다 — 루프가 실제로 밀렸는지는
    주기적으로 깨어나는 콜백의 지연으로만 관찰된다.
    """
    import asyncio

    a_locked = threading.Event()
    release = threading.Event()

    def holder():
        session = Session(bind=_engine)
        try:
            assert crud.try_lock_surro_knowledge_id(session, SURRO) is True
            a_locked.set()
            # 프로브가 끝나기를 기다리지 않고 시간으로 쥔다. 대기형 락이라면 프로브가
            # 이 시간만큼 루프를 막으므로, 지연이 그대로 드러난다.
            release.wait(HOLD_SECONDS)
        finally:
            session.rollback()
            session.close()

    thread = threading.Thread(target=holder)
    thread.start()
    try:
        assert a_locked.wait(SYNC_TIMEOUT), "락을 쥐는 스레드가 시작되지 못했다"

        async def scenario():
            gaps = []

            async def heartbeat():
                last = time.monotonic()
                while True:
                    await asyncio.sleep(0.05)
                    now = time.monotonic()
                    gaps.append(now - last)
                    last = now

            beat = asyncio.create_task(heartbeat())
            await asyncio.sleep(0.15)          # 평소 간격을 먼저 몇 번 쌓는다

            # async 핸들러가 동기 세션으로 락을 잡는 실제 모양.
            session = Session(bind=_engine)
            try:
                acquired = crud.try_lock_surro_knowledge_id(session, SURRO)
            finally:
                session.rollback()
                session.close()

            await asyncio.sleep(0.15)
            beat.cancel()
            return acquired, max(gaps)

        acquired, worst_gap = asyncio.run(scenario())
    finally:
        release.set()
        thread.join(timeout=SYNC_TIMEOUT)

    assert acquired is False, "락이 잡혀 있는데 획득했다"
    assert worst_gap < HOLD_SECONDS / 4, (
        f"락 획득이 이벤트 루프를 {worst_gap:.3f}s 멈춰 세웠다 — 50ms 주기 콜백이 그만큼 밀렸다"
    )


def test_skipped_candidate_keeps_the_lock_until_the_caller_ends_the_transaction(member):
    """락을 잡은 뒤 건너뛰는 분기도 결국 락을 풀어야 한다.

    목록을 읽은 뒤 락을 잡기 전에 다른 요청이 먼저 복구를 끝내면, 락을 잡은 뒤 상태를 다시 읽고
    물러난다. `_claim_candidate` 자체는 트랜잭션을 닫지 않으므로 그 시점까지 락이 남아 있고,
    닫는 책임은 호출자에게 있다. 호출자가 닫지 않으면 락이 요청 끝까지 유지되어 그동안 같은
    KB 에 대한 관리자 삭제가 막힌다.
    """
    now = datetime.now(timezone.utc)
    setup = Session(bind=_engine)
    try:
        # 다른 요청이 이미 복구를 끝낸 상태 — 락 안의 재확인이 물러나야 하는 경우.
        attempt = KnowledgeBaseCreateAttempt(
            member_id=member, name="락 테스트 KB", filename="f.pdf",
            request_id="skip-1", upstream_snapshot=[1, 2],
            state=AttemptState.RECOVERED, started_at=now - timedelta(minutes=5),
        )
        setup.add(attempt)
        setup.commit()
        attempt_id = attempt.id
    finally:
        setup.close()

    candidate = SimpleNamespace(
        id=SURRO, name="락 테스트 KB", description=None, collection_name=f"col_{SURRO}"
    )

    worker = Session(bind=_engine)
    probe = Session(bind=_engine)
    try:
        claimed = _claim_candidate(
            worker, worker.get(KnowledgeBaseCreateAttempt, attempt_id), candidate
        )
        assert claimed is False, "복구가 끝난 시도로 매핑을 만들면 안 된다"

        assert crud.try_lock_surro_knowledge_id(probe, SURRO) is False,             "건너뛴 시점에는 아직 락을 쥐고 있어야 한다 — 이 테스트의 전제"
        probe.rollback()

        worker.commit()                    # 호출자가 하는 일
        assert crud.try_lock_surro_knowledge_id(probe, SURRO) is True,             "건너뛰기 분기가 락을 놓지 못했다 — 요청이 끝날 때까지 다른 복구가 막힌다"
    finally:
        probe.rollback()
        probe.close()
        worker.rollback()
        worker.close()

    check = Session(bind=_engine)
    try:
        assert check.query(KnowledgeBase).filter(
            KnowledgeBase.surro_knowledge_id == SURRO
        ).count() == 0
    finally:
        check.close()


def test_only_one_of_two_racing_claims_creates_a_mapping(member):
    """같은 KB 를 노리는 복구 두 건이 동시에 들어와도 매핑은 하나만 생긴다.

    둘 다 성공하면 같은 업스트림 KB 를 가리키는 매핑이 두 개가 되어, 소유자가 둘로 갈린다.
    """
    now = datetime.now(timezone.utc)
    setup = Session(bind=_engine)
    try:
        attempts = []
        for i in range(2):
            a = KnowledgeBaseCreateAttempt(
                member_id=member, name="락 테스트 KB", filename="f.pdf",
                request_id=f"race-{i}", upstream_snapshot=[1, 2],
                state=AttemptState.ORPHAN_SUSPECT, started_at=now - timedelta(minutes=5),
            )
            setup.add(a)
            attempts.append(a)
        setup.commit()
        attempt_ids = [a.id for a in attempts]
    finally:
        setup.close()

    candidate = SimpleNamespace(
        id=SURRO, name="락 테스트 KB", description=None, collection_name=f"col_{SURRO}"
    )
    start = threading.Barrier(2, timeout=SYNC_TIMEOUT)
    claimed = []

    def worker(attempt_id):
        def run():
            session = Session(bind=_engine)
            try:
                attempt = session.get(KnowledgeBaseCreateAttempt, attempt_id)
                start.wait()
                claimed.append(_claim_candidate(session, attempt, candidate))
            finally:
                session.rollback()
                session.close()
        return run

    _run(worker(attempt_ids[0]), worker(attempt_ids[1]))

    check = Session(bind=_engine)
    try:
        rows = check.query(KnowledgeBase).filter(
            KnowledgeBase.surro_knowledge_id == SURRO
        ).all()
    finally:
        check.close()

    assert sorted(claimed) == [False, True], f"정확히 하나만 성공해야 한다: {claimed}"
    assert len(rows) == 1, "같은 업스트림 KB 를 가리키는 매핑이 둘 생겼다"
    assert rows[0].created_by == member
