from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime


class ExperimentReferenceModel(BaseModel):
    """실험 참조 모델 정보"""
    id: int
    name: Optional[str] = None


class ExperimentDataset(BaseModel):
    """실험 데이터셋 정보"""
    id: int
    name: Optional[str] = None


class LossHistoryItem(BaseModel):
    """에폭별 loss 항목"""
    epoch: int
    loss: float


class ExperimentListItem(BaseModel):
    """실험 목록 항목"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str] = None
    description: Optional[str] = None
    reference_model_id: Optional[int] = None
    dataset_id: Optional[int] = None
    status: Optional[str] = None
    registration_status: Optional[str] = None
    registered_model_id: Optional[int] = None
    elapsed_time: Optional[int] = None
    end_time: Optional[str] = None
    reference_model: Optional[ExperimentReferenceModel] = None
    dataset: Optional[ExperimentDataset] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ExperimentDetailResponse(BaseModel):
    """실험 상세 응답"""
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: Optional[str] = None
    description: Optional[str] = None
    reference_model_id: Optional[int] = None
    dataset_id: Optional[int] = None
    status: Optional[str] = None
    reference_model: Optional[ExperimentReferenceModel] = None
    dataset: Optional[ExperimentDataset] = None
    hyperparameters: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    registration_status: Optional[str] = None
    registered_model_id: Optional[int] = None
    train_msg: Optional[str] = None
    model_register_msg: Optional[str] = None
    elapsed_time: Optional[int] = None
    end_time: Optional[str] = None
    max_epoch: Optional[int] = None
    current_epoch: Optional[int] = None
    loss: Optional[float] = None
    loss_history: Optional[List[LossHistoryItem]] = Field(default_factory=list)
    average_precision: Optional[float] = None
    accuracy: Optional[float] = None
    precision: Optional[float] = None
    recall: Optional[float] = None
