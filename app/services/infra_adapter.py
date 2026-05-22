"""Any Cloud → 대시보드 스키마 어댑터.

현재 Any Cloud 연동이 미확정이라 mock 샘플을 반환한다.
연동 완료 후 `_USE_MOCK=False`로 토글하고 `_convert_*`에 변환 로직을 채운다.

원칙(CLAUDE.md §5):
- public 응답에 upstream 키워드(type/key/usage_namespace 등) 노출 금지
- accelerators[] 구조로 GPU/NPU/TPU 확장 흡수 (kind 필드 매핑)
"""
from datetime import datetime
from typing import List

from app.schemas.dashboard import (
    Accelerator,
    ClusterStatus,
    FilesystemUsage,
    InfraNodesResponse,
    InfraResourcesResponse,
    InfraStatusResponse,
    NodeInfo,
    NodeResourceEntry,
    NodeResources,
    ResourceTypeLiteral,
    ResourceUsage,
)

_USE_MOCK = True


def _now() -> datetime:
    return datetime.utcnow()


def _mock_clusters() -> List[ClusterStatus]:
    now = _now()
    return [
        ClusterStatus(name="any-cloud-dev", status="connected", last_checked_at=now),
        ClusterStatus(name="any-cloud-prod", status="connected", last_checked_at=now),
    ]


def _mock_node(name: str, status: str = "ready", with_accelerator: bool = True) -> NodeInfo:
    accelerators: List[Accelerator] = []
    if with_accelerator:
        accelerators.append(
            Accelerator(
                kind="gpu",
                status="available",
                vendor="nvidia",
                model="A100",
                total=4,
                used=1,
                unit="device",
                metrics={
                    "memory_used_gib": 40,
                    "memory_total_gib": 80,
                    "utilization_percent": 72,
                },
            )
        )
        # NPU는 확장 예정 — placeholder
        accelerators.append(
            Accelerator(
                kind="npu",
                status="not_available",
                metrics={},
            )
        )

    return NodeInfo(
        name=name,
        status=status,  # type: ignore[arg-type]
        resources=NodeResources(
            cpu=ResourceUsage(total=64, used=20, unit="core"),
            memory=ResourceUsage(total=256, used=90, unit="GiB"),
            filesystems=[
                FilesystemUsage(mount="/", total=1024, used=480, unit="GiB"),
            ],
            accelerators=accelerators,
        ),
    )


def _mock_nodes_response(cluster: str) -> InfraNodesResponse:
    cluster_status = ClusterStatus(
        name=cluster,
        status="connected",
        last_checked_at=_now(),
    )
    nodes = [
        _mock_node("master-1"),
        _mock_node("master-2", status="warning"),
        _mock_node("worker-1"),
        _mock_node("worker-2", with_accelerator=False),
    ]
    return InfraNodesResponse(cluster=cluster_status, nodes=nodes)


async def get_infra_status() -> InfraStatusResponse:
    """클러스터 목록 + 연결 상태. 미연동/미등록 시 has_data=False."""
    if not _USE_MOCK:
        # TODO: any_cloud_service.get_clusters() + get_cluster_test_connection()
        raise NotImplementedError("Any Cloud 연동 후 구현")

    clusters = _mock_clusters()
    return InfraStatusResponse(clusters=clusters, has_data=bool(clusters))


async def get_infra_nodes(cluster: str) -> InfraNodesResponse:
    """클러스터 내 노드 상태 + 노드별 리소스(CPU/메모리/파일시스템/가속기)."""
    if not _USE_MOCK:
        # TODO: any_cloud_service.get_monitoring_node(cluster)
        raise NotImplementedError("Any Cloud 연동 후 구현")

    return _mock_nodes_response(cluster)


async def get_infra_resources(
    cluster: str, resource_type: ResourceTypeLiteral
) -> InfraResourcesResponse:
    """노드별 특정 리소스 추출. resource_type=accelerator는 GPU/NPU/TPU 전체."""
    if not _USE_MOCK:
        # TODO: any_cloud_service.get_monitoring_metric(cluster, <upstream type>, <upstream key>, ...)
        # adapter 안에서 cpu/memory/filesystem/accelerator → upstream type/key 매핑
        raise NotImplementedError("Any Cloud 연동 후 구현")

    nodes_resp = _mock_nodes_response(cluster)
    entries: List[NodeResourceEntry] = []
    for node in nodes_resp.nodes:
        entry = NodeResourceEntry(name=node.name, status=node.status)
        if resource_type == "cpu":
            entry.cpu = node.resources.cpu
        elif resource_type == "memory":
            entry.memory = node.resources.memory
        elif resource_type == "filesystem":
            entry.filesystems = node.resources.filesystems
        elif resource_type == "accelerator":
            entry.accelerators = node.resources.accelerators
        entries.append(entry)

    return InfraResourcesResponse(
        cluster=nodes_resp.cluster,
        resource_type=resource_type,
        nodes=entries,
    )
