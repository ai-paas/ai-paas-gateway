from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime


class ExperimentUpdateRequest(BaseModel):
    """실험 수정 요청 스키마"""
    name: Optional[str] = Field(None, description="새로운 실험 이름. 실험을 식별하기 위한 이름. 생략 시 기존 값 유지")
    description: Optional[str] = Field(None, description="새로운 실험 설명. 실험에 대한 상세 설명. null 값으로 설명 제거 가능. 생략 시 기존 값 유지")


class ExperimentInternalUpdateRequest(BaseModel):
    """내부 통신 전용 실험 수정 요청 스키마"""
    status: Optional[str] = Field(None, description='실험 상태. 예: "RUNNING", "COMPLETED", "FAILED"')
    mlflow_run_id: Optional[str] = Field(None, description="MLflow 실행 ID")
    kubeflow_run_id: Optional[str] = Field(None, description="Kubeflow 파이프라인 실행 ID")
    registration_kubeflow_run_id: Optional[str] = Field(None, description="모델 등록 Kubeflow 파이프라인 실행 ID")


class ExperimentReferenceModel(BaseModel):
    """실험 참조 모델 정보"""
    id: int = Field(..., description="모델 ID")
    name: Optional[str] = Field(None, description="모델 이름")


class ExperimentDataset(BaseModel):
    """실험 데이터셋 정보"""
    id: int = Field(..., description="데이터셋 ID")
    name: Optional[str] = Field(None, description="데이터셋 이름")


class LossHistoryItem(BaseModel):
    """에폭별 loss 항목"""
    epoch: int = Field(..., description="에폭 번호")
    loss: float = Field(..., description="loss 값")


class ExperimentListItem(BaseModel):
    """실험 목록 항목"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="실험 고유 ID")
    name: Optional[str] = Field(None, description="실험 이름")
    description: Optional[str] = Field(None, description="실험 설명")
    reference_model_id: Optional[int] = Field(None, description="참조 모델 ID")
    dataset_id: Optional[int] = Field(None, description="데이터셋 ID")
    status: Optional[str] = Field(None, description="실험 상태")
    registration_status: Optional[str] = Field(None, description="모델 등록 상태")
    registered_model_id: Optional[int] = Field(None, description="등록된 모델 ID")
    elapsed_time: Optional[int] = Field(None, description="경과 시간")
    end_time: Optional[str] = Field(None, description="종료 시간")
    reference_model: Optional[ExperimentReferenceModel] = Field(None, description="참조 모델 정보")
    dataset: Optional[ExperimentDataset] = Field(None, description="데이터셋 정보")
    created_at: Optional[datetime] = Field(None, description="실험 생성 시각")
    updated_at: Optional[datetime] = Field(None, description="실험 수정 시각")


class ExperimentListResponse(BaseModel):
    """실험 목록 응답"""
    data: List[ExperimentListItem] = Field(..., description="실험 목록")
    total: int = Field(..., description="전체 항목 수")
    page: int = Field(..., description="현재 페이지 번호")
    size: int = Field(..., description="페이지당 항목 수")


class ExperimentDetailResponse(BaseModel):
    """실험 상세 응답"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="실험 고유 ID")
    name: Optional[str] = Field(None, description="실험 이름")
    description: Optional[str] = Field(None, description="실험 설명")
    reference_model_id: Optional[int] = Field(None, description="참조 모델 ID")
    dataset_id: Optional[int] = Field(None, description="데이터셋 ID")
    status: Optional[str] = Field(None, description="실험 상태")
    reference_model: Optional[ExperimentReferenceModel] = Field(None, description="참조 모델 상세 정보")
    dataset: Optional[ExperimentDataset] = Field(None, description="데이터셋 상세 정보")
    hyperparameters: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="하이퍼파라미터 목록")
    created_at: Optional[datetime] = Field(None, description="실험 생성 시각")
    updated_at: Optional[datetime] = Field(None, description="실험 수정 시각")
    registration_status: Optional[str] = Field(None, description="모델 등록 상태")
    registered_model_id: Optional[int] = Field(None, description="등록된 모델 ID")
    train_msg: Optional[str] = Field(None, description="학습 메시지")
    model_register_msg: Optional[str] = Field(None, description="모델 등록 메시지")
    elapsed_time: Optional[int] = Field(None, description="경과 시간")
    end_time: Optional[str] = Field(None, description="종료 시간")
    max_epoch: Optional[int] = Field(None, description="최대 에폭")
    current_epoch: Optional[int] = Field(None, description="현재 에폭")
    loss: Optional[float] = Field(None, description="loss")
    loss_history: Optional[List[LossHistoryItem]] = Field(default_factory=list, description="loss 히스토리")
    average_precision: Optional[float] = Field(None, description="Average Precision")
    accuracy: Optional[float] = Field(None, description="Accuracy")
    precision: Optional[float] = Field(None, description="Precision")
    recall: Optional[float] = Field(None, description="Recall")


class ExperimentReadResponse(BaseModel):
    """실험 수정/내부업데이트 응답 (PATCH 응답용)"""
    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="실험 ID")
    name: str = Field(..., description="실험 이름")
    description: Optional[str] = Field(None, description="실험 설명")
    reference_model_id: int = Field(..., description="참조 모델 ID")
    dataset_id: int = Field(..., description="데이터셋 ID")
    kubeflow_run_id: Optional[str] = Field(None, description="Kubeflow 파이프라인 실행 ID")
    mlflow_run_id: Optional[str] = Field(None, description="MLflow 실행 ID")
    status: str = Field(..., description="실험 상태")
    reference_model: Optional[Dict[str, Any]] = Field(None, description="참조 모델 상세 정보")
    dataset: Optional[Dict[str, Any]] = Field(None, description="데이터셋 상세 정보")
    hyperparameters: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="하이퍼파라미터 목록")
    created_at: Optional[datetime] = Field(None, description="실험 생성 시각")
    updated_at: Optional[datetime] = Field(None, description="실험 수정 시각")
    deleted_at: Optional[datetime] = Field(None, description="실험 삭제 시각")
    created_by: Optional[str] = Field(None, description="생성자")
    updated_by: Optional[str] = Field(None, description="수정자")
    deleted_by: Optional[str] = Field(None, description="삭제자")
