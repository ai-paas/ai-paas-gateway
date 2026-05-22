"""관리자 대시보드 API.

권한: admin 전용 (`get_current_admin_user`).
응답: summary/top/infra 류는 단일 객체 (페이지네이션 wrapper 미적용),
events는 리스트 응답이라 public pagination 규약(`{data,total,page,size}`) 적용.
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_admin_user
from app.database import get_db
from app.models.audit_log import AuditLog
from app.schemas.dashboard import (
    ApiMetricsPathItem,
    ApiMetricsResponse,
    AuditEventItem,
    AuditEventListResponse,
    DashboardSummary,
    DomainLiteral,
    InfraNodesResponse,
    InfraResourcesResponse,
    InfraStatusResponse,
    ProviderHealthHistoryPoint,
    ProviderHealthLatest,
    ProviderHealthResponse,
    ResourceTypeLiteral,
    TrendsRefreshResponse,
    TrendsResponse,
    UsersTopResponse,
)
from app.services import (
    api_metrics_service,
    dashboard_service,
    infra_adapter,
    provider_health_service,
    trends_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/dashboard", tags=["Admin - Dashboard"])


@router.get("/summary", response_model=DashboardSummary)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """관리자 대시보드 KPI 일괄.

    - 8개 자산 도메인 카운트 (`service`, `workflow`, `model`, `model_improvement`,
      `dataset`, `experiment`, `knowledge_base`, `prompt`)
    - soft-delete 도메인은 `active`/`inactive`/`deleted` 분리, 없는 도메인은 `active=total`
    - 사용자 5종 (`total`/`active`/`inactive`/`recent7d`/`by_role`)
    """
    return dashboard_service.build_summary(db)


@router.get("/users/top", response_model=UsersTopResponse)
def get_users_top(
    domain: DomainLiteral = Query(..., description="자산 도메인"),
    size: int = Query(3, ge=1, le=10, description="상위 N명 (size)"),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """도메인별 보유 자산 상위 사용자."""
    items = dashboard_service.top_users_by_domain(db, domain, size)
    return UsersTopResponse(domain=domain, items=items)


@router.get("/infra/status", response_model=InfraStatusResponse)
async def get_infra_status(
    _: None = Depends(get_current_admin_user),
):
    """Any Cloud 클러스터 연결 상태.

    클러스터 미등록 시 `has_data=False`로 empty state 표시.
    현재 Any Cloud 연동이 미정이라 샘플 데이터를 반환한다.
    """
    return await infra_adapter.get_infra_status()


@router.get("/infra/nodes", response_model=InfraNodesResponse)
async def get_infra_nodes(
    cluster: str = Query(..., description="클러스터 이름"),
    _: None = Depends(get_current_admin_user),
):
    """클러스터 내 노드 상태 + 노드별 리소스.

    `accelerators[]` 배열에 `kind=gpu|npu|tpu|other`로 가속기 확장 대응.
    가속기 미연동 항목은 `status=not_available` placeholder.
    """
    return await infra_adapter.get_infra_nodes(cluster)


@router.get("/infra/resources", response_model=InfraResourcesResponse)
async def get_infra_resources(
    cluster: str = Query(..., description="클러스터 이름"),
    resource_type: ResourceTypeLiteral = Query(..., description="cpu/memory/filesystem/accelerator"),
    _: None = Depends(get_current_admin_user),
):
    """노드별 특정 리소스 추출.

    `resource_type=accelerator` 한 번으로 GPU/NPU/TPU 전체 회수.
    upstream(Any Cloud)의 `type/key` 키워드는 adapter 내부에서 변환되어 노출되지 않는다.
    """
    return await infra_adapter.get_infra_resources(cluster, resource_type)


@router.get("/events", response_model=AuditEventListResponse)
def get_dashboard_events(
    page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
    size: int = Query(20, ge=1, le=200, description="페이지 크기"),
    resource_type: Optional[str] = Query(None, description="resource_type 필터"),
    action: Optional[str] = Query(None, description="action 필터 (create/update/delete/...)"),
    actor: Optional[str] = Query(None, description="actor_member_id 필터"),
    since: Optional[datetime] = Query(None, description="이 시각 이후 이벤트만 (ISO 8601)"),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """관리자 활동 피드 — audit_logs 조회.

    최신순(`created_at DESC`) 기본. resource_type/action/actor/since 필터 조합.
    """
    query = db.query(AuditLog)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor_member_id == actor)
    if since:
        query = query.filter(AuditLog.created_at >= since)

    total = query.count()
    rows = (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = [
        AuditEventItem(
            id=r.id,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            actor_member_id=r.actor_member_id,
            target_member_id=r.target_member_id,
            metadata_json=r.metadata_json,
            request_id=r.request_id,
            ip=r.ip,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AuditEventListResponse(data=items, total=total, page=page, size=size)


# ---------- Trends ----------

@router.get("/trends", response_model=TrendsResponse)
def get_dashboard_trends(
    days: int = Query(30, ge=1, le=365, description="과거 N일 범위 (기본 30)"),
    domain: Optional[str] = Query(None, description="단일 도메인 필터 (service/workflow/.../signup)"),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """일별 자산 생성/삭제 + 가입자 추이.

    소스 우선순위: `daily_stats` 테이블 → 실시간 raw 집계.
    domain 미지정 시 8개 도메인 + signup 모두 series로 반환.
    """
    try:
        return trends_service.get_trends(db, days=days, domain=domain)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/trends/refresh", response_model=TrendsRefreshResponse)
def refresh_dashboard_trends(
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """관리자 수동 갱신 — raw 집계를 `daily_stats`에 upsert하고 mat view를 REFRESH.

    스케줄러(ENABLE_SCHEDULER=false) 미사용 환경의 보조 갱신 경로.
    """
    from datetime import datetime

    rows = trends_service.refresh_daily_stats(db)
    refreshed_mv = db.bind.dialect.name == "postgresql"
    return TrendsRefreshResponse(
        rows_upserted=rows,
        refreshed_materialized_view=refreshed_mv,
        finished_at=datetime.utcnow(),
    )


# ---------- API metrics ----------

@router.get("/api-metrics", response_model=ApiMetricsResponse)
def get_dashboard_api_metrics(
    hours: int = Query(24, ge=1, le=168, description="최근 N시간 범위 (기본 24)"),
    path_pattern: Optional[str] = Query(None, description="path_pattern 필터"),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """경로별·상태코드별 호출 수 + 평균/최대/p95(근사) 응답시간.

    수집은 RequestLoggingMiddleware → in-memory buffer → 스케줄러 flush(`api_request_histograms`).
    p95는 Prometheus-like histogram bucket 보간이라 정확값 아님.
    """
    from datetime import datetime, timedelta

    since = datetime.utcnow() - timedelta(hours=hours)
    raw = api_metrics_service.get_api_metrics(db, since=since, path_pattern=path_pattern)
    return ApiMetricsResponse(
        since=raw["since"],
        generated_at=raw["generated_at"],
        buckets_ms=raw["buckets_ms"],
        paths=[ApiMetricsPathItem(**p) for p in raw["paths"]],
    )


@router.post("/api-metrics/flush", response_model=dict)
def flush_dashboard_api_metrics(
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """관리자 수동 flush — in-memory buffer를 즉시 DB에 반영.

    스케줄러 미사용 환경에서 디버깅/즉시 확인용.
    """
    n = api_metrics_service.flush_buffered_buckets(db)
    return {"flushed": n}


# ---------- Provider health ----------

@router.get("/providers/health", response_model=ProviderHealthResponse)
def get_dashboard_providers_health(
    history_minutes: int = Query(60, ge=1, le=1440, description="최근 N분 시계열 (기본 60)"),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """provider별 최신 헬스 + 최근 N분 시계열.

    스케줄러가 `provider_health_snapshots`를 매 분 기록. 미연동 provider는 status=disabled.
    """
    from datetime import datetime, timedelta

    from app.models.api_metric import ProviderHealthSnapshot

    since = datetime.utcnow() - timedelta(minutes=history_minutes)

    # 각 provider별 최신 1건
    sub = (
        db.query(
            ProviderHealthSnapshot.provider,
            func.max(ProviderHealthSnapshot.ts).label("max_ts"),
        )
        .group_by(ProviderHealthSnapshot.provider)
        .subquery()
    )
    latest_rows = (
        db.query(ProviderHealthSnapshot)
        .join(
            sub,
            (ProviderHealthSnapshot.provider == sub.c.provider)
            & (ProviderHealthSnapshot.ts == sub.c.max_ts),
        )
        .all()
    )

    latest = [
        ProviderHealthLatest(
            provider=r.provider,
            status=r.status,  # type: ignore[arg-type]
            latency_ms=r.latency_ms,
            error=r.error,
            last_checked_at=r.ts,
        )
        for r in latest_rows
    ]

    # 시계열
    history_rows = (
        db.query(ProviderHealthSnapshot)
        .filter(ProviderHealthSnapshot.ts >= since)
        .order_by(ProviderHealthSnapshot.provider, ProviderHealthSnapshot.ts)
        .all()
    )
    history: Dict[str, List[ProviderHealthHistoryPoint]] = {}
    for r in history_rows:
        history.setdefault(r.provider, []).append(
            ProviderHealthHistoryPoint(ts=r.ts, status=r.status, latency_ms=r.latency_ms)
        )

    return ProviderHealthResponse(providers=latest, history=history, generated_at=datetime.utcnow())


@router.post("/providers/health/probe", response_model=ProviderHealthResponse)
def trigger_provider_probe(
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """관리자 수동 probe — 즉시 호출해 snapshot 1건 기록 후 응답."""
    from datetime import datetime

    results = provider_health_service.probe_all_and_record(db)
    latest = [
        ProviderHealthLatest(
            provider=r.provider,
            status=r.status,  # type: ignore[arg-type]
            latency_ms=r.latency_ms,
            error=r.error,
            last_checked_at=datetime.utcnow(),
        )
        for r in results
    ]
    return ProviderHealthResponse(providers=latest, history={}, generated_at=datetime.utcnow())
