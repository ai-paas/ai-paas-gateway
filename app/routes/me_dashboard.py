"""개인사용자 대시보드 API.

권한: 일반 사용자 본인 ( `get_current_user` ).
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


@router.get("/summary", response_model=PersonalDashboardSummary)
def get_my_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """본인 보유 자산 카운트.

    8개 도메인 (Service/Workflow/Model/ModelImprovement/Dataset/Experiment/KnowledgeBase/Prompt)을
    `created_by == current_user.member_id` 기준으로 집계.
    soft-delete 도메인은 active/inactive/deleted 3분할.
    """
    return dashboard_service.build_summary_for_member(db, current_user.member_id)
