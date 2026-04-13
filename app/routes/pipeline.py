from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.orm import Session
import logging

from app.database import get_db
from app.auth import get_current_user
from app.cruds import experiment_crud
from app.schemas.pipeline import (
    TrainingPipelineRequest, TrainingPipelineResponse,
    ModelRegistrationRequest, ModelRegistrationResponse
)
from app.services.pipeline_service import pipeline_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])


@router.post("/training", response_model=TrainingPipelineResponse)
async def submit_training(
        request: TrainingPipelineRequest,
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    학습 파이프라인 생성 및 실행

    - 모델과 데이터셋을 사용하여 Kubeflow Pipeline 기반의 학습 파이프라인을 생성하고 실행합니다.
    """
    try:
        # 외부 API에 학습 파이프라인 제출
        result = await pipeline_service.submit_training(
            data=request.model_dump(),
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # Gateway DB에 실험 매핑 저장
        experiment_id = result.get("experiment_id")
        if experiment_id:
            try:
                experiment_crud.create_mapping(
                    db=db,
                    surro_experiment_id=experiment_id,
                    member_id=current_user.member_id,
                    name=request.train_name,
                    description=request.description,
                    model_id=request.model_id,
                    dataset_id=request.dataset_id
                )
                logger.info(f"Created experiment mapping: surro_id={experiment_id}, member_id={current_user.member_id}")
            except Exception as mapping_error:
                logger.warning(f"Failed to create experiment mapping: {str(mapping_error)}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting training for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit training: {str(e)}"
        )


@router.post("/model/registration", response_model=ModelRegistrationResponse)
async def register_model(
        request: ModelRegistrationRequest,
        current_user: Member = Depends(get_current_user)
):
    """
    학습 완료 모델 등록 파이프라인 제출

    - 학습이 끝난 실험의 산출물을 모델 레지스트리에 등록하기 위한 파이프라인을 제출합니다.
    """
    try:
        result = await pipeline_service.register_model(
            data=request.model_dump(),
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
        logger.error(f"Error registering model for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register model: {str(e)}"
        )


@router.get("/training/{experiment_id}/status", deprecated=True)
async def get_training_status(
        experiment_id: int = Path(..., description="실험 ID"),
        current_user: Member = Depends(get_current_user)
):
    """
    학습 상태 조회 (Deprecated)

    - 이 엔드포인트는 deprecated 되었습니다.
    - GET /api/v1/experiments/{experiment_id} 를 사용해주세요.
    """
    try:
        result = await pipeline_service.get_training_status(
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
        logger.error(f"Error getting training status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get training status: {str(e)}"
        )
