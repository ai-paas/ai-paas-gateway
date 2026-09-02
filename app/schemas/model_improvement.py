from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, ConfigDict


class ModelImprovementRequest(BaseModel):
    """모델 최적화/경량화 task 생성 요청"""
    model_config = ConfigDict(protected_namespaces=())

    source_model_id: int = Field(..., description="대상 모델 ID")
    task_type: str = Field(..., description="최적화 기법 (tensorrt, openvino, pruning, ptq 등)")


class ModelImprovementResponse(BaseModel):
    """모델 최적화/경량화 task 생성 응답 (202)"""
    task_id: str = Field(..., description="task 추적 UUID")
    status: str = Field(..., description="초기값 PENDING")
    source_model_id: int = Field(..., description="소스 모델 ID")
    created_at: Optional[datetime] = None


class ModelImprovementStatusResponse(BaseModel):
    """모델 최적화/경량화 task 상태 응답"""
    task_id: str
    status: str = Field(..., description="PENDING, RUNNING, SUCCEEDED, FAILED")
    source_model_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    message: Optional[str] = None
    result_model_id: Optional[int] = None
    error: Optional[str] = None


class TaskTypeResponse(BaseModel):
    """최적화/경량화 task_type 항목"""
    name: str = Field(..., description="기법 식별자")
    category: Optional[str] = Field(None, description="optimization 또는 lightweight")
    description: Optional[str] = Field(None, description="표시용 설명")
