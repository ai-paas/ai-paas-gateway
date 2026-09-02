"""Phase 4 — api_metrics (histogram) + provider_health 통합 테스트."""
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.auth import get_current_admin_user, get_current_user
from app.database import get_db
from app.main import app
from app.models.api_metric import ApiRequestHistogram, ProviderHealthSnapshot
from app.services import api_metrics_service, provider_health_service
from app.services.provider_health_service import HealthResult


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


# ---------- api_metrics_service unit ----------

class TestApiMetricsService:
    def setup_method(self):
        # buffer 초기화
        api_metrics_service._buffer.clear()

    def test_normalize_path_replaces_int_and_uuid(self):
        assert api_metrics_service.normalize_path("/api/v1/models/123") == "/api/v1/models/{id}"
        assert api_metrics_service.normalize_path(
            "/api/v1/services/87cded99-326a-4b6b-a2e2-71944cf89d02"
        ) == "/api/v1/services/{id}"
        assert api_metrics_service.normalize_path("/api/v1/health") == "/api/v1/health"

    def test_le_bucket(self):
        assert api_metrics_service._le_bucket(5) == 10
        assert api_metrics_service._le_bucket(15) == 50
        assert api_metrics_service._le_bucket(75) == 100
        assert api_metrics_service._le_bucket(10000) == 999999  # +Inf

    def test_record_increments_buffer(self):
        api_metrics_service.record("/api/v1/models/1", 200, 23.5)
        api_metrics_service.record("/api/v1/models/2", 200, 27.0)
        assert len(api_metrics_service._buffer) == 1  # 같은 path_pattern+bucket이라 단일 키
        key = next(iter(api_metrics_service._buffer))
        assert key[1] == "/api/v1/models/{id}"
        assert key[2] == "2xx"
        assert api_metrics_service._buffer[key]["count"] == 2

    def test_flush_persists_and_clears(self, db):
        api_metrics_service.record("/api/v1/x", 200, 30.0)
        api_metrics_service.record("/api/v1/x", 500, 1200.0)
        n = api_metrics_service.flush_buffered_buckets(db)
        assert n == 2
        assert len(api_metrics_service._buffer) == 0
        rows = db.query(ApiRequestHistogram).all()
        assert len(rows) == 2

    def test_flush_upserts_existing_bucket(self, db):
        """같은 bucket key는 count/sum/max 누적."""
        api_metrics_service.record("/api/v1/y", 200, 40.0)
        api_metrics_service.flush_buffered_buckets(db)

        api_metrics_service.record("/api/v1/y", 200, 35.0)
        api_metrics_service.record("/api/v1/y", 200, 80.0)  # 다른 bucket (100)
        api_metrics_service.flush_buffered_buckets(db)

        rows = db.query(ApiRequestHistogram).filter(
            ApiRequestHistogram.path_pattern == "/api/v1/y"
        ).all()
        by_le = {r.le_bucket_ms: r for r in rows}
        # le=50: 첫번째 (40ms) + 두번째 (35ms) = count 2
        assert by_le[50].count == 2
        # le=100: 세번째 (80ms) = count 1
        assert by_le[100].count == 1

    def test_percentile_basic(self):
        # 100건 모두 le=100 bucket → p95는 95
        buckets = [(10, 0), (50, 0), (100, 100), (250, 0), (500, 0), (1000, 0), (5000, 0), (999999, 0)]
        p95 = api_metrics_service._percentile_from_buckets(buckets, 0.95)
        assert p95 is not None
        assert 0 < p95 <= 100

    def test_percentile_capped_by_max_observed(self):
        """sparse bucket이라 보간이 큰 값을 내도 max_observed로 cap."""
        # 단일 데이터 — 실측 max=275, le=500 bucket
        buckets = [(500, 1)]
        p95 = api_metrics_service._percentile_from_buckets(buckets, 0.95, max_observed=275)
        # 보간 결과 475가 나오더라도 max_observed로 cap
        assert p95 is not None
        assert p95 <= 275

    def test_percentile_inf_bucket_uses_max_observed(self):
        """+Inf bucket(le=999999)에만 데이터 있으면 max_observed가 가장 정확."""
        buckets = [(999999, 1)]
        p95 = api_metrics_service._percentile_from_buckets(buckets, 0.95, max_observed=8000)
        # max_observed를 반환 (prev_le=0 반환하던 버그 회귀 방지)
        assert p95 == 8000

    def test_percentile_p95_never_exceeds_max(self):
        """일반 케이스에서도 p95 > max_ms가 절대 발생하지 않는다."""
        cases = [
            ([(50, 10)], 30),    # 단일 bucket sparse
            ([(100, 5), (250, 5)], 240),
            ([(1000, 1), (5000, 2), (999999, 1)], 7500),
        ]
        for buckets, max_obs in cases:
            p95 = api_metrics_service._percentile_from_buckets(buckets, 0.95, max_observed=max_obs)
            assert p95 is not None and p95 <= max_obs, f"buckets={buckets} max={max_obs} p95={p95}"


# ---------- /api-metrics endpoint ----------

def test_api_metrics_endpoint_returns_paths(db, admin_member):
    # 시드: 30ms 2건, 500ms 1건 (5xx)
    api_metrics_service._buffer.clear()
    api_metrics_service.record("/api/v1/models", 200, 30.0)
    api_metrics_service.record("/api/v1/models", 200, 35.0)
    api_metrics_service.record("/api/v1/models", 500, 480.0)
    api_metrics_service.flush_buffered_buckets(db)

    with _admin_client(db, admin_member) as client:
        resp = client.get("/api/v1/admin/dashboard/api-metrics", params={"hours": 1})
        assert resp.status_code == 200
        body = resp.json()

    assert "buckets_ms" in body
    paths = {(p["path_pattern"], p["status_class"]): p for p in body["paths"]}
    assert ("/api/v1/models", "2xx") in paths
    assert ("/api/v1/models", "5xx") in paths
    assert paths[("/api/v1/models", "2xx")]["count"] == 2
    assert paths[("/api/v1/models", "5xx")]["count"] == 1


def test_api_metrics_endpoint_path_filter(db, admin_member):
    api_metrics_service._buffer.clear()
    api_metrics_service.record("/a", 200, 10.0)
    api_metrics_service.record("/b", 200, 10.0)
    api_metrics_service.flush_buffered_buckets(db)

    with _admin_client(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/api-metrics",
            params={"path_pattern": "/a"},
        ).json()

    assert all(p["path_pattern"] == "/a" for p in body["paths"])


def test_api_metrics_flush_endpoint(db, admin_member):
    api_metrics_service._buffer.clear()
    api_metrics_service.record("/c", 200, 20.0)

    with _admin_client(db, admin_member) as client:
        resp = client.post("/api/v1/admin/dashboard/api-metrics/flush")
        assert resp.status_code == 200
        assert resp.json()["flushed"] >= 1


def test_api_metrics_admin_guard(db, sample_member):
    def override_db():
        yield db

    def override_current():
        return sample_member

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/admin/dashboard/api-metrics").status_code == 403
    finally:
        app.dependency_overrides.clear()


# ---------- provider_health_service ----------

def test_probe_all_returns_disabled_when_settings_off(monkeypatch):
    """connection 비활성화면 disabled status."""
    from app import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "PROXY_ENABLED", False)
    monkeypatch.setattr(cfg_module.settings, "HUB_CONNECT_ENABLED", False)
    monkeypatch.setattr(cfg_module.settings, "ANY_CLOUD_ENABLED", False)

    results = provider_health_service.probe_all_sync()
    statuses = {r.provider: r.status for r in results}
    assert statuses["mlops"] == "disabled"
    assert statuses["hub_connect"] == "disabled"
    assert statuses["any_cloud"] == "disabled"


def test_probe_all_and_record_inserts_snapshots(db, monkeypatch):
    from app import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "PROXY_ENABLED", False)
    monkeypatch.setattr(cfg_module.settings, "HUB_CONNECT_ENABLED", False)
    monkeypatch.setattr(cfg_module.settings, "ANY_CLOUD_ENABLED", False)

    results = provider_health_service.probe_all_and_record(db)
    assert len(results) == 3

    snaps = db.query(ProviderHealthSnapshot).all()
    assert len(snaps) == 3
    assert all(s.status == "disabled" for s in snaps)


# ---------- /providers/health endpoint ----------

def test_providers_health_endpoint_returns_latest(db, admin_member):
    now = datetime.utcnow()
    # 같은 provider 2건 — 최신 1건만 반환
    db.add(ProviderHealthSnapshot(
        ts=now - timedelta(minutes=5),
        provider="mlops", status="healthy", latency_ms=120,
    ))
    db.add(ProviderHealthSnapshot(
        ts=now - timedelta(minutes=1),
        provider="mlops", status="unhealthy", latency_ms=900, error="HTTP 503",
    ))
    db.add(ProviderHealthSnapshot(
        ts=now, provider="hub_connect", status="disabled",
    ))
    db.flush()

    with _admin_client(db, admin_member) as client:
        body = client.get("/api/v1/admin/dashboard/providers/health").json()

    by_provider = {p["provider"]: p for p in body["providers"]}
    assert by_provider["mlops"]["status"] == "unhealthy"  # 최신
    assert by_provider["mlops"]["latency_ms"] == 900
    assert by_provider["hub_connect"]["status"] == "disabled"


def test_providers_health_history_included(db, admin_member):
    now = datetime.utcnow()
    for i in range(3):
        db.add(ProviderHealthSnapshot(
            ts=now - timedelta(minutes=i * 5),
            provider="mlops", status="healthy", latency_ms=100 + i,
        ))
    db.flush()

    with _admin_client(db, admin_member) as client:
        body = client.get(
            "/api/v1/admin/dashboard/providers/health",
            params={"history_minutes": 60},
        ).json()

    assert "mlops" in body["history"]
    assert len(body["history"]["mlops"]) == 3


def test_providers_health_probe_endpoint(db, admin_member, monkeypatch):
    from app import config as cfg_module

    monkeypatch.setattr(cfg_module.settings, "PROXY_ENABLED", False)
    monkeypatch.setattr(cfg_module.settings, "HUB_CONNECT_ENABLED", False)
    monkeypatch.setattr(cfg_module.settings, "ANY_CLOUD_ENABLED", False)

    with _admin_client(db, admin_member) as client:
        resp = client.post("/api/v1/admin/dashboard/providers/health/probe")
        assert resp.status_code == 200
        body = resp.json()

    providers = {p["provider"]: p for p in body["providers"]}
    assert providers["mlops"]["status"] == "disabled"

    # DB에도 기록됐는지
    assert db.query(ProviderHealthSnapshot).count() >= 3


def test_providers_health_admin_guard(db, sample_member):
    def override_db():
        yield db

    def override_current():
        return sample_member

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_current
    try:
        with TestClient(app) as client:
            assert client.get("/api/v1/admin/dashboard/providers/health").status_code == 403
    finally:
        app.dependency_overrides.clear()
