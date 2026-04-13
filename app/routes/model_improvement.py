from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import logging

from app.database import get_db
from app.auth import get_current_user
from app.cruds import model_improvement_crud, model_crud
from app.schemas.model_improvement import (
    ModelImprovementRequest, ModelImprovementResponse,
    ModelImprovementStatusResponse, TaskTypeResponse
)
from app.services.model_improvement_service import model_improvement_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/model-improvements", tags=["Model Improvements"])


@router.post("", response_model=ModelImprovementResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_improvement(
        request: ModelImprovementRequest,
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 최적화/경량화 task 생성

    - opt_enable_yn=true인 소스 모델에 대해 최적화/경량화 task를 큐에 올립니다.
    - 비동기 처리이며, task_id로 상태를 조회합니다.
    """
    try:
        # 사용자가 해당 모델을 소유하고 있는지 확인
        if not model_crud.check_model_ownership(db, request.source_model_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model {request.source_model_id} not found or access denied"
            )

        # 외부 API에 task 제출
        result = await model_improvement_service.submit_improvement(
            data=request.model_dump(),
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # Gateway DB에 매핑 저장
        task_id = result.get("task_id")
        if task_id:
            try:
                model_improvement_crud.create_mapping(
                    db=db,
                    task_id=task_id,
                    source_model_id=request.source_model_id,
                    task_type=request.task_type,
                    member_id=current_user.member_id
                )
                logger.info(f"Created improvement mapping: task_id={task_id}, member_id={current_user.member_id}")
            except Exception as mapping_error:
                logger.warning(f"Failed to create improvement mapping: {str(mapping_error)}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting improvement for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit improvement: {str(e)}"
        )


@router.get("/status", response_model=ModelImprovementStatusResponse)
async def get_improvement_status(
        task_id: str = Query(..., description="task UUID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 최적화/경량화 task 상태 조회
    """
    try:
        # 소유권 검증 (명세 6.2: 타 사용자 task 조회 시 403)
        if not model_improvement_crud.check_ownership(db, task_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this task"
            )

        result = await model_improvement_service.get_status(
            task_id=task_id,
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
        logger.error(f"Error getting improvement status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get improvement status: {str(e)}"
        )


@router.get("/task-types", response_model=List[TaskTypeResponse])
async def get_task_types(
        category: Optional[str] = Query(None, description="카테고리 필터 (optimization, lightweight)"),
        current_user: Member = Depends(get_current_user)
):
    """
    최적화/경량화 task_type 목록 조회
    """
    try:
        result = await model_improvement_service.get_task_types(
            category=category,
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
        logger.error(f"Error getting task types: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get task types: {str(e)}"
        )
