from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.orm import Session
from typing import List
import logging

from app.database import get_db
from app.auth import get_current_user
from app.cruds import experiment_crud
from app.schemas.experiment import ExperimentListItem, ExperimentDetailResponse
from app.services.experiment_service import experiment_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["Experiments"])


@router.get("", response_model=List[ExperimentListItem])
async def list_experiments(
        skip: int = Query(0, ge=0, description="건너뛸 항목 수"),
        limit: int = Query(100, ge=1, le=1000, description="반환할 최대 항목 수"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    학습 실험 목록 조회

    - 현재 사용자의 학습 실험 목록을 반환합니다.
    """
    try:
        # 사용자 소유 실험 ID set 조회
        owned_ids = set(experiment_crud.get_experiments_by_member_id(db, current_user.member_id))

        # 매핑이 없으면 빈 리스트 반환
        if not owned_ids:
            return []

        # 외부 API에서 실험 목록 조회 (넉넉하게 가져와서 Gateway에서 필터링)
        all_experiments = await experiment_service.list_experiments(
            skip=0,
            limit=1000,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 사용자 소유 실험만 필터링
        filtered = [exp for exp in all_experiments if exp.get('id') in owned_ids]

        # Gateway에서 skip/limit 적용
        result = filtered[skip:skip + limit]
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing experiments for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list experiments: {str(e)}"
        )


@router.get("/{experiment_id}", response_model=ExperimentDetailResponse)
async def get_experiment(
        experiment_id: int = Path(..., description="실험 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    학습 실험 상세 조회

    - 단일 실험의 상세 정보를 반환합니다.
    - 학습 메트릭(loss 히스토리, AP, accuracy, precision, recall 등)을 포함합니다.
    """
    try:
        # 소유권 검증
        if not experiment_crud.check_ownership(db, experiment_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Experiment not found or access denied"
            )

        result = await experiment_service.get_experiment(
            experiment_id=experiment_id,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting experiment {experiment_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get experiment: {str(e)}"
        )
