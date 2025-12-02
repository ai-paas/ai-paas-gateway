from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.cruds.experiment import experiment_crud
from app.auth import get_current_user
from app.schemas.experiment import (
    ExperimentUpdateRequest,
    ExperimentReadSchema,
    ExperimentInternalUpdateRequest
)
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.patch("/{experiment_id}", response_model=ExperimentReadSchema)
async def update_experiment(
        experiment_id: int = Path(..., description="수정할 실험 ID"),
        update_request: ExperimentUpdateRequest = ...,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    실험 정보 수정

    학습이 진행 중이거나 완료된 실험의 이름과 설명을 수정합니다.
    학습 결과의 무결성을 위해 모델, 데이터셋, 하이퍼파라미터 등은 수정할 수 없습니다.

    ## Path Parameters
    - **experiment_id** (int): 수정할 실험 ID

    ## Request Body (ExperimentUpdateRequest)
    - **name** (str, optional): 새로운 실험 이름
        - 실험을 식별하기 위한 이름
        - 생략 시 기존 값 유지
    - **description** (str, optional): 새로운 실험 설명
        - 실험에 대한 상세 설명
        - null 값으로 설명 제거 가능
        - 생략 시 기존 값 유지

    ## Response (ExperimentReadSchema)
    실험의 전체 정보를 반환합니다 (참조 모델, 데이터셋, 하이퍼파라미터 포함)

    ## Notes
    - 학습이 진행 중이거나 완료된 실험에서는 name과 description만 수정 가능
    - reference_model_id, dataset_id, hyperparameters 등은 학습 결과의 무결성을 위해 수정 불가
    - 제공된 필드만 업데이트되며, 생략된 필드는 기존 값이 유지됨

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 실험을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        db_experiment = experiment_crud.update_experiment(
            db=db,
            experiment_id=experiment_id,
            name=update_request.name,
            description=update_request.description
        )

        if not db_experiment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Experiment with id {experiment_id} not found"
            )

        logger.info(
            f"Updated experiment: id={experiment_id}, "
            f"member_id={current_user.member_id}"
        )

        return db_experiment

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating experiment {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update experiment: {str(e)}"
        )


@router.get("/{experiment_id}", response_model=ExperimentReadSchema)
async def get_experiment(
        experiment_id: int = Path(..., description="조회할 실험 ID"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    실험 상세정보 조회

    특정 실험의 상세 정보를 조회합니다. 참조 모델, 데이터셋, 하이퍼파라미터 등 모든 관련 정보를 포함합니다.

    ## Path Parameters
    - **experiment_id** (int): 조회할 실험 ID

    ## Response (ExperimentReadSchema)
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

    ## Notes
    - 실험의 모든 관련 정보(모델, 데이터셋, 하이퍼파라미터)를 포함하여 반환
    - kubeflow_run_id와 mlflow_run_id는 학습 실행 후에만 값이 설정됨

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 실험을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        db_experiment = experiment_crud.get_experiment(db, experiment_id)

        if not db_experiment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Experiment with id {experiment_id} not found"
            )

        logger.info(
            f"Retrieved experiment: id={experiment_id}, "
            f"member_id={current_user.member_id}"
        )

        return db_experiment

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving experiment {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve experiment: {str(e)}"
        )


@router.delete("/{experiment_id}")
async def delete_experiment(
        experiment_id: int = Path(..., description="삭제할 실험 ID"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    실험 삭제

    실험을 삭제합니다. MLflow artifacts와 S3 object도 함께 삭제됩니다.

    ## Path Parameters
    - **experiment_id** (int): 삭제할 실험 ID

    ## Response
    - **message** (str): 삭제 성공 메시지

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 실험을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        deleted = experiment_crud.delete_experiment(db, experiment_id)

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Experiment with id {experiment_id} not found"
            )

        logger.info(
            f"Deleted experiment: id={experiment_id}, "
            f"member_id={current_user.member_id}"
        )

        return {"message": f"Experiment {experiment_id} successfully deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting experiment {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete experiment: {str(e)}"
        )


@router.patch("/{experiment_id}/internal-access", response_model=ExperimentReadSchema)
async def update_experiment_internal(
        experiment_id: int = Path(..., description="수정할 실험 ID"),
        update_request: ExperimentInternalUpdateRequest = ...,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    내부 통신 전용 실험 정보 수정 API

    시스템 내부 통신에서 사용하는 API로, status, mlflow_run_id, kubeflow_run_id를 수정할 수 있습니다.
    인증이 필요합니다.

    ## Path Parameters
    - **experiment_id** (int): 수정할 실험 ID

    ## Request Body (ExperimentInternalUpdateRequest)
    - **status** (str, optional): 실험 상태 (예: "RUNNING", "COMPLETED", "FAILED")
    - **mlflow_run_id** (str, optional): MLflow 실행 ID
    - **kubeflow_run_id** (str, optional): Kubeflow 파이프라인 실행 ID

    ## Response (ExperimentReadSchema)
    실험의 전체 정보를 반환합니다.

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 실험을 찾을 수 없음
    - 500: 서버 내부 오류
    """
    try:
        db_experiment = experiment_crud.update_experiment_internal(
            db=db,
            experiment_id=experiment_id,
            status=update_request.status,
            mlflow_run_id=update_request.mlflow_run_id,
            kubeflow_run_id=update_request.kubeflow_run_id
        )

        if not db_experiment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Experiment with id {experiment_id} not found"
            )

        logger.info(
            f"Updated experiment (internal): id={experiment_id}, "
            f"status={update_request.status}, "
            f"member_id={current_user.member_id}"
        )

        return db_experiment

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating experiment (internal) {experiment_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update experiment: {str(e)}"
        )