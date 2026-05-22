"""관리자 대시보드 API.

권한: admin 전용 (`get_current_admin_user`).
응답: summary/top/infra 류는 단일 객체 (페이지네이션 wrapper 미적용),
events는 리스트 응답이라 public pagination 규약(`{data,total,page,size}`) 적용.
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_admin_user
from app.database import get_db
from app.models.audit_log import AuditLog
from app.schemas.dashboard import (
    AuditEventItem,
    AuditEventListResponse,
    DashboardSummary,
    DomainLiteral,
    InfraNodesResponse,
    InfraResourcesResponse,
    InfraStatusResponse,
    ResourceTypeLiteral,
    UsersTopResponse,
)
from app.services import dashboard_service, infra_adapter

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
