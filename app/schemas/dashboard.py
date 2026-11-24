"""관리자 대시보드 응답 스키마.

설계 원칙:
- summary/top/infra 류는 wrapper 없는 단일 객체 (CLAUDE.md §5 페이지네이션은 리스트 도메인에만 적용)
- 가속기는 accelerators[] 배열 + kind 필드로 GPU/NPU/TPU 확장 대응 (breaking change 없이)
- upstream(Any Cloud)의 type/key 같은 키워드는 노출 금지 — adapter 내부에서 변환
"""
from datetime import date, datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------- Summary ----------

class AssetCount(BaseModel):
    """도메인별 자산 카운트.

    - active: `deleted_at IS NULL AND is_active IS TRUE` (soft-delete 컬럼 없으면 = total)
    - inactive: `deleted_at IS NULL AND is_active IS FALSE` (soft-delete 컬럼 없으면 0)
    - deleted: `deleted_at IS NOT NULL` (soft-delete 컬럼 없으면 0)
    - total = active + inactive + deleted
    """
    total: int
    active: int
    inactive: int
    deleted: int


class UserCounts(BaseModel):
    total: int
    active: int
    inactive: int
    recent7d: int = Field(..., description="최근 7일 가입자")
    by_role: Dict[str, int] = Field(default_factory=dict, description="권한별 카운트")


class DashboardSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    users: UserCounts
    services: AssetCount
    workflows: AssetCount
    models: AssetCount
    model_improvements: AssetCount
    datasets: AssetCount
    experiments: AssetCount
    knowledge_bases: AssetCount
    prompts: AssetCount
    generated_at: datetime


class PersonalDashboardSummary(BaseModel):
    """본인 보유 자산만 집계 (admin용 users/infra 섹션 없음)."""
    model_config = ConfigDict(from_attributes=True)

    member_id: str
    services: AssetCount
    workflows: AssetCount
    models: AssetCount
    model_improvements: AssetCount
    datasets: AssetCount
    experiments: AssetCount
    knowledge_bases: AssetCount
    prompts: AssetCount
    generated_at: datetime


# ---------- Users Top ----------

DomainLiteral = Literal[
    "service", "workflow", "model", "model_improvement",
    "dataset", "experiment", "knowledge_base", "prompt",
]


class UserTopItem(BaseModel):
    member_id: str
    name: Optional[str] = None
    count: int


class UsersTopResponse(BaseModel):
    domain: DomainLiteral
    items: List[UserTopItem]


# ---------- Infra ----------

ClusterStatusLiteral = Literal["connected", "disconnected", "error", "unknown"]
NodeStatusLiteral = Literal["ready", "warning", "error", "unknown"]
AcceleratorKindLiteral = Literal["gpu", "npu", "tpu", "other"]
AcceleratorStatusLiteral = Literal["available", "not_available", "error"]
ResourceTypeLiteral = Literal["cpu", "memory", "filesystem", "accelerator"]


class ClusterStatus(BaseModel):
    name: str
    status: ClusterStatusLiteral
    last_checked_at: datetime
    message: Optional[str] = None


class InfraStatusResponse(BaseModel):
    clusters: List[ClusterStatus]
    has_data: bool = Field(..., description="클러스터 미등록이면 False (empty state)")


class ResourceUsage(BaseModel):
    total: float
    used: float
    unit: str


class FilesystemUsage(BaseModel):
    mount: str
    total: float
    used: float
    unit: str


class Accelerator(BaseModel):
    kind: AcceleratorKindLiteral
    status: AcceleratorStatusLiteral
    vendor: Optional[str] = None
    model: Optional[str] = None
    total: Optional[int] = None
    used: Optional[int] = None
    unit: str = "device"
    metrics: Dict[str, Any] = Field(default_factory=dict,
                                    description="공통 키: memory_used_gib, memory_total_gib, utilization_percent, temperature_celsius")
    message: Optional[str] = None


class NodeResources(BaseModel):
    cpu: ResourceUsage
    memory: ResourceUsage
    filesystems: List[FilesystemUsage]
    accelerators: List[Accelerator]


class NodeInfo(BaseModel):
    name: str
    status: NodeStatusLiteral
    resources: NodeResources


class InfraNodesResponse(BaseModel):
    cluster: ClusterStatus
    nodes: List[NodeInfo]


class NodeResourceEntry(BaseModel):
    """resource_type 필터링된 노드별 응답 (cpu/memory/filesystem/accelerator 중 하나만 채워짐)."""
    name: str
    status: NodeStatusLiteral
    cpu: Optional[ResourceUsage] = None
    memory: Optional[ResourceUsage] = None
    filesystems: Optional[List[FilesystemUsage]] = None
    accelerators: Optional[List[Accelerator]] = None


class InfraResourcesResponse(BaseModel):
    cluster: ClusterStatus
    resource_type: ResourceTypeLiteral
    nodes: List[NodeResourceEntry]


# ---------- Events (audit_logs) ----------

class AuditEventItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    actor_member_id: str
    target_member_id: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = Field(default=None, alias="metadata_json", serialization_alias="metadata")
    request_id: Optional[str] = None
    ip: Optional[str] = None
    created_at: datetime


class AuditEventListResponse(BaseModel):
    data: List[AuditEventItem]
    total: int
    page: int
    size: int


# ---------- Trends (Phase 3) ----------

TrendSourceLiteral = Literal["daily_stats", "materialized_view", "live"]


class TrendPoint(BaseModel):
    date: date
    value: int


class TrendSeries(BaseModel):
    domain: str  # service/workflow/.../signup
    metric: str  # created/deleted
    points: List[TrendPoint]


class TrendsResponse(BaseModel):
    start: date
    end: date
    days: int
    source: TrendSourceLiteral
    series: List[TrendSeries]
    generated_at: datetime


class TrendsRefreshResponse(BaseModel):
    rows_upserted: int
    refreshed_materialized_view: bool
    finished_at: datetime


# ---------- API metrics (Phase 4) ----------

class ApiMetricsPathItem(BaseModel):
    path_pattern: str
    status_class: str  # 2xx/3xx/4xx/5xx
    count: int
    avg_ms: Optional[float] = None
    max_ms: int
    p95_ms: Optional[int] = None  # histogram bucket 보간 근사


class ApiMetricsResponse(BaseModel):
    since: datetime
    generated_at: datetime
    buckets_ms: List[int]
    paths: List[ApiMetricsPathItem]


# ---------- Provider health (Phase 4) ----------

ProviderHealthStatusLiteral = Literal["healthy", "unhealthy", "disabled", "error"]


class ProviderHealthLatest(BaseModel):
    provider: str
    status: ProviderHealthStatusLiteral
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    last_checked_at: Optional[datetime] = None


class ProviderHealthHistoryPoint(BaseModel):
    ts: datetime
    status: ProviderHealthStatusLiteral
    latency_ms: Optional[int] = None


class ProviderHealthResponse(BaseModel):
    providers: List[ProviderHealthLatest]
    history: Dict[str, List[ProviderHealthHistoryPoint]] = Field(
        default_factory=dict, description="provider별 최근 N건 시계열"
    )
    generated_at: datetime


# ============================================================
# 개인 대시보드 — 서비스 카드 / 모니터링 / 활동 히스토리
# ============================================================

CacheSourceLiteral = Literal["cache", "live", "empty"]
DASHBOARD_PERIODS = ("1h", "1d", "1w")


# ---------- 서비스 현황 카드 ----------

class ServiceCardItem(BaseModel):
    """서비스 현황 카드 1건. name/description은 gateway DB, 카운트는 캐시(MLOps 파생)."""
    surro_service_id: str
    name: str
    description: Optional[str] = None
    workflow_count: int = Field(0, description="연결된 워크플로우 수")
    model_count: Optional[int] = Field(
        None, description="사용 모델 distinct 수. 미집계(옵션 off)/집계 실패 시 null"
    )


class MyServiceCardsResponse(BaseModel):
    member_id: str
    services: List[ServiceCardItem] = Field(default_factory=list)
    source: CacheSourceLiteral = Field(
        ..., description="cache=스냅샷 사용, live=이번 요청에서 즉시 집계, empty=보유 서비스 없음"
    )
    generated_at: datetime


# ---------- 서비스 모니터링 (1h/1d/1w) ----------

class DashboardPeriodMetrics(BaseModel):
    """단일 기간 메트릭. MLOps PeriodMetrics와 동일 필드(대시보드 응답 전용 사본)."""
    message_count: int = 0
    active_users: int = 0
    token_usage: int = 0
    avg_interaction_count: float = 0.0
    response_time_ms: Optional[float] = None
    error_count: int = 0
    success_rate: Optional[float] = None


class ServiceMonitoringItem(BaseModel):
    """서비스 1건의 기간별 메트릭."""
    surro_service_id: str
    name: str
    metrics: Dict[str, DashboardPeriodMetrics] = Field(
        default_factory=dict, description="기간별 메트릭. 키: 1h/1d/1w"
    )
    aggregated_at: Optional[datetime] = Field(None, description="MLOps 집계 기준 끝점")


class MetricRankItem(BaseModel):
    surro_service_id: str
    name: str
    value: float


class PeriodTopMetrics(BaseModel):
    """한 기간 안에서 메트릭별 Top N 순위."""
    message_count: List[MetricRankItem] = Field(default_factory=list)
    active_users: List[MetricRankItem] = Field(default_factory=list)
    token_usage: List[MetricRankItem] = Field(default_factory=list)
    avg_interaction_count: List[MetricRankItem] = Field(default_factory=list)


class MyServiceMonitoringResponse(BaseModel):
    member_id: str
    source: CacheSourceLiteral
    top_n: int = Field(..., description="순위 항목 수 (top.*[] 길이 상한)")
    services: List[ServiceMonitoringItem] = Field(
        default_factory=list, description="본인 서비스별 전체 기간 메트릭"
    )
    top: Dict[str, PeriodTopMetrics] = Field(
        default_factory=dict, description="기간(1h/1d/1w)별 메트릭 Top N 순위"
    )
    generated_at: datetime


# ---------- 활동 히스토리 (audit_logs 기반, k8s 이벤트 대체) ----------

class MyActivityItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str = Field(description="create/update/delete/restore/status_change 등")
    resource_type: str = Field(description="service/workflow/model/... 대상 도메인")
    resource_id: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = Field(
        default=None, serialization_alias="metadata",
        description="액션별 부가 JSON (예: {\"name\":\"...\"}, {\"from\":\"DRAFT\",\"to\":\"ACTIVE\"})",
    )
    created_at: datetime


class MyActivityListResponse(BaseModel):
    data: List[MyActivityItem]
    total: int
    page: int
    size: int
