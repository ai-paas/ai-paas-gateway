"""개인사용자 대시보드 API.

권한: 일반 사용자 본인 (`get_current_user`).
인프라/타 사용자 정보 제외, 본인 `created_by` 자산만 집계.
"""
import logging

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Member
from app.schemas.dashboard import PersonalDashboardSummary
from app.services import dashboard_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me/dashboard", tags=["My - Dashboard"])


_USER_ERRORS = {
    401: {"description": "토큰 누락/만료/무효"},
}


@router.get(
    "/summary",
    response_model=PersonalDashboardSummary,
    summary="내 대시보드 KPI 요약 (본인 자산만)",
    responses=_USER_ERRORS,
)
def get_my_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """현재 로그인 사용자가 만든 8개 도메인 자산 카운트.

    ## 응답 구성
    - `member_id` — 현재 사용자 식별자
    - **services / workflows / models / model_improvements / datasets / experiments
      / knowledge_bases / prompts** — 본인 `created_by` 자산만 집계한 `AssetCount`
    - `generated_at` — 응답 생성 시각 (UTC)

    ## 관리자 대시보드와의 차이
    - **본인 자산만** — admin이라도 이 endpoint는 본인 `created_by` 자산만 응답.
      전체 조회는 `GET /api/v1/admin/dashboard/summary` 사용.
    - `users` 섹션 없음 — 사용자 카운트는 admin 전용.
    - `infra` 섹션 없음 — 인프라는 admin 전용.

    ## AssetCount 의미
    - `active`   = `deleted_at IS NULL AND is_active IS TRUE` (soft-delete 없는 도메인은 = total)
    - `inactive` = `deleted_at IS NULL AND is_active IS FALSE`
    - `deleted`  = `deleted_at IS NOT NULL`
    - `total` = `active + inactive + deleted`

    > `service`, `workflow`는 soft-delete가 없어 항상 `inactive=0, deleted=0`.
    """
    return dashboard_service.build_summary_for_member(db, current_user.member_id)
