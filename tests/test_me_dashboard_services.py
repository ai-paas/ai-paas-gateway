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

from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.database import get_db
from app.main import app
from app.models.audit_log import AuditLog
from app.models.dashboard_cache import ServiceCardSnapshot, ServiceMetricSnapshot
from app.models.service import Service
from app.services import me_dashboard_service


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
