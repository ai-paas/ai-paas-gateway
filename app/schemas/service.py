from pydantic import BaseModel, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime

ACCESS_TOKEN_EXPIRE_MINUTES = 30


# 사용자 정보 스키마 (외부 API 응답용)
class UserSchema(BaseModel):
    id: int
    username: str
    name: str
    password: str
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


# 워크플로우 기본 스키마 (외부 API 응답용)
class WorkflowBaseSchema(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    status: str
    is_template: bool
    template_id: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[List[str]] = None
    workflow_definition: Optional[Dict[str, Any]] = None
    service_id: Optional[str] = None
    creator_id: int
    kubeflow_run_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# 모니터링 메트릭 스키마
class MonitoringMetrics(BaseModel):
    message_count: int = 0
    active_users: int = 0
    token_usage: int = 0
    avg_interaction_count: float = 0.0
    response_time_ms: Optional[float] = None   # ← 반드시 수정
    error_count: int = 0
    success_rate: float = 0.0


# 워크플로우 모니터링 스키마
class WorkflowMonitoring(BaseModel):
    workflow_id: str
    workflow_name: str
    metrics: MonitoringMetrics
    last_updated: datetime


# 서비스 모니터링 데이터 스키마
class ServiceMonitoringData(BaseModel):
    total_metrics: MonitoringMetrics
    workflow_metrics: List[WorkflowMonitoring] = []
    period_start: datetime
    period_end: datetime


# 외부 API 응답 스키마
class ExternalServiceResponse(BaseModel):
    """외부 API에서 반환되는 서비스 응답"""
    id: str  # UUID (surro_service_id로 저장)
    name: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    creator_id: int
    created_at: datetime
    updated_at: datetime
    creator: UserSchema
    workflow_count: int = 0


class ExternalServiceDetailResponse(ExternalServiceResponse):
    """외부 API 상세 응답"""
    workflows: List[WorkflowBaseSchema] = []
    monitoring_data: Optional[ServiceMonitoringData] = None


# 서비스 생성 요청
class ServiceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None  # 리스트로 변경


# 서비스 수정 요청
class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None  # 리스트로 변경


# 우리 DB 서비스 응답 (기본)
class ServiceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int  # 우리 DB의 PK
    name: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None  # 리스트로 변경
    created_at: datetime
    updated_at: datetime
    created_by: str
    surro_service_id: str  # 외부 API의 UUID


# 서비스 상세 응답 (외부 정보 포함)
class ServiceDetailResponse(BaseModel):
    # 내부 DB 값
    id: int
    name: str
    description: Optional[str]
    tags: List[str]
    created_at: datetime
    updated_at: datetime
    created_by: str
    surro_service_id: str

    # 외부 API 값 (원하는 필드만)
    workflow_count: Optional[int] = 0
    workflows: List[WorkflowBaseSchema] = []
    monitoring_data: Optional[ServiceMonitoringData] = None


# 서비스 목록 응답
class ServiceListResponse(BaseModel):
    data: List[ServiceResponse]
    total: int
    page: int
    size: int