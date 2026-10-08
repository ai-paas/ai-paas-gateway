"""개인 대시보드 확장(서비스 카드/모니터링/활동 히스토리) 테스트.

전략:
- `_fetch_one`: 순수 async — fake client(SimpleNamespace)로 getattr 접근 검증.
- serve/build: 스냅샷을 db.add+flush(커밋 없이) seed → 트랜잭션 롤백으로 격리.
- 커밋 경로(_upsert/refresh/route live): `db.commit`을 no-op으로 monkeypatch해
  실제 SQL(delete+insert/query)은 돌리되 커밋만 막아 격리.
- 라우트: TestClient + get_db/get_current_user override (test_service_detail.py 패턴).
- MLOps는 싱글톤 메서드 monkeypatch (httpx 미사용).
"""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models import Member
from app.models.audit_log import AuditLog
from app.models.dashboard_cache import ServiceCardSnapshot, ServiceMetricSnapshot
from app.models.service import Service
from app.services import me_dashboard_service
from tests.conftest import _engine


# ============================================================
# fakes / helpers
# ============================================================

def _pm(**kw):
    """MLOps PeriodMetrics 유사 객체."""
    base = dict(message_count=0, active_users=0, token_usage=0, avg_interaction_count=0.0,
                response_time_ms=None, error_count=0, success_rate=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _svc_detail(workflow_ids, *, agg_at=None, m1h=None, m1d=None, m1w=None, with_monitoring=True):
    workflows = [SimpleNamespace(id=w) for w in workflow_ids]
    md = None
    if with_monitoring:
        md = SimpleNamespace(
            aggregated_at=agg_at,
            total_metrics=SimpleNamespace(
                period_1h=m1h or _pm(), period_1d=m1d or _pm(), period_1w=m1w or _pm()
            ),
        )
    return SimpleNamespace(workflows=workflows, monitoring_data=md)


class FakeSvcClient:
    def __init__(self, mapping):
        self.mapping = mapping

    async def get_service(self, surro_id, user_info):
        return self.mapping.get(surro_id)


class FakeWfClient:
    def __init__(self, mapping):
        self.mapping = mapping

    async def get_workflow(self, wf_id, user_info):
        return self.mapping.get(wf_id)


def _run(coro):
    return asyncio.run(coro)


def _make_service(db, member_id, surro_id, name, description=None):
    s = Service(name=name, description=description, created_by=member_id, surro_service_id=surro_id)
    db.add(s)
    db.flush()
    return s


def _seed_card(db, surro_id, *, workflow_count=0, model_count=None, age_minutes=0):
    db.add(ServiceCardSnapshot(
        surro_service_id=surro_id, workflow_count=workflow_count, model_count=model_count,
        refreshed_at=datetime.utcnow() - timedelta(minutes=age_minutes),
    ))
    db.flush()


def _seed_metric(db, surro_id, period, *, message_count=0, active_users=0, token_usage=0,
                 avg_interaction_count=0.0, age_minutes=0):
    db.add(ServiceMetricSnapshot(
        surro_service_id=surro_id, period=period,
        message_count=message_count, active_users=active_users, token_usage=token_usage,
        avg_interaction_count=avg_interaction_count, error_count=0,
        refreshed_at=datetime.utcnow() - timedelta(minutes=age_minutes),
    ))
    db.flush()


def _seed_all_periods(db, surro_id, *, message_count=0, age_minutes=0):
    for p in ("1h", "1d", "1w"):
        _seed_metric(db, surro_id, p, message_count=message_count, age_minutes=age_minutes)


@contextmanager
def _client(db, current_user):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: current_user
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.clear()


# ============================================================
# _fetch_one (순수 async)
# ============================================================

def test_fetch_one_extracts_counts_and_metrics():
    svc = FakeSvcClient({"s1": _svc_detail(
        ["wf1", "wf2"], agg_at=datetime(2026, 6, 1, 12, 0, 0),
        m1h=_pm(message_count=100, active_users=5, token_usage=1000, avg_interaction_count=2.5),
        m1d=_pm(message_count=900), m1w=_pm(message_count=5000),
    )})
    wf = FakeWfClient({
        "wf1": SimpleNamespace(components=[SimpleNamespace(model_id=1), SimpleNamespace(model_id=2)]),
        "wf2": SimpleNamespace(components=[SimpleNamespace(model_id=2), SimpleNamespace(model_id=None)]),
    })
    res = _run(me_dashboard_service._fetch_one("s1", {"member_id": "u1"}, True, svc, wf, asyncio.Semaphore(8)))

    assert res["workflow_count"] == 2
    assert res["model_count"] == 2  # distinct {1, 2}
    assert res["metrics"]["1h"]["message_count"] == 100
    assert res["metrics"]["1h"]["avg_interaction_count"] == 2.5
    assert res["metrics"]["1d"]["message_count"] == 900
    assert res["metrics"]["1w"]["message_count"] == 5000
    assert res["aggregated_at"] == datetime(2026, 6, 1, 12, 0, 0)


def test_fetch_one_no_monitoring_data_yields_zeros():
    svc = FakeSvcClient({"s1": _svc_detail(["wf1"], with_monitoring=False)})
    res = _run(me_dashboard_service._fetch_one("s1", {"member_id": "u1"}, False, svc, FakeWfClient({}), asyncio.Semaphore(8)))
    assert res["workflow_count"] == 1
    assert res["model_count"] is None  # include_model_count=False
    assert res["metrics"]["1h"]["message_count"] == 0
    assert res["metrics"]["1w"]["success_rate"] is None


def test_fetch_one_model_count_none_when_all_workflows_fail():
    svc = FakeSvcClient({"s1": _svc_detail(["wf1"])})
    res = _run(me_dashboard_service._fetch_one("s1", {"member_id": "u1"}, True, svc, FakeWfClient({}), asyncio.Semaphore(8)))
    assert res["model_count"] is None  # wf1 detail 미수신 → 신뢰 불가


def test_fetch_one_returns_none_when_service_missing():
    res = _run(me_dashboard_service._fetch_one("nope", {"member_id": "u1"}, True, FakeSvcClient({}), FakeWfClient({}), asyncio.Semaphore(8)))
    assert res is None


# ============================================================
# build_cards_response / build_monitoring_response (flush-only seed)
# ============================================================

def test_build_cards_response_merges_db_and_cache(db, sample_member):
    _make_service(db, sample_member.member_id, "s1", "svc one", "desc one")
    _make_service(db, sample_member.member_id, "s2", "svc two")
    _seed_card(db, "s1", workflow_count=24, model_count=15)
    _seed_card(db, "s2", workflow_count=3, model_count=None)

    resp = me_dashboard_service.build_cards_response(db, sample_member.member_id, source="cache")
    assert resp.source == "cache"
    cards = {c.surro_service_id: c for c in resp.services}
    assert cards["s1"].name == "svc one"
    assert cards["s1"].description == "desc one"
    assert cards["s1"].workflow_count == 24
    assert cards["s1"].model_count == 15
    assert cards["s2"].workflow_count == 3
    assert cards["s2"].model_count is None


def test_build_cards_response_missing_snapshot_defaults_zero(db, sample_member):
    _make_service(db, sample_member.member_id, "s1", "svc one")
    resp = me_dashboard_service.build_cards_response(db, sample_member.member_id, source="cache")
    assert resp.services[0].workflow_count == 0
    assert resp.services[0].model_count is None


def test_build_cards_response_empty_when_no_services(db, sample_member):
    resp = me_dashboard_service.build_cards_response(db, sample_member.member_id, source="cache")
    assert resp.source == "empty"
    assert resp.services == []


def test_build_cards_response_scoped_to_owner(db, sample_member, admin_member):
    _make_service(db, sample_member.member_id, "s1", "mine")
    _make_service(db, admin_member.member_id, "s2", "theirs")
    resp = me_dashboard_service.build_cards_response(db, sample_member.member_id, source="cache")
    ids = {c.surro_service_id for c in resp.services}
    assert ids == {"s1"}


def test_build_monitoring_response_all_periods_and_top_ordering(db, sample_member):
    _make_service(db, sample_member.member_id, "low", "low svc")
    _make_service(db, sample_member.member_id, "high", "high svc")
    _make_service(db, sample_member.member_id, "mid", "mid svc")
    for sid, mc in (("low", 10), ("high", 5000), ("mid", 500)):
        _seed_metric(db, sid, "1h", message_count=mc)
        _seed_metric(db, sid, "1d", message_count=mc * 2)
        _seed_metric(db, sid, "1w", message_count=mc * 3)

    resp = me_dashboard_service.build_monitoring_response(db, sample_member.member_id, top_n=5, source="cache")

    # 모든 기간 존재 + 서비스별 metrics 채움
    assert set(resp.top.keys()) == {"1h", "1d", "1w"}
    by_service = {s.surro_service_id: s for s in resp.services}
    assert set(by_service["high"].metrics.keys()) == {"1h", "1d", "1w"}
    assert by_service["high"].metrics["1d"].message_count == 10000

    # Top 메시지 순위: high > mid > low (1h 기준)
    ranked_1h = [r.surro_service_id for r in resp.top["1h"].message_count]
    assert ranked_1h == ["high", "mid", "low"]
    # 1d 기준에서도 동일 순위, 값은 2배
    assert resp.top["1d"].message_count[0].surro_service_id == "high"
    assert resp.top["1d"].message_count[0].value == 10000.0


def test_build_monitoring_response_top_n_limits(db, sample_member):
    for i in range(4):
        _make_service(db, sample_member.member_id, f"s{i}", f"svc {i}")
        _seed_all_periods(db, f"s{i}", message_count=i * 100)
    resp = me_dashboard_service.build_monitoring_response(db, sample_member.member_id, top_n=2, source="cache")
    assert len(resp.top["1h"].message_count) == 2  # top_n=2 상한
    assert resp.top_n == 2


def test_build_monitoring_response_empty(db, sample_member):
    resp = me_dashboard_service.build_monitoring_response(db, sample_member.member_id, source="cache")
    assert resp.source == "empty"
    assert resp.services == []
    assert resp.top == {}


# ============================================================
# need_refresh (TTL)
# ============================================================

def test_cards_need_refresh_missing_and_stale(db, sample_member, monkeypatch):
    monkeypatch.setattr("app.config.settings.DASHBOARD_CACHE_TTL_MINUTES", 10, raising=False)
    _seed_card(db, "fresh", workflow_count=1, age_minutes=1)
    _seed_card(db, "stale", workflow_count=1, age_minutes=120)

    assert me_dashboard_service.cards_need_refresh(db, ["fresh"]) is False
    assert me_dashboard_service.cards_need_refresh(db, ["stale"]) is True
    assert me_dashboard_service.cards_need_refresh(db, ["missing"]) is True
    assert me_dashboard_service.cards_need_refresh(db, ["fresh", "missing"]) is True


def test_metrics_need_refresh_requires_all_periods(db, sample_member, monkeypatch):
    monkeypatch.setattr("app.config.settings.DASHBOARD_CACHE_TTL_MINUTES", 10, raising=False)
    _seed_all_periods(db, "full", age_minutes=1)
    _seed_metric(db, "partial", "1h", age_minutes=1)  # 1d/1w 누락

    assert me_dashboard_service.metrics_need_refresh(db, ["full"]) is False
    assert me_dashboard_service.metrics_need_refresh(db, ["partial"]) is True


def test_ttl_zero_means_never_stale(db, monkeypatch):
    monkeypatch.setattr("app.config.settings.DASHBOARD_CACHE_TTL_MINUTES", 0, raising=False)
    _seed_card(db, "old", workflow_count=1, age_minutes=99999)
    assert me_dashboard_service.cards_need_refresh(db, ["old"]) is False


# ============================================================
# _upsert_snapshots + refresh (commit no-op로 격리)
# ============================================================

def _fetched(surro_id, *, workflow_count=0, model_count=None, m1h=None):
    metrics = {p: me_dashboard_service._period_metrics_to_dict(None) for p in ("1h", "1d", "1w")}
    if m1h is not None:
        metrics["1h"] = me_dashboard_service._period_metrics_to_dict(_pm(**m1h))
    return {"surro_service_id": surro_id, "workflow_count": workflow_count,
            "model_count": model_count, "metrics": metrics, "aggregated_at": None}


def test_upsert_snapshots_inserts_and_updates(db, sample_member, monkeypatch):
    # commit을 no-op으로 막아 conftest 외부 트랜잭션 롤백 격리 유지.
    # 운영에선 commit이 identity map을 expire하므로, 테스트에서도 재조회 전 expire_all로 모사.
    monkeypatch.setattr(db, "commit", lambda: None)
    _make_service(db, sample_member.member_id, "s1", "svc")

    me_dashboard_service._upsert_snapshots(db, [_fetched("s1", workflow_count=2, model_count=3,
                                                          m1h={"message_count": 100})])
    db.expire_all()
    card = db.query(ServiceCardSnapshot).filter_by(surro_service_id="s1").one()
    assert card.workflow_count == 2 and card.model_count == 3
    assert db.query(ServiceMetricSnapshot).filter_by(surro_service_id="s1").count() == 3

    # 재 upsert → 갱신(중복 없음)
    me_dashboard_service._upsert_snapshots(db, [_fetched("s1", workflow_count=9, model_count=9)])
    db.expire_all()
    assert db.query(ServiceCardSnapshot).filter_by(surro_service_id="s1").count() == 1
    assert db.query(ServiceCardSnapshot).filter_by(surro_service_id="s1").one().workflow_count == 9
    assert db.query(ServiceMetricSnapshot).filter_by(surro_service_id="s1").count() == 3


def test_refresh_member_services_live_populates_cache(db, sample_member, monkeypatch):
    monkeypatch.setattr(db, "commit", lambda: None)
    _make_service(db, sample_member.member_id, "s1", "svc one")

    svc = FakeSvcClient({"s1": _svc_detail(["wf1"], m1h=_pm(message_count=42))})
    wf = FakeWfClient({"wf1": SimpleNamespace(components=[SimpleNamespace(model_id=7)])})
    monkeypatch.setattr("app.services.service_service.service_service.get_service", svc.get_service)
    monkeypatch.setattr("app.services.workflow_service.workflow_service.get_workflow", wf.get_workflow)

    n = _run(me_dashboard_service.refresh_member_services_live(db, sample_member, include_model_count=True))
    assert n == 1
    card = db.query(ServiceCardSnapshot).filter_by(surro_service_id="s1").one()
    assert card.workflow_count == 1
    assert card.model_count == 1
    m1h = db.query(ServiceMetricSnapshot).filter_by(surro_service_id="s1", period="1h").one()
    assert m1h.message_count == 42


# ============================================================
# 활동 히스토리
# ============================================================

def test_get_my_activities_scoped_to_actor_and_ordered(db, sample_member, admin_member):
    db.add_all([
        AuditLog(action="create", resource_type="service", resource_id="a",
                 actor_member_id=sample_member.member_id, created_at=datetime(2026, 6, 1, 10, 0, 0)),
        AuditLog(action="delete", resource_type="workflow", resource_id="b",
                 actor_member_id=sample_member.member_id, created_at=datetime(2026, 6, 2, 10, 0, 0)),
        AuditLog(action="create", resource_type="service", resource_id="c",
                 actor_member_id=admin_member.member_id, created_at=datetime(2026, 6, 3, 10, 0, 0)),
    ])
    db.flush()

    rows, total = me_dashboard_service.get_my_activities(db, sample_member.member_id, page=1, size=20)
    assert total == 2  # 타 사용자(admin) 활동 제외
    assert [r.resource_id for r in rows] == ["b", "a"]  # created_at DESC


def test_get_my_activities_filters(db, sample_member):
    db.add_all([
        AuditLog(action="create", resource_type="service", resource_id="a",
                 actor_member_id=sample_member.member_id, created_at=datetime(2026, 6, 1, 10, 0, 0)),
        AuditLog(action="status_change", resource_type="workflow", resource_id="b",
                 actor_member_id=sample_member.member_id,
                 metadata_json={"from": "DRAFT", "to": "ACTIVE"},
                 created_at=datetime(2026, 6, 2, 10, 0, 0)),
    ])
    db.flush()

    rows, total = me_dashboard_service.get_my_activities(
        db, sample_member.member_id, resource_type="workflow")
    assert total == 1 and rows[0].resource_id == "b"
    assert rows[0].metadata_json == {"from": "DRAFT", "to": "ACTIVE"}


# ============================================================
# 라우트 통합 (TestClient)
# ============================================================

def test_route_services_cache(db, sample_member, monkeypatch):
    monkeypatch.setattr("app.config.settings.DASHBOARD_CACHE_TTL_MINUTES", 10, raising=False)
    _make_service(db, sample_member.member_id, "s1", "svc one", "RAG 채팅 서비스")
    _seed_card(db, "s1", workflow_count=24, model_count=15, age_minutes=1)

    with _client(db, sample_member) as client:
        r = client.get("/api/v1/me/dashboard/services")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "cache"
    assert body["services"][0]["workflow_count"] == 24
    assert body["services"][0]["model_count"] == 15
    assert body["services"][0]["description"] == "RAG 채팅 서비스"


def test_route_monitoring_cache_all_periods(db, sample_member, monkeypatch):
    monkeypatch.setattr("app.config.settings.DASHBOARD_CACHE_TTL_MINUTES", 10, raising=False)
    _make_service(db, sample_member.member_id, "s1", "svc one")
    _seed_metric(db, "s1", "1h", message_count=100, age_minutes=1)
    _seed_metric(db, "s1", "1d", message_count=900, age_minutes=1)
    _seed_metric(db, "s1", "1w", message_count=5000, age_minutes=1)

    with _client(db, sample_member) as client:
        r = client.get("/api/v1/me/dashboard/monitoring?top_n=5")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "cache"
    assert set(body["top"].keys()) == {"1h", "1d", "1w"}
    assert body["top"]["1w"]["message_count"][0]["value"] == 5000.0
    assert body["services"][0]["metrics"]["1d"]["message_count"] == 900


def test_route_services_live_refreshes_when_empty(db, sample_member, monkeypatch):
    monkeypatch.setattr(db, "commit", lambda: None)
    _make_service(db, sample_member.member_id, "s1", "svc one")
    svc = FakeSvcClient({"s1": _svc_detail(["wf1", "wf2"], m1h=_pm(message_count=11))})
    wf = FakeWfClient({
        "wf1": SimpleNamespace(components=[SimpleNamespace(model_id=1)]),
        "wf2": SimpleNamespace(components=[SimpleNamespace(model_id=1), SimpleNamespace(model_id=2)]),
    })
    monkeypatch.setattr("app.services.service_service.service_service.get_service", svc.get_service)
    monkeypatch.setattr("app.services.workflow_service.workflow_service.get_workflow", wf.get_workflow)

    with _client(db, sample_member) as client:
        r = client.get("/api/v1/me/dashboard/services")
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "live"
    assert body["services"][0]["workflow_count"] == 2
    assert body["services"][0]["model_count"] == 2  # distinct {1,2}


def test_route_activities(db, sample_member):
    db.add(AuditLog(action="create", resource_type="service", resource_id="a",
                    actor_member_id=sample_member.member_id, metadata_json={"name": "svc"},
                    created_at=datetime(2026, 6, 1, 10, 0, 0)))
    db.flush()
    with _client(db, sample_member) as client:
        r = client.get("/api/v1/me/dashboard/activities")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    item = body["data"][0]
    assert item["action"] == "create"
    assert item["resource_type"] == "service"
    assert item["metadata"] == {"name": "svc"}  # serialization_alias


# ============================================================
# soft-delete 된 서비스 제외
# ============================================================

def _soft_delete(service):
    service.deleted_at = datetime.utcnow()
    service.is_active = False


def test_build_cards_response_excludes_deleted_service(db, sample_member):
    _make_service(db, sample_member.member_id, "s-live", "live")
    gone = _make_service(db, sample_member.member_id, "s-gone", "gone")
    _soft_delete(gone)
    db.flush()

    resp = me_dashboard_service.build_cards_response(db, sample_member.member_id)

    assert [c.surro_service_id for c in resp.services] == ["s-live"]


def test_route_uses_cache_when_member_has_deleted_service(db, sample_member, monkeypatch):
    """삭제된 서비스가 있어도 신선한 캐시가 있으면 업스트림을 부르지 않는다."""
    monkeypatch.setattr("app.config.settings.DASHBOARD_CACHE_TTL_MINUTES", 10, raising=False)
    _make_service(db, sample_member.member_id, "s-live", "live")
    _seed_card(db, "s-live", workflow_count=3, age_minutes=1)
    gone = _make_service(db, sample_member.member_id, "s-gone", "gone")
    _soft_delete(gone)
    db.flush()

    calls = []

    async def counting_get_service(surro_id, user_info):
        calls.append(surro_id)
        return None

    monkeypatch.setattr(
        "app.services.service_service.service_service.get_service", counting_get_service
    )

    with _client(db, sample_member) as client:
        r = client.get("/api/v1/me/dashboard/services")

    assert r.status_code == 200
    assert r.json()["source"] == "cache"
    assert calls == []


def test_refresh_all_services_sync_skips_deleted_service(db, sample_member, monkeypatch):
    _make_service(db, sample_member.member_id, "s-live", "live")
    gone = _make_service(db, sample_member.member_id, "s-gone", "gone")
    _soft_delete(gone)
    db.flush()

    requested = []

    async def fake_refresh(items, include_model_count, svc_client, wf_client):
        requested.extend(surro_id for surro_id, _ in items)
        return []

    monkeypatch.setattr(me_dashboard_service, "_refresh_async", fake_refresh)

    me_dashboard_service.refresh_all_services_sync(db, include_model_count=False)

    assert requested == ["s-live"]


# ============================================================
# live refresh 실패 후 세션 복구
# ============================================================

RB_MEMBER = "dash-rb-user"
RB_POISON = "dash-rb-poison"


def _purge_rb(session):
    service_ids = [
        sid for (sid,) in session.query(Service.surro_service_id)
        .filter(Service.created_by == RB_MEMBER).all()
    ]
    for model in (ServiceCardSnapshot, ServiceMetricSnapshot):
        session.query(model).filter(
            model.surro_service_id.in_(service_ids)
        ).delete(synchronize_session=False)
    session.query(Service).filter(Service.created_by == RB_MEMBER).delete(synchronize_session=False)
    session.query(Member).filter(
        Member.member_id.in_([RB_MEMBER, RB_POISON])
    ).delete(synchronize_session=False)
    session.commit()


@pytest.fixture
def rb_db():
    """rollback 이 준비 데이터를 되돌리지 않는 세션. 공용 `db` 는 rollback_only 로 참여한다."""
    connection = _engine.connect()
    session = Session(bind=connection, autoflush=False)
    _purge_rb(session)
    member = Member(
        name="dash rb", member_id=RB_MEMBER, email=f"{RB_MEMBER}@example.com",
        password_hash="$2b$12$dummyhashvalue1234567890abcdefghijklmnopqrstuv",
        role="user", is_active=True,
    )
    session.add(member)
    session.add(Service(name="svc", created_by=RB_MEMBER, surro_service_id="rb-svc"))
    session.commit()
    session.refresh(member)
    try:
        yield session, member
    finally:
        session.rollback()
        _purge_rb(session)
        session.close()
        connection.close()


def _failing_live_refresh(monkeypatch):
    """live refresh 가 스냅샷 commit 중 flush 실패로 세션을 오염시킨 상황."""
    async def failing(db, current_user, **kwargs):
        db.add(Member(
            name=None, member_id=RB_POISON, email=f"{RB_POISON}@example.com",
            password_hash="x", role="user", is_active=True,
        ))
        db.commit()

    monkeypatch.setattr(me_dashboard_service, "refresh_member_services_live", failing)


def test_cards_served_after_live_refresh_failure(rb_db, monkeypatch):
    db, member = rb_db
    _failing_live_refresh(monkeypatch)

    resp = _run(me_dashboard_service.get_my_cards(db, member))

    assert resp.source == "cache"
    assert [c.surro_service_id for c in resp.services] == ["rb-svc"]


def test_monitoring_served_after_live_refresh_failure(rb_db, monkeypatch):
    db, member = rb_db
    _failing_live_refresh(monkeypatch)

    resp = _run(me_dashboard_service.get_my_monitoring(db, member))

    assert resp.source == "cache"
    assert [s.surro_service_id for s in resp.services] == ["rb-svc"]


@pytest.mark.skipif(
    _engine.dialect.name == "postgresql",
    reason="SQLite 분기의 bulk insert 로 행 순서를 캡처한다 — 정렬은 분기 전에 일어난다",
)
def test_upsert_snapshots_writes_rows_in_key_order(db, monkeypatch):
    """라우트 live refresh 와 스케줄러가 같은 행을 같은 순서로 잠그도록 정렬해 쓴다."""
    written = {}

    def capture(mapper, rows):
        written[mapper.__name__] = [
            (r["surro_service_id"], r.get("period")) for r in rows
        ]

    monkeypatch.setattr(db, "bulk_insert_mappings", capture)
    monkeypatch.setattr(db, "commit", lambda: None)

    me_dashboard_service._upsert_snapshots(db, [_fetched("s-b"), _fetched("s-a")])

    assert written["ServiceCardSnapshot"] == [("s-a", None), ("s-b", None)]
    # 기간 순서는 두 경로 모두 고정된 _PERIODS 를 따르므로 서비스 순서만 맞으면 된다
    assert [sid for sid, _ in written["ServiceMetricSnapshot"]] == ["s-a"] * 3 + ["s-b"] * 3


# ============================================================
# live refresh 는 스냅샷이 없거나 오래된 서비스만
# ============================================================

def _count_get_service(monkeypatch):
    calls = []

    async def counting(surro_id, user_info):
        calls.append(surro_id)
        return None  # MLOps 404 (삭제되지 않았지만 업스트림에 없는 서비스)

    monkeypatch.setattr(
        "app.services.service_service.service_service.get_service", counting
    )
    return calls


def test_cards_live_refresh_only_stale_services(db, sample_member, monkeypatch):
    """하나가 404 로 스냅샷이 없어도 신선한 서비스까지 매 요청 다시 조회하지 않는다."""
    monkeypatch.setattr("app.config.settings.DASHBOARD_CACHE_TTL_MINUTES", 10, raising=False)
    _make_service(db, sample_member.member_id, "s-fresh", "fresh")
    _seed_card(db, "s-fresh", workflow_count=2, age_minutes=1)
    _make_service(db, sample_member.member_id, "s-404", "missing upstream")
    db.flush()
    calls = _count_get_service(monkeypatch)

    _run(me_dashboard_service.get_my_cards(db, sample_member))

    assert calls == ["s-404"]


def test_monitoring_live_refresh_only_stale_services(db, sample_member, monkeypatch):
    monkeypatch.setattr("app.config.settings.DASHBOARD_CACHE_TTL_MINUTES", 10, raising=False)
    _make_service(db, sample_member.member_id, "s-fresh", "fresh")
    _seed_all_periods(db, "s-fresh", age_minutes=1)
    _make_service(db, sample_member.member_id, "s-404", "missing upstream")
    db.flush()
    calls = _count_get_service(monkeypatch)

    _run(me_dashboard_service.get_my_monitoring(db, sample_member))

    assert calls == ["s-404"]
