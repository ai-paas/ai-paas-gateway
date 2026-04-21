import asyncio
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session

from app.auth import get_current_admin_user, get_current_user
from app.cruds import experiment_crud
from app.database import get_db
from app.models import Member
from app.schemas.experiment import (
    ExperimentDetailResponse,
    ExperimentInternalUpdateRequest,
    ExperimentListItem,
    ExperimentListResponse,
    ExperimentReadResponse,
    ExperimentUpdateRequest,
)
from app.schemas.pipeline import (
    ModelRegistrationRequest,
    ModelRegistrationResponse,
    TrainingPipelineRequest,
    TrainingPipelineResponse,
    TrainingStatusResponse,
)
from app.services.experiment_service import experiment_service
from app.services.pipeline_service import pipeline_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/learning", tags=["Learning"])
SEARCH_DETAIL_CONCURRENCY = 5


def _create_pagination_response(data, total: int, page: int, size: int):
    return {
        "data": data,
        "total": total,
        "page": page,
        "size": size,
    }


async def _fetch_learning_details(
    experiment_ids: List[int],
    current_user: Member,
) -> List[dict]:
    semaphore = asyncio.Semaphore(SEARCH_DETAIL_CONCURRENCY)

    async def _fetch_one(experiment_id: int):
        async with semaphore:
            try:
                return await experiment_service.get_experiment(
                    experiment_id=experiment_id,
                    user_info={
                        "member_id": current_user.member_id,
                        "role": current_user.role,
                        "name": current_user.name,
                    },
                )
            except Exception as detail_error:
                logger.warning(
                    f"Failed to fetch learning detail for experiment {experiment_id}: {str(detail_error)}"
                )
                return None

    results = await asyncio.gather(*[_fetch_one(experiment_id) for experiment_id in experiment_ids])
    return [result for result in results if result is not None]


async def _sync_external_experiments_for_admin(db: Session, current_user: Member) -> set[int]:
    # External MLOps still exposes training through the legacy pipeline/experiments APIs.
    # The gateway keeps a local experiments mapping table so the frontend can use the
    # unified learning domain while ownership checks remain gateway-controlled.
    owned_ids = set(experiment_crud.get_experiments_by_member_id(db, current_user.member_id))

    if current_user.role != "admin":
        return owned_ids

    all_experiments = await experiment_service.list_experiments(
        skip=0,
        limit=1000,
        user_info={
            "member_id": current_user.member_id,
            "role": current_user.role,
            "name": current_user.name,
        },
    )

    missing = [exp for exp in all_experiments if exp.get("id") not in owned_ids]
    for exp in missing:
        exp_id = exp.get("id")
        if not exp_id:
            continue
        try:
            reference_model = exp.get("reference_model") or {}
            dataset = exp.get("dataset") or {}
            experiment_crud.create_mapping(
                db=db,
                surro_experiment_id=exp_id,
                member_id=current_user.member_id,
                name=exp.get("name"),
                description=exp.get("description"),
                model_id=reference_model.get("id") or exp.get("reference_model_id"),
                dataset_id=dataset.get("id") or exp.get("dataset_id"),
            )
            owned_ids.add(exp_id)
            logger.info(
                f"Registered missing experiment under admin ({current_user.member_id}): surro_id={exp_id}"
            )
        except Exception as sync_error:
            logger.warning(f"Failed to sync external experiment {exp_id}: {str(sync_error)}")

    return owned_ids


@router.get(
    "",
    response_model=ExperimentListResponse,
    summary="List Learning",
    description="""
학습 목록 조회

파이프라인 학습 실행으로 생성된 학습 항목의 목록을 반환합니다.
게이트웨이에서 사용자 소유 학습만 필터링한 뒤 페이지네이션하여 응답합니다.

## Query Parameters
- **page** (int, optional): 페이지 번호
  - 기본값: `1`
  - 최소값: `1`
- **size** (int, optional): 페이지당 항목 수
  - 기본값: `20`
  - 범위: `1-100`

## Response (ExperimentListResponse)
- **data** (List[ExperimentListItem]): 학습 목록
- **total** (int): 전체 항목 수
- **page** (int): 현재 페이지 번호
- **size** (int): 페이지당 항목 수

`data`의 각 항목은 다음 정보를 포함합니다.
- **id** (int): 학습 ID
- **name** (str): 학습 이름
- **description** (str, optional): 학습 설명
- **status** (str): 학습 상태
- **registration_status** (str): 모델 등록 상태
- **registered_model_id** (int | null): 등록된 모델 ID
- **elapsed_time** (int): 경과 시간
- **end_time** (datetime | null): 종료 시각
- **reference_model**: 참조 모델 요약 정보
- **dataset**: 데이터셋 요약 정보
- **created_at** (datetime): 생성 시각
- **updated_at** (datetime): 수정 시각

## Notes
- 외부 MLOps 실험 목록을 게이트웨이에서 사용자 소유 기준으로 필터링한 뒤 응답합니다.

## Errors
- 401: 인증되지 않은 사용자
- 500: 서버 내부 오류
""",
)
async def list_learning(
    page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
    size: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
    search: Optional[str] = Query(None, description="검색어 (이름, 설명)"),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """
    학습 목록 조회

    파이프라인 학습 실행으로 생성된 학습 항목의 목록을 반환합니다.
    게이트웨이에서 사용자 소유 학습만 필터링한 뒤, 프론트엔드와 약속된 `skip`/`limit` 방식으로 페이지네이션하여 응답합니다.

    ## Query Parameters
    - **skip** (int, optional): 건너뛸 항목 수
        - 기본값: `0`
        - 최소값: `0`
    - **limit** (int, optional): 반환할 최대 항목 수
        - 기본값: `100`
        - 범위: `1-1000`

    ## Response (ExperimentListResponse)
    - **data** (List[ExperimentListItem]): 학습 목록
    - **total** (int): 전체 항목 수
    - **page** (int): 현재 페이지 번호
    - **size** (int): 페이지당 항목 수

    `data`의 각 항목은 다음 정보를 포함합니다.
    - **id** (int): 학습 ID
    - **name** (str): 학습 이름
    - **description** (str, optional): 학습 설명
    - **status** (str): 학습 상태
    - **model registration status 관련 요약 정보**
    - **경과 시간, 종료 시간 등 요약 정보**

    ## Notes
    - 외부 MLOps API의 실험 목록을 게이트웨이에서 사용자 기준으로 필터링한 후 응답합니다.
    - 프론트엔드 연동 규약에 따라 게이트웨이에서는 `skip`/`limit` 방식 페이지네이션을 유지합니다.
    - 외부 API의 페이지 파라미터 형식은 게이트웨이 내부에서만 사용되며 프론트엔드에 그대로 노출하지 않습니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 500: 서버 내부 오류
    """
    try:
        skip = (page - 1) * size
        owned_ids = await _sync_external_experiments_for_admin(db, current_user)

        if search:
            local_matches, total = experiment_crud.search_experiments_by_member_id(
                db=db,
                member_id=current_user.member_id,
                skip=skip,
                limit=size,
                search=search,
            )
            if not local_matches:
                return _create_pagination_response([], total, page, size)

            page_ids = [exp.surro_experiment_id for exp in local_matches if exp.surro_experiment_id]
            details = await _fetch_learning_details(page_ids, current_user)

            for detail in details:
                if detail.get("id") is None:
                    continue
                experiment_crud.update_mapping(
                    db=db,
                    surro_experiment_id=detail["id"],
                    member_id=current_user.member_id,
                    update_data={
                        "name": detail.get("name"),
                        "description": detail.get("description"),
                    },
                )

            detail_by_id = {
                detail["id"]: detail
                for detail in details
                if detail.get("id") is not None
            }
            ordered = [detail_by_id[experiment_id] for experiment_id in page_ids if experiment_id in detail_by_id]
            return _create_pagination_response(ordered, total, page, size)

        if not owned_ids:
            return _create_pagination_response([], 0, page, size)

        all_experiments = await experiment_service.list_experiments(
            skip=0,
            limit=1000,
            user_info={
                "member_id": current_user.member_id,
                "role": current_user.role,
                "name": current_user.name,
            },
        )

        filtered = [exp for exp in all_experiments if exp.get("id") in owned_ids]
        total = len(filtered)
        return _create_pagination_response(filtered[skip:skip + size], total, page, size)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing learning items for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to list learning items: {str(e)}",
        )


@router.post("/training", response_model=TrainingPipelineResponse, summary="Submit Training")
async def submit_training(
    request: TrainingPipelineRequest,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """
    학습 파이프라인 생성 및 실행

    모델과 데이터셋을 사용하여 Kubeflow Pipeline 기반의 학습 파이프라인을 생성하고 실행합니다.
    요청은 전체 Body(JSON)로 전달되며, 학습 시작 후 백그라운드에서 MLflow 메트릭 폴링이 시작됩니다.

    ## Response (TrainingPipelineResponse)
    - **experiment_id** (int | null): 생성된 학습 ID

    ## Notes
    - 외부 MLOps API에는 기존 pipeline 학습 API로 요청하지만, 게이트웨이에서는 learning 도메인으로 통합하여 제공합니다.
    - 학습 생성 성공 시 게이트웨이 DB에 사용자-학습 매핑 정보를 함께 저장합니다.

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
    - 외부 MLOps API에는 기존 pipeline 모델 등록 API로 요청합니다.
    - 게이트웨이에서는 learning 도메인 하위의 모델 등록 흐름으로 통합 제공됩니다.

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
    "/{experiment_id}/status",
    response_model=TrainingStatusResponse,
    deprecated=True,
    summary="Get Training Status",
)
async def get_training_status(
    experiment_id: int = Path(..., description="Learning ID"),
    current_user: Member = Depends(get_current_user),
):
    """
    학습 상태 조회 (Deprecated)

    `GET /api/v1/learning/{experiment_id}` 사용을 권장합니다.
    기존 상태 전용 조회 경로와의 하위 호환을 위해 유지합니다.

    ## Path Parameters
    - **experiment_id** (int): 학습 ID

    ## Response (TrainingStatusResponse)
    - **status** (str): 학습 상태
    - **start_time** (int): 시작 시각 (Unix timestamp)
    - **end_time** (int, optional): 종료 시각 (Unix timestamp)
    - **elapsed_time** (int): 경과 시간(초)
    - **max_epoch** (int): 최대 epoch 수
    - **current_epoch** (int): 현재 epoch
    - **loss_history** (array): loss 이력
    - **epoch_history** (array): epoch 이력
    - **average_precision_50_history** (array): AP@50 이력
    - **average_precision_75_history** (array): AP@75 이력
    - **best_average_precision_history** (array): Best AP 이력
    - **average_precision_50_95_history** (array): AP@50:95 이력

    ## Notes
    - 게이트웨이 내부에서는 기존 pipeline 상태 조회 API를 그대로 호출합니다.
    - 신규 연동은 상세 조회 API 사용을 권장합니다.

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


@router.patch(
    "/{experiment_id}/internal-access",
    response_model=ExperimentReadResponse,
    summary="Update Learning Internal",
)
async def update_learning_internal(
    experiment_id: int = Path(..., description="Learning ID to update internally"),
    update_data: ExperimentInternalUpdateRequest = ...,
    current_user: Member = Depends(get_current_admin_user),
):
    """
    내부 통신 전용 학습 정보 수정 API

    시스템 내부 통신에서 사용하는 API로, `status`, `mlflow_run_id`, `kubeflow_run_id`를 수정할 수 있습니다.
    관리자 권한이 필요합니다.

    ## Path Parameters
    - **experiment_id** (int): 수정할 학습 ID

    ## Response (ExperimentReadResponse)
    - 학습의 전체 정보를 반환합니다.

    ## Notes
    - 내부 상태 동기화 용도입니다.
    - 외부 MLOps API에는 기존 experiments internal-access API로 요청합니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 403: 관리자 권한 필요
    - 404: 학습을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        user_info = {
            "member_id": current_user.member_id,
            "role": current_user.role,
            "name": current_user.name,
        }
        update_payload = update_data.model_dump(exclude_unset=True)

        result = await experiment_service.update_experiment_internal(
            experiment_id=experiment_id,
            update_data=update_payload,
            user_info=user_info,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating learning internal {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update learning internal: {str(e)}",
        )


@router.get("/{experiment_id}", response_model=ExperimentDetailResponse, summary="Get Learning")
async def get_learning(
    experiment_id: int = Path(..., description="Learning ID to retrieve"),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """
    학습 상세정보 조회

    특정 학습의 상세 정보를 조회합니다.
    목록 필드에 더해 학습 메트릭, 등록 상태, 메시지 정보를 통합 제공할 수 있는 상세 조회 API입니다.

    ## Path Parameters
    - **experiment_id** (int): 조회할 학습 ID

    ## Response (ExperimentDetailResponse)
    - **id** (int): 학습 ID
    - **name** (str): 학습 이름
    - **description** (str): 학습 설명
    - **reference_model_id** (int): 참조 모델 ID
    - **dataset_id** (int): 데이터셋 ID
    - **kubeflow_run_id** (str, optional): Kubeflow 파이프라인 실행 ID
    - **mlflow_run_id** (str, optional): MLflow 실행 ID
    - **status** (str): 학습 상태
    - **reference_model**: 참조 모델 상세 정보
    - **dataset**: 데이터셋 상세 정보
    - **hyperparameters**: 하이퍼파라미터 목록
    - **created_at** (datetime): 생성 시각
    - **updated_at** (datetime): 수정 시각

    ## Notes
    - 게이트웨이 DB에서 사용자 소유 여부를 먼저 검증한 뒤 외부 MLOps API를 조회합니다.
    - 외부 실험 상세 응답을 게이트웨이의 learning 상세 조회로 매핑하여 제공합니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 학습을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        await _sync_external_experiments_for_admin(db, current_user)
        if not experiment_crud.check_ownership(db, experiment_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Learning item not found or access denied",
            )

        result = await experiment_service.get_experiment(
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
        logger.error(f"Error getting learning item {experiment_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get learning item: {str(e)}",
        )


@router.patch("/{experiment_id}", response_model=ExperimentReadResponse, summary="Update Learning")
async def update_learning(
    experiment_id: int = Path(..., description="Learning ID to update"),
    update_data: ExperimentUpdateRequest = ...,
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """
    학습 정보 수정

    학습이 진행 중이거나 완료된 항목의 이름과 설명을 수정합니다.
    학습 결과의 무결성을 위해 모델, 데이터셋, 하이퍼파라미터 등은 수정할 수 없습니다.

    ## Path Parameters
    - **experiment_id** (int): 수정할 학습 ID

    ## Response (ExperimentReadResponse)
    - **id** (int): 학습 ID
    - **name** (str): 학습 이름
    - **description** (str): 학습 설명
    - **reference_model_id** (int): 참조 모델 ID
    - **dataset_id** (int): 데이터셋 ID
    - **kubeflow_run_id** (str, optional): Kubeflow 파이프라인 실행 ID
    - **mlflow_run_id** (str, optional): MLflow 실행 ID
    - **status** (str): 학습 상태
    - **reference_model**: 참조 모델 상세 정보
    - **dataset**: 데이터셋 상세 정보
    - **hyperparameters**: 하이퍼파라미터 목록
    - **created_at** (datetime): 생성 시각
    - **updated_at** (datetime): 수정 시각

    ## Notes
    - 학습이 진행 중이거나 완료된 항목에서는 `name`과 `description`만 수정 가능합니다.
    - `reference_model_id`, `dataset_id`, `hyperparameters` 등은 학습 결과의 무결성을 위해 수정할 수 없습니다.
    - 제공된 필드만 업데이트되며, 생략된 필드는 기존 값이 유지됩니다.
    - 외부 MLOps API에는 기존 experiments 수정 API로 요청하고, 게이트웨이 DB의 매핑 정보도 함께 갱신합니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 학습을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        await _sync_external_experiments_for_admin(db, current_user)
        if not experiment_crud.check_ownership(db, experiment_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Learning item not found or access denied",
            )

        user_info = {
            "member_id": current_user.member_id,
            "role": current_user.role,
            "name": current_user.name,
        }
        update_payload = update_data.model_dump(exclude_unset=True)

        result = await experiment_service.update_experiment(
            experiment_id=experiment_id,
            update_data=update_payload,
            user_info=user_info,
        )

        experiment_crud.update_mapping(
            db=db,
            surro_experiment_id=experiment_id,
            member_id=current_user.member_id,
            update_data=update_payload,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating learning item {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update learning item: {str(e)}",
        )


@router.delete("/{experiment_id}", summary="Delete Learning")
async def delete_learning(
    experiment_id: int = Path(..., description="Learning ID to delete"),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """
    학습 삭제

    학습 항목을 삭제합니다.
    외부 MLOps 시스템의 MLflow artifacts와 S3 object까지 함께 삭제됩니다.

    ## Path Parameters
    - **experiment_id** (int): 삭제할 학습 ID

    ## Response
    - **message** (str): 삭제 성공 메시지

    ## Notes
    - 게이트웨이 DB에서 소유권 검증 후 외부 MLOps API 삭제를 요청합니다.
    - 삭제 성공 시 게이트웨이 DB의 사용자-학습 매핑도 함께 제거됩니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 학습을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        await _sync_external_experiments_for_admin(db, current_user)
        if not experiment_crud.check_ownership(db, experiment_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Learning item not found or access denied",
            )

        user_info = {
            "member_id": current_user.member_id,
            "role": current_user.role,
            "name": current_user.name,
        }

        result = await experiment_service.delete_experiment(
            experiment_id=experiment_id,
            user_info=user_info,
        )

        experiment_crud.delete_mapping(db, experiment_id, current_user.member_id)
        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting learning item {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete learning item: {str(e)}",
        )
