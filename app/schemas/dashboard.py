"""관리자 대시보드 응답 스키마.

설계 원칙:
- summary/top/infra 류는 wrapper 없는 단일 객체 (CLAUDE.md §5 페이지네이션은 리스트 도메인에만 적용)
- 가속기는 accelerators[] 배열 + kind 필드로 GPU/NPU/TPU 확장 대응 (breaking change 없이)
- upstream(Any Cloud)의 type/key 같은 키워드는 노출 금지 — adapter 내부에서 변환
"""
from datetime import datetime
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
