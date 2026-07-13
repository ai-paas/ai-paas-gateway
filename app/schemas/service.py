from datetime import datetime
from typing import List, Optional, Dict, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

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


# 단일 기간 메트릭 (1h/1d/1w 각각의 값)
class PeriodMetrics(BaseModel):
    message_count: int = Field(0, description="해당 기간 총 메시지 수")
    active_users: int = Field(0, description="해당 기간 활성 사용자 수")
    token_usage: int = Field(0, description="해당 기간 토큰 사용량")
    avg_interaction_count: float = Field(0.0, description="해당 기간 평균 사용자 상호작용 수")
    response_time_ms: Optional[float] = Field(
        None, description="해당 기간 평균 응답 시간(ms). 요청 없으면 null"
    )
    error_count: int = Field(0, description="해당 기간 오류 수")
    success_rate: Optional[float] = Field(
        None, description="해당 기간 성공률(%). 요청 없으면 null"
    )


# 평면 7필드(구 spec) 시그너처 — 신/구 spec 판별용
_LEGACY_PERIOD_KEYS = {
    "message_count",
    "active_users",
    "token_usage",
    "avg_interaction_count",
    "response_time_ms",
    "error_count",
    "success_rate",
}


# 모니터링 메트릭 스키마 (기간별 중첩)
# upstream lockstep: 명세상 "기간 키(1h/1d/1w)는 항상 존재" → required로 둠.
# upstream이 partial response(1h/1d/1w 중 일부만)를 보내면 ValidationError로 502 처리되어
# 조용한 0 채움 방지.
#
# Transitional hybrid: upstream MLOps가 신 spec(1h/1d/1w 중첩) 배포 전 단계에서 구 spec
# (평면 7필드)을 보내는 동안에도 게이트웨이 detail API가 작동하도록, 구 spec 페이로드를
# 1h로 매핑하고 1d/1w는 데이터 없음(빈 PeriodMetrics)으로 채움. upstream이 신 spec으로
# 전환되면 자동으로 신 spec 경로로 흐름.
class MonitoringMetrics(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    period_1h: PeriodMetrics = Field(alias="1h", description="최근 1시간 집계")
    period_1d: PeriodMetrics = Field(alias="1d", description="최근 1일(24시간) 집계")
    period_1w: PeriodMetrics = Field(alias="1w", description="최근 1주일(7일) 집계")

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_flat(cls, data: Any) -> Any:
        """구 spec(평면 7필드) → 신 spec(1h/1d/1w 중첩)으로 정규화.

        판별 조건: dict이며 1h/1d/1w 키가 하나도 없고 평면 7필드 중 하나 이상 보일 때만
        구 spec으로 간주. 부분 신 spec(1d 누락 등)은 이 단계에서 건드리지 않고 normal
        validator가 거부하도록 통과시킨다.
        """
        if not isinstance(data, dict):
            return data
        has_period_keys = bool({"1h", "1d", "1w"} & data.keys())
        if has_period_keys:
            return data
        if not (_LEGACY_PERIOD_KEYS & data.keys()):
            return data
        # 구 spec: 평면 7필드 → 1h. 1d/1w는 데이터 없음으로.
        legacy_period = {k: data[k] for k in _LEGACY_PERIOD_KEYS if k in data}
        return {"1h": legacy_period, "1d": {}, "1w": {}}


# 워크플로우 모니터링 스키마
class WorkflowMonitoring(BaseModel):
    workflow_id: str = Field(description="워크플로우 ID")
    workflow_name: str = Field(description="워크플로우 이름")
    metrics: MonitoringMetrics = Field(description="해당 워크플로우의 기간별 메트릭 (1h/1d/1w)")
    last_updated: datetime = Field(description="집계 기준 시각 (= aggregated_at)")


# 서비스 모니터링 데이터 스키마
class ServiceMonitoringData(BaseModel):
    total_metrics: MonitoringMetrics = Field(description="전체 서비스 기간별 메트릭")
    workflow_metrics: List[WorkflowMonitoring] = Field(
        default_factory=list, description="워크플로우별 기간별 메트릭"
    )
    aggregated_at: datetime = Field(
        description="집계 기준 시각(UTC). 각 기간(1h/1d/1w)의 끝점"
    )

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_timestamps(cls, data: Any) -> Any:
        """구 spec(period_start/period_end) → 신 spec(aggregated_at)으로 정규화.

        upstream MLOps 구 spec은 period_end가 집계 끝점이므로 그것을 aggregated_at으로
        매핑. period_start는 신 spec에서 의미가 사라지므로 폐기. workflow_metrics 항목의
        last_updated는 구 spec에도 존재하므로 그대로 통과.
        """
        if not isinstance(data, dict):
            return data
        if "aggregated_at" in data:
            return data
        if "period_end" in data:
            data = dict(data)  # 원본 mutation 방지
            data["aggregated_at"] = data.get("period_end")
        return data


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
    """외부 API 상세 응답.

    upstream contract: MLOps ServiceDetailSchema에는 workflow_count 키가 없고 workflows 배열만
    노출한다 (브리프 ServiceBriefSchema에만 workflow_count 존재). 부모 ExternalServiceResponse의
    default 0이 그대로 노출되면 실제 workflows 길이와 어긋나므로, detail 페이로드에서는
    workflow_count == len(workflows)로 자동 보정한다.
    """
    workflows: List[WorkflowBaseSchema] = Field(default_factory=list)
    monitoring_data: Optional[ServiceMonitoringData] = None

    @model_validator(mode="before")
    @classmethod
    def _derive_workflow_count(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if "workflow_count" not in data:
            data = dict(data)
            data["workflow_count"] = len(data.get("workflows") or [])
        return data


# 서비스 생성 요청
class ServiceCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)


# 서비스 수정 요청
class ServiceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
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
