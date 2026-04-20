import logging

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.cruds import experiment_crud
from app.database import get_db
from app.models import Member
from app.schemas.pipeline import (
    ModelRegistrationRequest,
    ModelRegistrationResponse,
    TrainingPipelineRequest,
    TrainingPipelineResponse,
    TrainingStatusResponse,
)
from app.services.pipeline_service import pipeline_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["Pipeline"])

# NOTE:
# This file is kept as a reference for the legacy gateway route design only.
# The gateway no longer exposes /api/v1/pipeline/* publicly. Public learning
# APIs are exposed only through /api/v1/learning/* in app.main.
#
# External MLOps still uses the legacy /pipeline endpoints for training creation
# and model registration. The gateway keeps these routes public because
# POST /pipeline/training is still where the external experiment_id is created.
# That experiment_id must be stored in the gateway experiments mapping table so
# the unified /learning domain can later enforce ownership and serve list/detail
# APIs consistently.
#
# If another developer re-enables this router in app.main, they are restoring
# a backward-compatibility alias, not the primary public API contract.


@router.post("/training", response_model=TrainingPipelineResponse, summary="Container Train")
async def submit_training(
    request: TrainingPipelineRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """
    학습 파이프라인 생성 및 실행

    모델과 데이터셋을 사용하여 Kubeflow Pipeline 기반의 학습 파이프라인을 생성하고 실행합니다.
    요청은 전체 Body(JSON)로 통일되며, 학습 시작 후 백그라운드에서 MLflow 메트릭 폴링이 시작됩니다.

    ## Response (TrainingPipelineResponse)
    - **experiment_id** (int | null): 생성된 학습 ID

    ## Notes
    - 외부 MLOps에는 기존 `/pipeline/training` API로 요청합니다.
    - 이 API는 새 `experiment_id`를 생성하는 진입점이므로 게이트웨이에서도 계속 유지합니다.
    - 학습 생성 성공 시 게이트웨이 DB의 `experiments` 매핑 테이블에 사용자 소유권 정보를 저장합니다.
    - 생성 이후의 목록/상세/수정/삭제는 `/api/v1/learning` 도메인 사용을 권장합니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 422: 요청 본문 검증 실패
    - 500: 서버 내부 오류
    """
    try:
        result = await pipeline_service.submit_training(
            data=request.model_dump(),
            user_info={
                "member_id": current_user.member_id,
                "role": current_user.role,
                "name": current_user.name,
            },
        )

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
                    dataset_id=request.dataset_id,
                )
                logger.info(
                    f"Created experiment mapping: surro_id={experiment_id}, member_id={current_user.member_id}"
                )
            except Exception as mapping_error:
                logger.warning(f"Failed to create experiment mapping: {str(mapping_error)}")

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting training for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to submit training: {str(e)}",
        )


@router.post("/model/registration", response_model=ModelRegistrationResponse, summary="Register Model")
async def register_model(
    request: ModelRegistrationRequest,
    current_user: Member = Depends(get_current_user),
):
    """
    학습 완료 모델 등록 파이프라인 실행

    학습이 완료된 모델을 등록하는 파이프라인을 실행합니다.
    기존 Query Parameter 방식이 아닌 Body(JSON) 기반 요청이며, 응답은 객체 형태로 반환됩니다.
    KFP run_id를 저장하고 백그라운드에서 등록 상태 폴링이 시작됩니다.

    ## Response (ModelRegistrationResponse)
    - **accepted** (bool): 파이프라인 접수 여부
    - **experiment_id** (int): 대상 학습 ID
    - **message** (str): 처리 결과 메시지

    ## Notes
    - 외부 MLOps에는 기존 `/pipeline/model/registration` API로 요청합니다.
    - 생성된 학습의 후속 등록 단계이므로 legacy `pipeline` 도메인에 유지합니다.
    - 학습 목록 및 상세 조회는 `/api/v1/learning` 사용을 권장합니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 422: 요청 본문 검증 실패
    - 500: 서버 내부 오류
    """
    try:
        result = await pipeline_service.register_model(
            data=request.model_dump(),
            user_info={
                "member_id": current_user.member_id,
                "role": current_user.role,
                "name": current_user.name,
            },
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error registering model for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to register model: {str(e)}",
        )


@router.get(
    "/training/{experiment_id}/status",
    response_model=TrainingStatusResponse,
    deprecated=True,
    summary="Get Training Status",
)
async def get_training_status(
    experiment_id: int = Path(..., description="학습 ID"),
    current_user: Member = Depends(get_current_user),
):
    """
    학습 상태 조회 (Deprecated)

    @deprecated — `GET /api/v1/learning/{experiment_id}` 또는 기존 `GET /api/v1/experiments/{experiment_id}` 사용 권장.

    기존 Path Parameter 방식의 학습 상태 조회입니다.
    하위 호환을 위해 유지하지만, 신규 연동에서는 learning 상세 조회 API 사용을 권장합니다.

    ## Path Parameters
    - **experiment_id** (int): 학습 ID

    ## Response (TrainingStatusResponse)
    - **status** (str): 학습 상태
    - **start_time** (int): 시작 시각 (Unix timestamp)
    - **end_time** (int | null): 종료 시각 (Unix timestamp)
    - **elapsed_time** (int): 경과 시간 (초)
    - **max_epoch** (int): 최대 epoch 수
    - **current_epoch** (int): 현재 epoch
    - **loss_history** (array): loss 이력
    - **epoch_history** (array): epoch 이력
    - **average_precision_50_history** (array): AP@50 이력
    - **average_precision_75_history** (array): AP@75 이력
    - **best_average_precision_history** (array): Best AP 이력
    - **average_precision_50_95_history** (array): AP@50:95 이력

    ## Notes
    - 외부 MLOps에는 기존 `/pipeline/training/{experiment_id}/status` API로 요청합니다.
    - 이 경로는 하위 호환 전용입니다.
    - 신규 화면/연동은 `/api/v1/learning/{experiment_id}` 사용을 권장합니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 학습을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        result = await pipeline_service.get_training_status(
            experiment_id=experiment_id,
            user_info={
                "member_id": current_user.member_id,
                "role": current_user.role,
                "name": current_user.name,
            },
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting training status: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get training status: {str(e)}",
        )
