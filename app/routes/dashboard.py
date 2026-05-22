"""관리자 대시보드 API.

권한: admin 전용 (`get_current_admin_user`).
응답: summary/top/infra 류는 단일 객체 (페이지네이션 wrapper 미적용).
"""
import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_admin_user
from app.database import get_db
from app.schemas.dashboard import (
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
    - soft-delete 도메인은 `active`/`deleted` 분리, 없는 도메인은 `active=total`
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
