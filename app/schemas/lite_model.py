from pydantic import BaseModel, Field
from typing import Any, Optional, Dict


class LiteModelResponse(BaseModel):
    """최적화 모델 API 단일 조회 응답 래퍼 - 응답 데이터를 직접 반환"""
    # 이 경우 Any 타입의 필드들이 동적으로 추가됨
    class Config:
        extra = "allow"  # 추가 필드 허용

class LiteModelDataResponse(BaseModel):
    """최적화 모델 API 범용 응답 래퍼 - 응답 내용을 그대로 data에 담음"""
    data: Any = Field(..., description="Any Cloud API 응답 데이터 (원본 그대로)")

class OptimizeRequest(BaseModel):
    saved_model_run_id: str
    saved_model_path: str
    model_name: str
    args: Dict[str, Any] = Field(default_factory=dict)


class TaskUpdate(BaseModel):
    """Task 업데이트 요청 스키마"""
    progress_status: bool = Field(..., description="진행 상태")
    path_output_model: str = Field(..., description="출력 모델 경로")