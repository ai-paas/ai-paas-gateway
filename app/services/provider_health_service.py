"""외부 provider health probe service.

각 provider별 base URL 호출 → latency + HTTP 응답으로 status 판단.
스케줄러가 매 분 `probe_all_and_record()` 호출 → provider_health_snapshots insert.

provider별 전용 health endpoint가 없어 가벼운 GET 호출(`/` 또는 `/version`)을
사용한다. 어느 응답코드든 latency 측정. 2xx면 healthy, 그 외는 unhealthy.
연동 disabled면 status="disabled".
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import httpx
from sqlalchemy.orm import Session

from app.config import settings
from app.models.api_metric import ProviderHealthSnapshot

logger = logging.getLogger(__name__)


@dataclass
class HealthResult:
    provider: str
    status: str  # healthy/unhealthy/disabled/error
    latency_ms: Optional[int]
    error: Optional[str]


# ---------- provider별 설정 ----------

@dataclass
class ProviderConfig:
    name: str
    enabled: bool
    base_url: str
    timeout: float


def _provider_configs() -> List[ProviderConfig]:
    return [
        ProviderConfig("mlops", settings.PROXY_ENABLED, settings.PROXY_TARGET_BASE_URL,
                       settings.PROXY_CONNECT_TIMEOUT or 5.0),
        ProviderConfig("hub_connect", settings.HUB_CONNECT_ENABLED,
                       settings.HUB_CONNECT_TARGET_BASE_URL,
                       settings.HUB_CONNECT_CONNECT_TIMEOUT or 5.0),
        ProviderConfig("any_cloud", settings.ANY_CLOUD_ENABLED,
                       settings.ANY_CLOUD_TARGET_BASE_URL,
                       settings.ANY_CLOUD_CONNECT_TIMEOUT or 5.0),
    ]


async def _probe_one(cfg: ProviderConfig) -> HealthResult:
    if not cfg.enabled or not cfg.base_url:
        return HealthResult(cfg.name, "disabled", None, None)

    url = cfg.base_url.rstrip("/")
    start = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=cfg.timeout) as client:
            resp = await client.get(url, follow_redirects=True)
        latency = int(round((time.perf_counter() - start) * 1000))
        if 200 <= resp.status_code < 400:
            return HealthResult(cfg.name, "healthy", latency, None)
        return HealthResult(cfg.name, "unhealthy", latency,
                            f"HTTP {resp.status_code}")
    except httpx.TimeoutException:
        latency = int(round((time.perf_counter() - start) * 1000))
        return HealthResult(cfg.name, "error", latency, "timeout")
    except Exception as e:  # noqa: BLE001
        latency = int(round((time.perf_counter() - start) * 1000))
        return HealthResult(cfg.name, "error", latency, str(e)[:480])


async def probe_all() -> List[HealthResult]:
    results: List[HealthResult] = []
    for cfg in _provider_configs():
        results.append(await _probe_one(cfg))
    return results


def probe_all_sync() -> List[HealthResult]:
    """동기 wrapper — 스케줄러는 sync 컨텍스트라 asyncio 진입 필요."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            raise RuntimeError("already running loop")
    except RuntimeError:
        loop = None

    if loop is None:
        return asyncio.run(probe_all())
    return loop.run_until_complete(probe_all())


def probe_all_and_record(db: Session) -> List[HealthResult]:
    """probe → DB insert. 스케줄러가 호출."""
    results = probe_all_sync()
    now = datetime.utcnow()
    for r in results:
        db.add(ProviderHealthSnapshot(
            ts=now,
            provider=r.provider,
            status=r.status,
            latency_ms=r.latency_ms,
            error=r.error,
        ))
    db.commit()
    return results
