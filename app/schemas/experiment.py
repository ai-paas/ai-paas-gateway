from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ===== Request Schemas =====

class ExperimentUpdateRequest(BaseModel):
    """실험 정보 수정 요청 (name, description만)"""
    name: Optional[str] = Field(None, description="새로운 실험 이름")
    description: Optional[str] = Field(None, description="새로운 실험 설명")

    class Config:
        schema_extra = {
            "example": {
                "name": "Updated YOLO Training",
                "description": "Updated description for YOLO training experiment"
            }
        }


class ExperimentInternalUpdateRequest(BaseModel):
    """내부 통신용 실험 정보 수정 요청"""
    status: Optional[str] = Field(None, description="실험 상태 (RUNNING/COMPLETED/FAILED)")
    mlflow_run_id: Optional[str] = Field(None, description="MLflow 실행 ID")
    kubeflow_run_id: Optional[str] = Field(None, description="Kubeflow 파이프라인 실행 ID")

    class Config:
        schema_extra = {
            "example": {
                "status": "COMPLETED",
                "mlflow_run_id": "abc123def456",
                "kubeflow_run_id": "run-xyz789"
            }
        }


# ===== Response Sub-Schemas =====

class ModelProviderReadSchema(BaseModel):
    """모델 제공자 정보"""
    id: int
    name: str
    description: str

    class Config:
        from_attributes = True


class ModelTypeReadSchema(BaseModel):
    """모델 타입 정보"""
    id: int
    name: str
    description: str

    class Config:
        from_attributes = True


class ModelFormatReadSchema(BaseModel):
    """모델 포맷 정보"""
    id: int
    name: str
    description: str

    class Config:
        from_attributes = True


class ModelRegistryReadSchema(BaseModel):
    """모델 레지스트리 정보"""
    id: int
    artifact_path: str
    uri: str
    run_id: Optional[str]
    reference_model_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ModelReadParentSchema(BaseModel):
    """부모 모델 정보 (재귀적)"""
    id: int
    name: str
    description: str
    parent_model: Optional['ModelReadParentSchema'] = None

    class Config:
        from_attributes = True


class ModelReadChildSchema(BaseModel):
    """자식 모델 정보 (재귀적)"""
    id: int
    name: str
    description: str
    child_models: Optional[List['ModelReadChildSchema']] = None

    class Config:
        from_attributes = True


class ModelReadSchema(BaseModel):
    """참조 모델 상세 정보"""
    id: int
    name: str
    description: str
    provider_info: ModelProviderReadSchema
    type_info: ModelTypeReadSchema
    format_info: ModelFormatReadSchema
    parent_model_id: Optional[int]
    registry: ModelRegistryReadSchema
    parent_model: Optional[ModelReadParentSchema]
    child_models: Optional[List[ModelReadChildSchema]]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DatasetRegistryReadSchema(BaseModel):
    """데이터셋 레지스트리 정보"""
    id: int
    artifact_path: str
    uri: str
    dataset_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DatasetReadSchema(BaseModel):
    """데이터셋 상세 정보"""
    id: int
    name: str
    dataset_registry: DatasetRegistryReadSchema
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class HyperparameterTypeReadSchema(BaseModel):
    """하이퍼파라미터 타입 정보"""
    id: int
    param_name: str
    param_type: str
    default_value: str

    class Config:
        from_attributes = True


class HyperparameterReadSchema(BaseModel):
    """하이퍼파라미터 정보"""
    id: int
    value: str
    experiment_id: int
    hyperparameter_type_id: int
    hyperparameter_type: HyperparameterTypeReadSchema

    class Config:
        from_attributes = True


# ===== Main Response Schema =====

class ExperimentReadSchema(BaseModel):
    """실험 상세 정보 응답"""
    id: int
    name: str
    description: str
    reference_model_id: int
    dataset_id: int
    kubeflow_run_id: Optional[str]
    mlflow_run_id: Optional[str]
    status: str
    reference_model: ModelReadSchema
    dataset: DatasetReadSchema
    hyperparameters: List[HyperparameterReadSchema]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# 재귀 모델 업데이트
ModelReadParentSchema.model_rebuild()
ModelReadChildSchema.model_rebuild()