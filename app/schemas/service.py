from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.workflow import UserBriefSchema

ACCESS_TOKEN_EXPIRE_MINUTES = 30


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
    workflow_metrics: List[WorkflowMonitoring] = Field(default_factory=list)
    period_start: datetime
    period_end: datetime


# 외부 API 응답 스키마
class ExternalServiceResponse(BaseModel):
    """외부 API에서 반환되는 서비스 응답.

    MLOps ServiceBriefSchema의 required는 id/name/creator_id/creator뿐 — timestamp는 nullable.
    """
    id: str  # UUID (surro_service_id로 저장)
    name: str
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    creator_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    creator: UserBriefSchema
    workflow_count: int = 0


class ExternalServiceDetailResponse(ExternalServiceResponse):
    """외부 API 상세 응답"""
    workflows: List[WorkflowBaseSchema] = Field(default_factory=list)
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


# ===== 보강 응답 스키마 (workflows 컴포넌트에서 추출) =====


class WorkflowRefSchema(BaseModel):
    """보강 항목이 어떤 워크플로우에서 사용 중인지 가리키는 참조"""
    id: str  # workflow UUID
    name: str


class KnowledgeBaseSummary(BaseModel):
    """서비스 detail에 인라인되는 지식베이스 요약. UI 표시용 핵심 필드만 포함."""
    id: int  # = surro_knowledge_id (= component.knowledge_base_id)
    name: str
    description: Optional[str] = None
    type: str = "RAG"  # gateway 파생 상수 (upstream 스키마에 type 필드 없음)
    collection_name: Optional[str] = None
    embedding_model_id: Optional[int] = None
    search_method_id: Optional[int] = None
    created_by: Optional[str] = None  # gateway DB의 member_id
    created_at: Optional[datetime] = None  # gateway DB
    workflow_refs: List[WorkflowRefSchema] = Field(default_factory=list)


class ModelSummary(BaseModel):
    """서비스 detail에 인라인되는 모델 요약."""
    id: int
    name: str
    description: Optional[str] = None
    provider: Optional[str] = None  # provider_info.name 평탄화
    model_type: Optional[str] = None  # type_info.name
    format: Optional[str] = None  # format_info.name
    task: Optional[str] = None
    visibility: Optional[str] = None
    created_at: Optional[datetime] = None  # upstream
    workflow_refs: List[WorkflowRefSchema] = Field(default_factory=list)


class PromptSummary(BaseModel):
    """서비스 detail에 인라인되는 프롬프트 요약."""
    id: int  # = surro_prompt_id (= component.prompt_id)
    name: str
    description: Optional[str] = None
    content: Optional[str] = None
    variables: List[str] = Field(default_factory=list)  # prompt_variable.name 평탄화
    created_at: Optional[datetime] = None  # gateway DB (upstream 응답에 없음)
    created_by: Optional[str] = None  # gateway DB
    workflow_refs: List[WorkflowRefSchema] = Field(default_factory=list)


# 서비스 상세 응답 (외부 정보 포함)
class ServiceDetailResponse(BaseModel):
    # 내부 DB 값
    id: int
    name: str
    description: Optional[str]
    tags: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    created_by: str
    surro_service_id: str

    # 외부 API 값 (원하는 필드만)
    workflow_count: Optional[int] = 0
    workflows: List[WorkflowBaseSchema] = Field(default_factory=list)
    monitoring_data: Optional[ServiceMonitoringData] = None

    # 워크플로우 컴포넌트 추출 후 보강 (best-effort, 권한 통과 항목만)
    knowledge_bases: List[KnowledgeBaseSummary] = Field(default_factory=list)
    models: List[ModelSummary] = Field(default_factory=list)
    prompts: List[PromptSummary] = Field(default_factory=list)


# 서비스 목록 응답
class ServiceListResponse(BaseModel):
    data: List[ServiceResponse]
    total: int
    page: int
    size: int
