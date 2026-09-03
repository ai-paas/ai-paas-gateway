"""개인 대시보드 service: 서비스 현황 카드 + 기간별(1h/1d/1w) 모니터링 + 활동 히스토리.

설계(캐싱 우선):
- MLOps 서비스 detail 호출은 서비스 수만큼 N+1이라 비싸다 → 결과를 스냅샷 테이블에 캐시.
- 읽기: gateway `services`(소유권/이름) 기준 + 스냅샷(캐시 수치) 병합. 본인(created_by) 것만.
- 캐시 미스/TTL 만료: 본인 서비스만 즉시(live) 집계 후 upsert (cold-start UX). bounded 동시성.
- 스케줄러: 전체 서비스 주기 pre-warm (`refresh_all_services_sync`).

활동 히스토리는 audit_logs(본인 actor)를 시계열로 노출 — k8s 이벤트를 대체하는
"사용자가 UI에서 한 작업(서비스/워크플로우 생성·수정·삭제·상태변경 등)" 피드.

async/sync 경계:
- fetch(`_fetch_one`/`_refresh_async`)는 순수 HTTP만 — client는 주입받음.
- route(async loop)는 싱글톤 client를 주입해 await.
- 스케줄러(sync)는 `asyncio.run` + 신규 client 인스턴스(루프 교차 재사용 회피).
- DB upsert(`_upsert_snapshots`)는 동기 — fetch 결과(plain dict)만 받아 처리.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Service
from app.models.audit_log import AuditLog
from app.models.dashboard_cache import ServiceCardSnapshot, ServiceMetricSnapshot
from app.schemas.dashboard import (
    DASHBOARD_PERIODS,
    DashboardPeriodMetrics,
    MetricRankItem,
    MyServiceCardsResponse,
    MyServiceMonitoringResponse,
    PeriodTopMetrics,
    ServiceCardItem,
    ServiceMonitoringItem,
)

logger = logging.getLogger(__name__)

_PERIODS = DASHBOARD_PERIODS  # ("1h", "1d", "1w")
# top.* 에 순위 매길 헤드라인 메트릭 (이미지의 4개 위젯)
_RANK_FIELDS = ("message_count", "active_users", "token_usage", "avg_interaction_count")
_METRIC_FIELDS = (
    "message_count", "active_users", "token_usage", "avg_interaction_count",
    "response_time_ms", "error_count", "success_rate",
)
_CONCURRENCY = 8


# ============================================================
# 공통 helper
# ============================================================

def _user_info(member_id: str, role: Optional[str] = None, name: Optional[str] = None) -> Dict[str, str]:
    ui: Dict[str, str] = {"member_id": member_id}
    if role:
        ui["role"] = role
    if name:
        ui["name"] = name
    return ui


def _member_services(db: Session, member_id: str) -> List[Service]:
    return (
        db.query(Service)
        .filter(Service.created_by == member_id)
        .order_by(Service.created_at.desc())
        .all()
    )


def _is_stale(refreshed_at: Any) -> bool:
    """TTL 초과/미존재면 stale. TTL<=0이면 무한 캐시(스케줄러만 갱신)."""
    if refreshed_at is None:
        return True
    ttl = settings.DASHBOARD_CACHE_TTL_MINUTES
    if ttl <= 0:
        return False
    try:
        ra = refreshed_at
        if getattr(ra, "tzinfo", None) is not None:
            ra = ra.replace(tzinfo=None)
        return (datetime.utcnow() - ra) > timedelta(minutes=ttl)
    except Exception:
        return True


# ============================================================
# MLOps fetch (async, client 주입)
# ============================================================

def _period_metrics_to_dict(pm: Any) -> Dict[str, Any]:
    """MLOps PeriodMetrics(또는 유사 객체) → dict. None/누락 안전."""
    if pm is None:
        return {
            "message_count": 0, "active_users": 0, "token_usage": 0,
            "avg_interaction_count": 0.0, "response_time_ms": None,
            "error_count": 0, "success_rate": None,
        }
    return {
        "message_count": int(getattr(pm, "message_count", 0) or 0),
        "active_users": int(getattr(pm, "active_users", 0) or 0),
        "token_usage": int(getattr(pm, "token_usage", 0) or 0),
        "avg_interaction_count": float(getattr(pm, "avg_interaction_count", 0.0) or 0.0),
        "response_time_ms": getattr(pm, "response_time_ms", None),
        "error_count": int(getattr(pm, "error_count", 0) or 0),
        "success_rate": getattr(pm, "success_rate", None),
    }


async def _fetch_one(
    surro_id: str,
    user_info: Dict[str, str],
    include_model_count: bool,
    svc_client: Any,
    wf_client: Any,
    sem: asyncio.Semaphore,
) -> Optional[Dict[str, Any]]:
    """단일 서비스 detail → 카드 수치 + 기간별 메트릭 dict. 실패 시 None (best-effort)."""
    async with sem:
        try:
            ext = await svc_client.get_service(surro_id, user_info)
        except Exception:
            logger.warning("dashboard refresh: get_service failed surro_id=%s", surro_id, exc_info=True)
            return None
    if ext is None:
        return None

    workflows = list(getattr(ext, "workflows", []) or [])
    workflow_count = len(workflows)

    # 기간별 메트릭 (monitoring_data.total_metrics.{1h,1d,1w})
    metrics: Dict[str, Dict[str, Any]] = {p: _period_metrics_to_dict(None) for p in _PERIODS}
    aggregated_at = None
    md = getattr(ext, "monitoring_data", None)
    if md is not None:
        aggregated_at = getattr(md, "aggregated_at", None)
        tm = getattr(md, "total_metrics", None)
        if tm is not None:
            metrics["1h"] = _period_metrics_to_dict(getattr(tm, "period_1h", None))
            metrics["1d"] = _period_metrics_to_dict(getattr(tm, "period_1d", None))
            metrics["1w"] = _period_metrics_to_dict(getattr(tm, "period_1w", None))

    # 사용 모델 distinct 수 — 워크플로우 detail fan-out (비용 큼, 옵션)
    model_count: Optional[int] = None
    if include_model_count and workflows:
        model_ids: set = set()

        async def _wf(wf_id: str):
            async with sem:
                try:
                    return await wf_client.get_workflow(wf_id, user_info)
                except Exception:
                    logger.warning("dashboard refresh: get_workflow failed wf_id=%s", wf_id, exc_info=True)
                    return None

        wf_results = await asyncio.gather(*[_wf(getattr(wf, "id", None)) for wf in workflows])
        any_ok = False
        for r in wf_results:
            if r is None:
                continue
            any_ok = True
            for comp in (getattr(r, "components", None) or []):
                mid = getattr(comp, "model_id", None)
                if mid is not None:
                    model_ids.add(mid)
        # 워크플로우 detail을 하나도 못 받으면 신뢰 불가 → None 유지
        model_count = len(model_ids) if any_ok else None

    return {
        "surro_service_id": surro_id,
        "workflow_count": workflow_count,
        "model_count": model_count,
        "metrics": metrics,
        "aggregated_at": aggregated_at,
    }


async def _refresh_async(
    items: List[Tuple[str, Dict[str, str]]],
    include_model_count: bool,
    svc_client: Any,
    wf_client: Any,
) -> List[Dict[str, Any]]:
    """items: [(surro_id, user_info), ...] → 성공 fetch dict 리스트 (실패 항목 제외)."""
    if not items:
        return []
    sem = asyncio.Semaphore(_CONCURRENCY)
    results = await asyncio.gather(
        *[_fetch_one(sid, ui, include_model_count, svc_client, wf_client, sem) for sid, ui in items]
    )
    return [r for r in results if r is not None]


# ============================================================
# DB upsert (sync, dialect-agnostic)
# ============================================================

def _upsert_snapshots(db: Session, fetched: List[Dict[str, Any]]) -> int:
    """카드/메트릭 스냅샷 upsert. PG는 ON CONFLICT, 그 외는 delete+insert."""
    if not fetched:
        return 0
    now = datetime.utcnow()
    dialect = db.bind.dialect.name

    card_rows = [
        {
            "surro_service_id": f["surro_service_id"],
            "workflow_count": f["workflow_count"],
            "model_count": f["model_count"],
            "refreshed_at": now,
        }
        for f in fetched
    ]
    metric_rows: List[Dict[str, Any]] = []
    for f in fetched:
        for p in _PERIODS:
            m = f["metrics"][p]
            metric_rows.append({
                "surro_service_id": f["surro_service_id"],
                "period": p,
                "message_count": m["message_count"],
                "active_users": m["active_users"],
                "token_usage": m["token_usage"],
                "avg_interaction_count": m["avg_interaction_count"],
                "response_time_ms": m["response_time_ms"],
                "error_count": m["error_count"],
                "success_rate": m["success_rate"],
                "aggregated_at": f["aggregated_at"],
                "refreshed_at": now,
            })

    if dialect == "postgresql":
        cstmt = pg_insert(ServiceCardSnapshot.__table__).values(card_rows)
        cstmt = cstmt.on_conflict_do_update(
            constraint="uq_service_card_surro_id",
            set_={
                "workflow_count": cstmt.excluded.workflow_count,
                "model_count": cstmt.excluded.model_count,
                "refreshed_at": cstmt.excluded.refreshed_at,
            },
        )
        db.execute(cstmt)

        mstmt = pg_insert(ServiceMetricSnapshot.__table__).values(metric_rows)
        mstmt = mstmt.on_conflict_do_update(
            constraint="uq_service_metric_surro_period",
            set_={
                k: getattr(mstmt.excluded, k)
                for k in (
                    "message_count", "active_users", "token_usage", "avg_interaction_count",
                    "response_time_ms", "error_count", "success_rate", "aggregated_at", "refreshed_at",
                )
            },
        )
        db.execute(mstmt)
    else:
        surro_ids = [f["surro_service_id"] for f in fetched]
        db.query(ServiceCardSnapshot).filter(
            ServiceCardSnapshot.surro_service_id.in_(surro_ids)
        ).delete(synchronize_session=False)
        db.bulk_insert_mappings(ServiceCardSnapshot, card_rows)

        db.query(ServiceMetricSnapshot).filter(
            ServiceMetricSnapshot.surro_service_id.in_(surro_ids)
        ).delete(synchronize_session=False)
        db.bulk_insert_mappings(ServiceMetricSnapshot, metric_rows)

    db.commit()
    return len(fetched)


# ============================================================
# Refresh 진입점
# ============================================================

async def refresh_member_services_live(
    db: Session, current_user: Any, *, include_model_count: Optional[bool] = None
) -> int:
    """본인 서비스만 즉시 집계 + 캐시 upsert. route(async loop)에서 await — 싱글톤 client 사용.

    반환: upsert된 서비스 수.
    """
    from app.services.service_service import service_service
    from app.services.workflow_service import workflow_service

    if include_model_count is None:
        include_model_count = settings.DASHBOARD_INCLUDE_MODEL_COUNT

    services = _member_services(db, current_user.member_id)
    if not services:
        return 0

    ui = _user_info(
        current_user.member_id,
        getattr(current_user, "role", None),
        getattr(current_user, "name", None),
    )
    items = [(s.surro_service_id, ui) for s in services]
    fetched = await _refresh_async(items, include_model_count, service_service, workflow_service)
    return _upsert_snapshots(db, fetched)


def refresh_all_services_sync(db: Session, *, include_model_count: Optional[bool] = None) -> int:
    """스케줄러용: 전체 서비스 pre-warm. 신규 client 인스턴스로 asyncio.run (루프 교차 회피).

    반환: upsert된 서비스 수.
    """
    if include_model_count is None:
        include_model_count = settings.DASHBOARD_INCLUDE_MODEL_COUNT

    services = db.query(Service).all()
    if not services:
        return 0
    items = [(s.surro_service_id, _user_info(s.created_by)) for s in services]

    from app.services.service_service import ServiceService
    from app.services.workflow_service import WorkflowService

    async def _run() -> List[Dict[str, Any]]:
        svc = ServiceService()
        wf = WorkflowService()
        try:
            return await _refresh_async(items, include_model_count, svc, wf)
        finally:
            await svc.close()
            await wf.close()

    fetched = asyncio.run(_run())
    return _upsert_snapshots(db, fetched)


# ============================================================
# Serve (sync) — cache 병합 읽기
# ============================================================

def cards_need_refresh(db: Session, surro_ids: List[str]) -> bool:
    """카드 스냅샷이 하나라도 없거나 TTL stale이면 True."""
    if not surro_ids:
        return False
    rows = (
        db.query(ServiceCardSnapshot.surro_service_id, ServiceCardSnapshot.refreshed_at)
        .filter(ServiceCardSnapshot.surro_service_id.in_(surro_ids))
        .all()
    )
    have = {r.surro_service_id: r.refreshed_at for r in rows}
    for sid in surro_ids:
        if sid not in have or _is_stale(have[sid]):
            return True
    return False


def metrics_need_refresh(db: Session, surro_ids: List[str]) -> bool:
    """서비스마다 3개 기간 행이 다 있고 모두 fresh가 아니면 True."""
    if not surro_ids:
        return False
    rows = (
        db.query(
            ServiceMetricSnapshot.surro_service_id,
            ServiceMetricSnapshot.period,
            ServiceMetricSnapshot.refreshed_at,
        )
        .filter(ServiceMetricSnapshot.surro_service_id.in_(surro_ids))
        .all()
    )
    periods_by: Dict[str, set] = {}
    for r in rows:
        if _is_stale(r.refreshed_at):
            return True
        periods_by.setdefault(r.surro_service_id, set()).add(r.period)
    for sid in surro_ids:
        if periods_by.get(sid, set()) != set(_PERIODS):
            return True
    return False


def build_cards_response(
    db: Session, member_id: str, *, source: str = "cache"
) -> MyServiceCardsResponse:
    services = _member_services(db, member_id)
    if not services:
        return MyServiceCardsResponse(
            member_id=member_id, services=[], source="empty", generated_at=datetime.utcnow()
        )

    surro_ids = [s.surro_service_id for s in services]
    snap = {
        c.surro_service_id: c
        for c in db.query(ServiceCardSnapshot)
        .filter(ServiceCardSnapshot.surro_service_id.in_(surro_ids))
        .all()
    }
    items = [
        ServiceCardItem(
            surro_service_id=s.surro_service_id,
            name=s.name,
            description=s.description,
            workflow_count=(snap[s.surro_service_id].workflow_count if s.surro_service_id in snap else 0),
            model_count=(snap[s.surro_service_id].model_count if s.surro_service_id in snap else None),
        )
        for s in services
    ]
    return MyServiceCardsResponse(
        member_id=member_id, services=items, source=source, generated_at=datetime.utcnow()  # type: ignore[arg-type]
    )


def _row_to_period_metrics(row: Any) -> DashboardPeriodMetrics:
    if row is None:
        return DashboardPeriodMetrics()
    return DashboardPeriodMetrics(
        message_count=row.message_count,
        active_users=row.active_users,
        token_usage=row.token_usage,
        avg_interaction_count=row.avg_interaction_count,
        response_time_ms=row.response_time_ms,
        error_count=row.error_count,
        success_rate=row.success_rate,
    )


def build_monitoring_response(
    db: Session, member_id: str, *, top_n: int = 5, source: str = "cache"
) -> MyServiceMonitoringResponse:
    services = _member_services(db, member_id)
    name_map = {s.surro_service_id: s.name for s in services}
    surro_ids = list(name_map.keys())
    if not surro_ids:
        return MyServiceMonitoringResponse(
            member_id=member_id, source="empty", top_n=top_n,
            services=[], top={}, generated_at=datetime.utcnow(),
        )

    rows = (
        db.query(ServiceMetricSnapshot)
        .filter(ServiceMetricSnapshot.surro_service_id.in_(surro_ids))
        .all()
    )
    by_service: Dict[str, Dict[str, Any]] = {}
    agg_at: Dict[str, Any] = {}
    for r in rows:
        by_service.setdefault(r.surro_service_id, {})[r.period] = r
        if r.aggregated_at is not None:
            agg_at[r.surro_service_id] = r.aggregated_at

    # 서비스별 전체 기간 메트릭 (services[])
    services_out: List[ServiceMonitoringItem] = []
    for s in services:
        sid = s.surro_service_id
        per = by_service.get(sid, {})
        metrics = {p: _row_to_period_metrics(per.get(p)) for p in _PERIODS}
        services_out.append(
            ServiceMonitoringItem(
                surro_service_id=sid, name=name_map[sid], metrics=metrics, aggregated_at=agg_at.get(sid)
            )
        )

    # 기간별 메트릭 Top N (top.{1h,1d,1w}.{message_count,...})
    top: Dict[str, PeriodTopMetrics] = {}
    for p in _PERIODS:
        ptm = PeriodTopMetrics()
        for field in _RANK_FIELDS:
            scored: List[Tuple[str, float]] = []
            for sid in surro_ids:
                row = by_service.get(sid, {}).get(p)
                val = float(getattr(row, field, 0) or 0) if row is not None else 0.0
                scored.append((sid, val))
            scored.sort(key=lambda x: x[1], reverse=True)
            ranked = [
                MetricRankItem(surro_service_id=sid, name=name_map[sid], value=val)
                for sid, val in scored[:top_n]
            ]
            setattr(ptm, field, ranked)
        top[p] = ptm

    return MyServiceMonitoringResponse(
        member_id=member_id, source=source, top_n=top_n,  # type: ignore[arg-type]
        services=services_out, top=top, generated_at=datetime.utcnow(),
    )


# ============================================================
# Orchestrator (async) — route 진입점. 캐시 stale/미스 시 본인 서비스만 live 갱신.
# ============================================================

async def get_my_cards(db: Session, current_user: Any) -> MyServiceCardsResponse:
    """서비스 현황 카드. 캐시 우선, stale/미스 시 본인 서비스만 즉시 갱신(source=live)."""
    member_id = current_user.member_id
    surro_ids = [s.surro_service_id for s in _member_services(db, member_id)]
    if not surro_ids:
        return build_cards_response(db, member_id, source="cache")  # -> source="empty"

    source = "cache"
    if cards_need_refresh(db, surro_ids):
        try:
            await refresh_member_services_live(db, current_user)
            source = "live"
        except Exception:
            logger.exception("get_my_cards: live refresh failed; serving cached/partial data")
    return build_cards_response(db, member_id, source=source)


async def get_my_monitoring(
    db: Session, current_user: Any, *, top_n: int = 5
) -> MyServiceMonitoringResponse:
    """서비스 모니터링(1h/1d/1w + Top N). 캐시 우선, stale/미스 시 본인 서비스만 즉시 갱신."""
    member_id = current_user.member_id
    surro_ids = [s.surro_service_id for s in _member_services(db, member_id)]
    if not surro_ids:
        return build_monitoring_response(db, member_id, top_n=top_n, source="cache")  # -> "empty"

    source = "cache"
    if metrics_need_refresh(db, surro_ids):
        try:
            await refresh_member_services_live(db, current_user)
            source = "live"
        except Exception:
            logger.exception("get_my_monitoring: live refresh failed; serving cached/partial data")
    return build_monitoring_response(db, member_id, top_n=top_n, source=source)


# ============================================================
# 활동 히스토리 (audit_logs, k8s 이벤트 대체)
# ============================================================

def get_my_activities(
    db: Session,
    member_id: str,
    *,
    page: int = 1,
    size: int = 20,
    resource_type: Optional[str] = None,
    action: Optional[str] = None,
    since: Optional[datetime] = None,
) -> Tuple[List[AuditLog], int]:
    """본인(actor)이 수행한 활동 시계열. 반환: (rows, total)."""
    query = db.query(AuditLog).filter(AuditLog.actor_member_id == member_id)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if action:
        query = query.filter(AuditLog.action == action)
    if since:
        query = query.filter(AuditLog.created_at >= since)

    total = query.count()
    rows = (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )
    return rows, total
