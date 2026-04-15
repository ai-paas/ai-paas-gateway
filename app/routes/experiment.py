from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.orm import Session
from typing import List
import logging

from app.database import get_db
from app.auth import get_current_user, get_current_admin_user
from app.cruds import experiment_crud
from app.schemas.experiment import (
    ExperimentListItem, ExperimentDetailResponse,
    ExperimentUpdateRequest, ExperimentInternalUpdateRequest, ExperimentReadResponse
)
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
    실험 목록 조회

    모든 학습 실험의 목록을 반환합니다.
    모델 등록 상태, 경과 시간, 종료 시간 등 요약 정보를 포함합니다.
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


@router.patch("/{experiment_id}", response_model=ExperimentReadResponse)
async def update_experiment(
        experiment_id: int = Path(..., description="수정할 실험 ID"),
        update_data: ExperimentUpdateRequest = ...,
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    실험 정보 수정

    학습이 진행 중이거나 완료된 실험의 이름과 설명을 수정합니다.
    학습 결과의 무결성을 위해 모델, 데이터셋, 하이퍼파라미터 등은 수정할 수 없습니다.

    **Path Parameters**
    - **experiment_id** (int): 수정할 실험 ID

    **Request Body (ExperimentUpdateRequest)**
    - **name** (str, optional): 새로운 실험 이름
      - 실험을 식별하기 위한 이름
      - 생략 시 기존 값 유지
    - **description** (str, optional): 새로운 실험 설명
      - 실험에 대한 상세 설명
      - null 값으로 설명 제거 가능
      - 생략 시 기존 값 유지

    **Response (ExperimentReadSchema)**
    - **id** (int): 실험 ID
    - **name** (str): 실험 이름
    - **description** (str): 실험 설명
    - **reference_model_id** (int): 참조 모델 ID
    - **dataset_id** (int): 데이터셋 ID
    - **kubeflow_run_id** (str, optional): Kubeflow 파이프라인 실행 ID
    - **mlflow_run_id** (str, optional): MLflow 실행 ID
    - **status** (str): 실험 상태
    - **reference_model**: 참조 모델 상세 정보
    - **dataset**: 데이터셋 상세 정보
    - **hyperparameters**: 하이퍼파라미터 목록
    - **created_at** (datetime): 실험 생성 시각
    - **updated_at** (datetime): 실험 수정 시각

    **Notes**
    - 학습이 진행 중이거나 완료된 실험에서는 name과 description만 수정 가능
    - reference_model_id, dataset_id, hyperparameters 등은 학습 결과의 무결성을 위해 수정 불가
    - 제공된 필드만 업데이트되며, 생략된 필드는 기존 값이 유지됨

    **Errors**
    - 401: 인증되지 않은 사용자
    - 404: 실험을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        if not experiment_crud.check_ownership(db, experiment_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Experiment not found or access denied"
            )

        user_info = {
            'member_id': current_user.member_id,
            'role': current_user.role,
            'name': current_user.name
        }
        update_payload = update_data.model_dump(exclude_unset=True)

        result = await experiment_service.update_experiment(
            experiment_id=experiment_id,
            update_data=update_payload,
            user_info=user_info
        )

        # 로컬 캐시 업데이트
        experiment_crud.update_mapping(
            db=db,
            surro_experiment_id=experiment_id,
            member_id=current_user.member_id,
            update_data=update_payload
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating experiment {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update experiment: {str(e)}"
        )


@router.delete("/{experiment_id}")
async def delete_experiment(
        experiment_id: int = Path(..., description="삭제할 실험 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    실험을 삭제합니다.
    MLflow artifacts와 S3 object도 함께 삭제됩니다.

    **Path Parameters**
    - **experiment_id** (int): 삭제할 실험 ID

    **Response**
    - **message** (str): 삭제 성공 메시지

    **Errors**
    - 404: 실험을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        if not experiment_crud.check_ownership(db, experiment_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Experiment not found or access denied"
            )

        user_info = {
            'member_id': current_user.member_id,
            'role': current_user.role,
            'name': current_user.name
        }

        result = await experiment_service.delete_experiment(
            experiment_id=experiment_id,
            user_info=user_info
        )

        # 로컬 매핑 소프트 삭제
        experiment_crud.delete_mapping(db, experiment_id, current_user.member_id)

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting experiment {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete experiment: {str(e)}"
        )


@router.patch("/{experiment_id}/internal-access", response_model=ExperimentReadResponse)
async def update_experiment_internal(
        experiment_id: int = Path(..., description="수정할 실험 ID"),
        update_data: ExperimentInternalUpdateRequest = ...,
        current_user: Member = Depends(get_current_admin_user)
):
    """
    내부 통신 전용 실험 정보 수정 API

    시스템 내부 통신에서 사용하는 API로, status, mlflow_run_id, kubeflow_run_id를 수정할 수 있습니다.
    인증이 필요합니다.

    **Path Parameters**
    - **experiment_id** (int): 수정할 실험 ID

    **Request Body (ExperimentInternalUpdateRequest)**
    - **status** (str, optional): 실험 상태
      - 예: "RUNNING", "COMPLETED", "FAILED"
    - **mlflow_run_id** (str, optional): MLflow 실행 ID
    - **kubeflow_run_id** (str, optional): Kubeflow 파이프라인 실행 ID

    **Response (ExperimentReadSchema)**
    - 실험의 전체 정보를 반환합니다.

    **Errors**
    - 401: 인증되지 않은 사용자
    - 404: 실험을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        user_info = {
            'member_id': current_user.member_id,
            'role': current_user.role,
            'name': current_user.name
        }
        update_payload = update_data.model_dump(exclude_unset=True)

        result = await experiment_service.update_experiment_internal(
            experiment_id=experiment_id,
            update_data=update_payload,
            user_info=user_info
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating experiment internal {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update experiment internal: {str(e)}"
        )


@router.get("/{experiment_id}", response_model=ExperimentDetailResponse)
async def get_experiment(
        experiment_id: int = Path(..., description="조회할 실험 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    실험 상세정보 조회

    특정 실험의 상세 정보를 조회합니다.
    목록 필드에 더해 학습 메트릭, 등록 상태, 메시지 정보를 통합 제공합니다.
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
