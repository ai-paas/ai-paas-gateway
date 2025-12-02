from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


# ===== 학습 파이프라인 요청 =====

class TrainingPipelineRequest(BaseModel):
    """학습 파이프라인 생성 요청"""
    train_name: Optional[str] = Field(default="", description="학습 실험 이름")
    description: Optional[str] = Field(default="", description="학습 실험 설명")
    gpus: Optional[str] = Field(default="1", description="사용할 GPU 개수 (1개 이상 필수)")
    batch_size: Optional[str] = Field(default="64", description="배치 크기")
    epochs: Optional[str] = Field(default="5", description="학습 에포크 수")
    save_period: Optional[str] = Field(default="1", description="모델 저장 주기")
    weight_decay: Optional[str] = Field(default="5e-4", description="가중치 감쇠(정규화) 계수")
    lr0: Optional[str] = Field(default="0.01", description="초기 학습률")
    lrf: Optional[str] = Field(default="0.05", description="최종 학습률 (lr0의 비율)")

    class Config:
        schema_extra = {
            "example": {
                "train_name": "YOLO 객체 탐지 학습",
                "description": "COCO 데이터셋으로 YOLO 모델 학습",
                "gpus": "1",
                "batch_size": "32",
                "epochs": "5",
                "save_period": "1",
                "weight_decay": "5e-4",
                "lr0": "0.01",
                "lrf": "0.05"
            }
        }


class TrainingPipelineResponse(BaseModel):
    """학습 파이프라인 생성 응답"""
    experiment_id: Optional[int] = Field(
        None,
        description="생성된 실험 ID (실패 시 null)"
    )


# ===== 모델 등록 파이프라인 요청 =====

class ModelRegistrationRequest(BaseModel):
    """모델 등록 파이프라인 요청"""
    model_name: str = Field(..., description="등록할 모델 이름")
    description: str = Field(..., description="모델 설명")
    experiment_id: int = Field(..., description="학습 완료된 실험 ID")

    class Config:
        schema_extra = {
            "example": {
                "model_name": "YOLO-trained-v1",
                "description": "COCO 데이터셋으로 학습한 YOLO 모델, mAP@0.5: 0.85",
                "experiment_id": 123
            }
        }


class ModelRegistrationResponse(BaseModel):
    """모델 등록 파이프라인 응답"""
    success: bool = Field(..., description="파이프라인 실행 성공 여부")


# ===== 학습 상태 조회 =====

class MetricHistory(BaseModel):
    """메트릭 히스토리 항목"""
    key: str
    value: float
    timestamp: int
    step: int


class TrainingStatusResponse(BaseModel):
    """학습 상태 조회 응답"""
    status: str = Field(..., description="학습 상태 (RUNNING/FINISHED/FAILED)")
    start_time: int = Field(..., description="학습 시작 시각 (밀리초 타임스탬프)")
    end_time: int = Field(..., description="학습 종료 시각 (밀리초 타임스탬프)")
    max_epoch: int = Field(..., description="설정된 최대 에포크 수")
    current_epoch: int = Field(..., description="현재 진행 중인 에포크")
    loss_history: List[MetricHistory] = Field(default_factory=list, description="손실(loss) 히스토리")
    epoch_history: List[MetricHistory] = Field(default_factory=list, description="에포크 히스토리")
    average_precision_50_history: List[MetricHistory] = Field(
        default_factory=list,
        description="AP@50 히스토리 (IoU 0.5 기준)"
    )
    average_precision_75_history: List[MetricHistory] = Field(
        default_factory=list,
        description="AP@75 히스토리 (IoU 0.75 기준)"
    )
    best_average_precision_history: List[MetricHistory] = Field(
        default_factory=list,
        description="최고 평균 정밀도 히스토리"
    )
    average_precision_50_95_history: List[MetricHistory] = Field(
        default_factory=list,
        description="mAP@0.5:0.95 히스토리"
    )