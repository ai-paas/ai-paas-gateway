from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.cruds.pipeline import pipeline_crud
from app.auth import get_current_user
from app.schemas.pipeline import (
    TrainingPipelineRequest,
    TrainingPipelineResponse,
    ModelRegistrationRequest,
    ModelRegistrationResponse,
    TrainingStatusResponse
)
from app.services.pipeline_service import pipeline_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/training", response_model=TrainingPipelineResponse)
async def create_training_pipeline(
        model_id: int = Query(..., description="학습에 사용할 모델 ID"),
        dataset_id: int = Query(..., description="학습에 사용할 데이터셋 ID"),
        training_request: TrainingPipelineRequest = ...,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    학습 파이프라인 생성 및 실행

    모델과 데이터셋을 사용하여 Kubeflow Pipeline 기반의 학습 파이프라인을 생성하고 실행합니다.
    학습 실험(Experiment)을 생성하고 하이퍼파라미터를 설정한 후, Kubeflow에서 학습 작업을 시작합니다.

    ## Request Body (TrainingPipelineRequest)
    - **train_name** (str, optional): 학습 실험 이름 (기본값: 빈 문자열)
    - **description** (str, optional): 학습 실험 설명 (기본값: 빈 문자열)
    - **gpus** (str, optional): 사용할 GPU 개수 (기본값: "1", 필수적으로 1개 이상)
    - **batch_size** (str, optional): 배치 크기 (기본값: "64")
    - **epochs** (str, optional): 학습 에포크 수 (기본값: "5")
    - **save_period** (str, optional): 모델 저장 주기 (기본값: "1")
    - **weight_decay** (str, optional): 가중치 감쇠 계수 (기본값: "5e-4")
    - **lr0** (str, optional): 초기 학습률 (기본값: "0.01")
    - **lrf** (str, optional): 최종 학습률 비율 (기본값: "0.05")

    ## Response (TrainingPipelineResponse)
    - **experiment_id** (int): 생성된 실험 ID (실패 시 null)

    ## Process Flow
    1. 모델 및 데이터셋 정보 조회
    2. MLflow 및 Kubeflow 설정 확인
    3. 실험(Experiment) 레코드 생성
    4. 하이퍼파라미터 저장
    5. Kubeflow Pipeline 실행 시작

    ## Notes
    - 학습은 **비동기**로 실행되며, 즉시 완료되지 않습니다
    - 학습 상태는 `/pipeline/training/{experiment_id}/status` API로 조회할 수 있습니다
    - 학습 완료 후 `/pipeline/model/registration` API로 모델을 등록할 수 있습니다
    - 실패 시 experiment_id가 null로 반환되며, 에러는 로그에 기록됩니다

    ## Errors
    - 400: GPU 개수가 0 이하이거나 유효하지 않은 값, 또는 학습 불가능한 모델
    - 401: 인증되지 않은 사용자
    - 404: 모델 또는 데이터셋을 찾을 수 없음
    - 500: 파이프라인 생성 또는 실행 중 서버 내부 오류
    """
    # GPU 개수 검증
    try:
        gpu_count = int(training_request.gpus)
        if gpu_count <= 0:
            raise HTTPException(
                status_code=400,
                detail="GPU count must be greater than 0"
            )
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail="Invalid GPU count value"
        )

    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    # 하이퍼파라미터 구성
    hyperparameters = {
        "gpus": training_request.gpus,
        "batch_size": training_request.batch_size,
        "epochs": training_request.epochs,
        "save_period": training_request.save_period,
        "weight_decay": training_request.weight_decay,
        "lr0": training_request.lr0,
        "lrf": training_request.lrf
    }

    # 외부 API 호출
    external_response = await pipeline_service.create_training_pipeline(
        model_id=model_id,
        dataset_id=dataset_id,
        training_params=training_request.dict(),
        user_info=user_info
    )

    # 실험 ID가 있으면 우리 DB에 저장
    if external_response.experiment_id:
        try:
            db_experiment = pipeline_crud.create_experiment(
                db=db,
                train_name=training_request.train_name,
                description=training_request.description,
                model_id=model_id,
                dataset_id=dataset_id,
                hyperparameters=hyperparameters,
                created_by=current_user.member_id
            )
            logger.info(
                f"Created experiment: id={db_experiment.id}, "
                f"external_id={external_response.experiment_id}, "
                f"member_id={current_user.member_id}"
            )
        except Exception as e:
            logger.error(f"Failed to save experiment to DB: {str(e)}")
            # DB 저장 실패해도 외부 API는 성공했으므로 experiment_id 반환

    return external_response


@router.post("/model/registration", response_model=ModelRegistrationResponse)
async def register_model(
        model_name: str = Query(..., description="등록할 모델 이름"),
        description: str = Query(..., description="모델 설명"),
        experiment_id: int = Query(..., description="학습 완료된 실험 ID"),
        current_user=Depends(get_current_user)
):
    """
    학습 완료된 모델 등록 파이프라인 실행

    학습이 완료된 실험(Experiment)의 결과 모델을 모델 레지스트리에 등록하는 파이프라인을 실행합니다.
    MLflow에 저장된 학습된 모델을 조회하여 새로운 모델로 등록하며, 부모 모델과의 관계를 설정합니다.

    ## Request Parameters
    - **model_name** (str, required): 등록할 모델 이름
    - **description** (str, required): 모델 설명 (학습 조건, 성능 등 포함 권장)
    - **experiment_id** (int, required): 학습 완료된 실험 ID

    ## Response (ModelRegistrationResponse)
    - **success** (bool): 파이프라인 실행 성공 여부

    ## Process Flow
    1. 실험(Experiment) 정보 조회 및 부모 모델 ID 확인
    2. Kubeflow Pipeline 생성 및 실행
    3. MLflow에서 학습된 모델 조회
    4. 모델 레지스트리에 새 모델로 등록
    5. 부모 모델과의 관계 설정

    ## Notes
    - 학습이 **완료된 실험**에 대해서만 사용해야 합니다
    - 등록된 모델은 부모 모델의 자식 모델로 설정됩니다
    - 파이프라인 실행은 **비동기**로 진행되며, 즉시 완료되지 않습니다
    - 실패 시 False를 반환하며, 상세 에러는 로그에 기록됩니다
    - 모델 등록 후 모델 목록에서 조회할 수 있습니다

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 실험(Experiment)을 찾을 수 없음
    - 500: 파이프라인 실행 중 서버 내부 오류
    """
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    registration_response = await pipeline_service.register_model(
        model_name=model_name,
        description=description,
        experiment_id=experiment_id,
        user_info=user_info
    )

    return registration_response


@router.get("/training/{experiment_id}/status", response_model=TrainingStatusResponse)
async def get_training_status(
        experiment_id: int,
        current_user=Depends(get_current_user)
):
    """
    학습 파이프라인 상태 조회

    특정 실험(Experiment)의 학습 진행 상태와 메트릭을 조회합니다.
    MLflow에서 실시간 학습 메트릭을 가져와 현재 epoch, loss, 평균 정밀도(AP) 등의 정보를 제공합니다.

    ## Path Parameters
    - **experiment_id** (int): 조회할 실험 ID (학습 파이프라인 생성 시 반환된 ID)

    ## Response (TrainingStatusResponse)
    - **status** (str): 학습 상태
        - "RUNNING": 학습 진행 중
        - "FINISHED": 학습 완료
        - "FAILED": 학습 실패
    - **start_time** (int): 학습 시작 시각 (밀리초 타임스탬프)
    - **end_time** (int): 학습 종료 시각 (밀리초 타임스탬프, 진행 중인 경우 현재 시각)
    - **max_epoch** (int): 설정된 최대 에포크 수
    - **current_epoch** (int): 현재 진행 중인 에포크
    - **loss_history** (List[MetricHistory]): 손실(loss) 히스토리
    - **epoch_history** (List[MetricHistory]): 에포크 히스토리
    - **average_precision_50_history**: AP@50 히스토리 (IoU 0.5 기준)
    - **average_precision_75_history**: AP@75 히스토리 (IoU 0.75 기준)
    - **best_average_precision_history**: 최고 평균 정밀도 히스토리
    - **average_precision_50_95_history**: mAP@0.5:0.95 히스토리

    ## Notes
    - 학습이 시작되지 않은 경우 일부 메트릭이 비어있을 수 있습니다
    - 메트릭은 step과 timestamp 기준으로 정렬되어 반환됩니다
    - 특정 메트릭 조회 실패 시 해당 메트릭은 빈 리스트로 반환됩니다
    - 학습이 완료되면 status가 "FINISHED"로 변경됩니다
    - 실시간으로 학습 진행 상황을 모니터링할 수 있습니다

    ## Errors
    - 401: 인증되지 않은 사용자
    - 404: 실험을 찾을 수 없거나 학습 상태가 존재하지 않음
    - 500: MLflow 연결 또는 메트릭 조회 중 서버 내부 오류
    """
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    status_response = await pipeline_service.get_training_status(
        experiment_id=experiment_id,
        user_info=user_info
    )

    return status_response