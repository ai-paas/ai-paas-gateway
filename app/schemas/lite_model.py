from pydantic import BaseModel, Field, ConfigDict
from typing import Any, Optional, Dict, List


class LiteModelResponse(BaseModel):
    """최적화 모델 API 단일 조회 응답 래퍼 - 응답 데이터를 직접 반환"""
    model_config = ConfigDict(extra="allow", protected_namespaces=())

class LiteModelDataResponse(BaseModel):
    """최적화 모델 API 범용 응답 래퍼 - 응답 내용을 그대로 data에 담음"""
    data: Any = Field(..., description="Any Cloud API 응답 데이터 (원본 그대로)")

class OptimizeRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    saved_model_run_id: str
    saved_model_path: str
    model_name: str
    args: Dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    progress_status: bool = Field(..., description="진행 상태")
    path_output_model: str = Field(..., description="출력 모델 경로")

class ModelOptimizer(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    saved_model_run_id: str = Field(..., description="모델 id")
    saved_model_path: str = Field(..., description="모델 경로")

class ModelOptimizerPTQ(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    saved_model_run_id: str = Field(..., description="모델 id")
    saved_model_path: str = Field(..., description="모델 경로")
    quantization_layers: List[str] = Field(..., description="양자화 레이어 목록")
