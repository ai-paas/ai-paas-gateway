"""Phase 3 — 트렌드 service + endpoint 통합 테스트."""
from contextlib import contextmanager
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import get_current_admin_user, get_current_user
from app.database import get_db
from app.main import app
from app.models import (
    DailyStat,
    KnowledgeBase,
    Model,
    Prompt,
    Service,
    Workflow,
)
from app.services import trends_service


@contextmanager
def _admin_client(db, admin_user):
    def override_db():
        yield db

    def override_admin():
        return admin_user

    def override_current():
        return admin_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_admin_user] = override_admin
    app.dependency_overrides[get_current_user] = override_current
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


# ---------- refresh_daily_stats ----------

def test_refresh_daily_stats_populates_table(db, sample_member):
    now = datetime.utcnow()
    db.add(Service(name="s1", created_by=sample_member.member_id,
                   surro_service_id="t-s1", created_at=now))
    db.add(Workflow(name="w1", created_by=sample_member.member_id,
                    surro_workflow_id="t-w1", created_at=now))
    db.add(Model(surro_model_id=1, created_by=sample_member.member_id,
                 is_active=True, created_at=now))
    db.add(Model(surro_model_id=2, created_by=sample_member.member_id,
                 deleted_at=now, created_at=now))
    db.flush()

    n = trends_service.refresh_daily_stats(db)
    assert n > 0

    rows = db.query(DailyStat).all()
    # 최소: service.created, workflow.created, model.created, model.deleted, signup.created
    domains = {(r.domain, r.metric) for r in rows}
    assert ("service", "created") in domains
    assert ("workflow", "created") in domains
    assert ("model", "created") in domains
    assert ("model", "deleted") in domains
    assert ("signup", "created") in domains


def test_refresh_daily_stats_upserts_idempotent(db, sample_member):
    """같은 일자에 두 번 돌려도 row 수가 폭증하지 않음 (upsert)."""
    db.add(Service(name="s", created_by=sample_member.member_id,
                   surro_service_id="t-s2"))
    db.flush()

    trends_service.refresh_daily_stats(db)
    count1 = db.query(DailyStat).count()

    trends_service.refresh_daily_stats(db)
    count2 = db.query(DailyStat).count()

    assert count1 == count2


# ---------- get_trends ----------

def test_get_trends_uses_daily_stats_when_available(db, sample_member):
    today = date.today()
    db.add(DailyStat(date=today, domain="service", metric="created", value=5))
    db.add(DailyStat(date=today, domain="signup", metric="created", value=2))
    db.flush()

    resp = trends_service.get_trends(db, days=7)
    assert resp.source == "daily_stats"
    domains = {(s.domain, s.metric) for s in resp.series}
    assert ("service", "created") in domains
    assert ("signup", "created") in domains


def test_get_trends_live_fallback_when_empty(db, sample_member):
    """daily_stats가 비어있으면 raw 집계 폴백."""
    db.add(Service(name="s", created_by=sample_member.member_id,
                   surro_service_id="t-s3"))
    db.flush()

    resp = trends_service.get_trends(db, days=30)
    assert resp.source == "live"
    # raw 집계에 service.created 1개 있어야 함
    s_series = [s for s in resp.series if s.domain == "service" and s.metric == "created"]
    assert s_series and sum(p.value for p in s_series[0].points) == 1


def test_get_trends_domain_filter(db, sample_member):
    today = date.today()
    db.add(DailyStat(date=today, domain="service", metric="created", value=3))
    db.add(DailyStat(date=today, domain="model", metric="created", value=7))
    db.flush()

    resp = trends_service.get_trends(db, days=7, domain="model")
    assert all(s.domain == "model" for s in resp.series)


def test_get_trends_unknown_domain_raises(db):
    with pytest.raises(ValueError):
        trends_service.get_trends(db, days=7, domain="bogus")


def test_get_trends_respects_window(db, sample_member):
    """days 범위 밖 데이터는 제외."""
    far_past = date.today() - timedelta(days=400)
    db.add(DailyStat(date=far_past, domain="service", metric="created", value=99))
    db.add(DailyStat(date=date.today(), domain="service", metric="created", value=1))
    db.flush()

    resp = trends_service.get_trends(db, days=30)
    s_series = [s for s in resp.series if s.domain == "service"][0]
    # 400일 전 99는 제외, 오늘 1만 포함
    assert sum(p.value for p in s_series.points) == 1


# ---------- /trends endpoint ----------

def test_trends_endpoint_returns_200(db, admin_member, sample_member):
    db.add(Service(name="s", created_by=sample_member.member_id,
                   surro_service_id="t-ep"))
    db.flush()

    with _admin_client(db, admin_member) as client:
        resp = client.get("/api/v1/admin/dashboard/trends", params={"days": 30})
        assert resp.status_code == 200
        body = resp.json()

    assert body["days"] == 30
    assert body["source"] in ("daily_stats", "live")
    assert "series" in body


def test_trends_endpoint_admin_guard(db, sample_member):
    def override_db():
        yield db

    def override_current():
        return sample_member

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current
    try:
        with TestClient(app) as client:
            resp = client.get("/api/v1/admin/dashboard/trends")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_trends_endpoint_invalid_domain_returns_422(db, admin_member):
    with _admin_client(db, admin_member) as client:
        resp = client.get(
            "/api/v1/admin/dashboard/trends",
            params={"domain": "bogus"},
        )
    assert resp.status_code == 422


# ---------- /trends/refresh endpoint ----------

def test_refresh_endpoint_upserts_rows(db, admin_member, sample_member):
    db.add(Prompt(name="p", content="x", created_by=sample_member.member_id,
                  surro_prompt_id=999))
    db.flush()

    with _admin_client(db, admin_member) as client:
        resp = client.post("/api/v1/admin/dashboard/trends/refresh")
        assert resp.status_code == 200
        body = resp.json()

    assert body["rows_upserted"] >= 1
    # SQLite 환경에선 mat view 갱신 못 함
    assert body["refreshed_materialized_view"] in (True, False)


# ---------- scheduler import sanity ----------

def test_scheduler_disabled_returns_none(monkeypatch):
    """ENABLE_SCHEDULER=false면 start_scheduler가 None 반환.

    실행 환경의 .env에서 ENABLE_SCHEDULER=true일 수 있으므로 monkeypatch로 강제 false.
    """
    from app import config as cfg_module
    from app.scheduler import get_scheduler, start_scheduler, stop_scheduler

    monkeypatch.setattr(cfg_module.settings, "ENABLE_SCHEDULER", False)
    sched = start_scheduler()
    try:
        assert sched is None
        assert get_scheduler() is None
    finally:
        stop_scheduler()


def test_scheduler_enabled_registers_jobs(monkeypatch):
    """ENABLE_SCHEDULER=true이면 잡이 등록되고 stop으로 정리된다."""
    from app import config as cfg_module
    from app.scheduler import get_scheduler, start_scheduler, stop_scheduler

    monkeypatch.setattr(cfg_module.settings, "ENABLE_SCHEDULER", True)
    monkeypatch.setattr(cfg_module.settings, "SCHEDULER_INCLUDE_API_METRICS", True)
    sched = start_scheduler()
    try:
        assert sched is not None
        ids = {j.id for j in sched.get_jobs()}
        assert "refresh_daily_stats" in ids
        assert "refresh_mv_daily_trends" in ids
        assert "flush_api_metrics" in ids
        assert "probe_providers" in ids
    finally:
        stop_scheduler()
        assert get_scheduler() is None


def test_scheduler_skips_api_metrics_when_excluded(monkeypatch):
    """SCHEDULER_INCLUDE_API_METRICS=false면 api_metrics flush 잡은 건너뛴다 (별도 worker 모드)."""
    from app import config as cfg_module
    from app.scheduler import start_scheduler, stop_scheduler

    monkeypatch.setattr(cfg_module.settings, "ENABLE_SCHEDULER", True)
    monkeypatch.setattr(cfg_module.settings, "SCHEDULER_INCLUDE_API_METRICS", False)
    sched = start_scheduler()
    try:
        assert sched is not None
        ids = {j.id for j in sched.get_jobs()}
        assert "flush_api_metrics" not in ids
        # 나머지는 그대로 등록
        assert "refresh_daily_stats" in ids
        assert "probe_providers" in ids
    finally:
        stop_scheduler()
