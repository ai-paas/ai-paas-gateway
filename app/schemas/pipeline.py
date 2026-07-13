from typing import Optional, List, Any

from pydantic import BaseModel, Field, ConfigDict

from app.schemas.dataset import DatasetKindEnum


class TrainingPipelineRequest(BaseModel):
    """MLOps multipart 학습 파이프라인 요청의 Form 필드"""
    model_config = ConfigDict(protected_namespaces=())

    model_id: int = Field(..., description="학습에 사용할 모델 ID")
    dataset_id: Optional[int] = Field(None, description="기존 데이터셋 ID. dataset_file과 동시에 사용할 수 없음")
    dataset_kind: Optional[DatasetKindEnum] = Field(None, description="데이터셋 학습 태스크 분류")
    train_name: str = Field("", description="학습 실험 이름")
    description: str = Field("", description="학습 실험 설명")
    gpus: Optional[str] = Field(None, description="사용할 GPU 개수")
    batch_size: Optional[str] = Field(None, description="배치 크기")
    epochs: Optional[str] = Field(None, description="학습 에포크 수")
    save_period: Optional[str] = Field(None, description="모델 저장 주기")
    weight_decay: Optional[str] = Field(None, description="가중치 감쇠 계수")
    learning_rate: Optional[str] = Field(None, description="학습률")


class TrainingPipelineResponse(BaseModel):
    """학습 파이프라인 응답"""
    experiment_id: Optional[int] = Field(None, description="생성된 실험의 고유 ID")


class ModelRegistrationRequest(BaseModel):
    """모델 등록 파이프라인 요청"""
    model_config = ConfigDict(protected_namespaces=())

    model_name: str = Field(..., description="등록될 모델 표시 이름")
    description: str = Field(..., description="설명")
    experiment_id: int = Field(..., description="대상 학습 실험 ID")


class ModelRegistrationResponse(BaseModel):
    """모델 등록 파이프라인 응답"""
    accepted: bool = Field(..., description="파이프라인 제출 수락 여부")
    experiment_id: int = Field(..., description="요청 실험 ID")
    message: str = Field(..., description="안내 메시지")


class TrainingStatusResponse(BaseModel):
    """학습 상태 조회 응답"""
    status: str = Field(..., description="학습 상태")
    start_time: int = Field(..., description="시작 시간 (Unix timestamp)")
    end_time: Optional[int] = Field(None, description="종료 시간 (Unix timestamp)")
    elapsed_time: int = Field(..., description="경과 시간 (초)")
    max_epoch: int = Field(..., description="최대 에포크 수")
    current_epoch: int = Field(..., description="현재 에포크")
    loss_history: List[Any] = Field(..., description="손실 히스토리")
    epoch_history: List[Any] = Field(..., description="에포크 히스토리")
    average_precision_50_history: List[Any] = Field(..., description="AP@50 히스토리")
    average_precision_75_history: List[Any] = Field(..., description="AP@75 히스토리")
    best_average_precision_history: List[Any] = Field(..., description="Best AP 히스토리")
    average_precision_50_95_history: List[Any] = Field(..., description="AP@50:95 히스토리")
