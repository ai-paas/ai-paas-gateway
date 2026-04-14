from fastapi import APIRouter, Depends, HTTPException, status, Path
from sqlalchemy.orm import Session
import logging

from app.database import get_db
from app.auth import get_current_user
from app.cruds import experiment_crud
from app.schemas.pipeline import (
    TrainingPipelineRequest, TrainingPipelineResponse,
    ModelRegistrationRequest, ModelRegistrationResponse,
    TrainingStatusResponse
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

    모델과 데이터셋을 사용하여 Kubeflow Pipeline 기반의 학습 파이프라인을 생성하고 실행합니다.
    요청은 전체 Body(JSON)로 통일되며, 학습 시작 후 백그라운드에서 MLflow 메트릭 폴링이 시작됩니다.

    ## Request Body (application/json) — `TrainingRequest`

    | 필드 | 타입 | 필수 | 기본값 | 설명 |
    |------|------|------|--------|------|
    | `model_id` | integer | ✅ | — | 학습에 사용할 모델 ID |
    | `dataset_id` | integer | ✅ | — | 학습에 사용할 데이터셋 ID |
    | `train_name` | string | — | `""` | 학습 실험 이름 |
    | `description` | string | — | `""` | 학습 실험 설명 |
    | `gpus` | string | — | `"1"` | 사용할 GPU 개수 |
    | `batch_size` | string | — | `"32"` | 배치 크기 |
    | `epochs` | string | — | `"5"` | 학습 에포크 수 |
    | `save_period` | string | — | `"1"` | 모델 저장 주기 (에포크 단위) |
    | `weight_decay` | string | — | `"5e-4"` | 가중치 감쇠 계수 |
    | `lr0` | string | — | `"0.01"` | 초기 학습률 |
    | `lrf` | string | — | `"0.05"` | 최종 학습률 |

    ## Response (200)

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `experiment_id` | integer \\| null | 생성된 실험의 고유 ID |
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
    학습 완료된 모델 등록 파이프라인 실행

    Query Parameter → Body(JSON) 변경. 응답이 객체로 확장되었으며,
    KFP run_id를 DB에 저장하고 백그라운드에서 등록 상태 폴링이 시작됩니다.

    ## Request Body (application/json) — `ModelRegistrationRequest`

    | 필드 | 타입 | 필수 | 설명 |
    |------|------|------|------|
    | `model_name` | string | ✅ | 등록될 모델 표시 이름 |
    | `description` | string | ✅ | 모델 설명 |
    | `experiment_id` | integer | ✅ | 대상 학습 실험 ID |

    ## Response (200) — `ModelRegistrationResponse`

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `accepted` | boolean | 파이프라인 제출 수락 여부 |
    | `experiment_id` | integer | 요청 실험 ID |
    | `message` | string | 안내 메시지 |
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


@router.get("/training/{experiment_id}/status", response_model=TrainingStatusResponse, deprecated=True)
async def get_training_status(
        experiment_id: int = Path(..., description="실험 ID"),
        current_user: Member = Depends(get_current_user)
):
    """
    학습 상태 조회 (Deprecated)

    @deprecated — GET /api/v1/experiments/{experiment_id} 사용 권장.

    기존 Path Parameter 방식의 학습 상태 조회. 하위 호환을 위해 유지합니다.

    ## Path Parameter

    | 필드 | 타입 | 설명 |
    |------|------|------|
    | `experiment_id` | integer | 실험 ID |

    ## Response (200) — `TrainingStatusResponse`

    | 필드 | 타입 | 필수 | 설명 |
    |------|------|------|------|
    | `status` | string | ✅ | 학습 상태 |
    | `start_time` | integer | ✅ | 시작 시간 (Unix timestamp) |
    | `end_time` | integer \\| null | — | 종료 시간 (Unix timestamp) |
    | `elapsed_time` | integer | ✅ | 경과 시간 (초) |
    | `max_epoch` | integer | ✅ | 최대 에포크 수 |
    | `current_epoch` | integer | ✅ | 현재 에포크 |
    | `loss_history` | array | ✅ | 손실 히스토리 |
    | `epoch_history` | array | ✅ | 에포크 히스토리 |
    | `average_precision_50_history` | array | ✅ | AP@50 히스토리 |
    | `average_precision_75_history` | array | ✅ | AP@75 히스토리 |
    | `best_average_precision_history` | array | ✅ | Best AP 히스토리 |
    | `average_precision_50_95_history` | array | ✅ | AP@50:95 히스토리 |
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
