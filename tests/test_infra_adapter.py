"""infra_adapter mock 응답 구조 검증.

Any Cloud 연동 전이라 _USE_MOCK=True 상태에서 응답 구조만 보장한다.
실제 연동 시 _convert_* 함수가 동일 스키마를 만족해야 한다는 계약 테스트.
"""
import asyncio

from app.services import infra_adapter


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


def test_get_infra_status_returns_clusters():
    resp = _run(infra_adapter.get_infra_status())
    assert resp.has_data is True
    assert len(resp.clusters) >= 1
    for c in resp.clusters:
        assert c.status in ("connected", "disconnected", "error", "unknown")


def test_get_infra_nodes_structure():
    resp = _run(infra_adapter.get_infra_nodes("any-cloud-dev"))
    assert resp.cluster.name == "any-cloud-dev"
    assert len(resp.nodes) >= 1

    for node in resp.nodes:
        r = node.resources
        assert r.cpu.unit == "core"
        assert r.memory.unit == "GiB"
        assert isinstance(r.filesystems, list)
        assert isinstance(r.accelerators, list)


def test_accelerator_kinds_and_npu_placeholder():
    """GPU는 available, NPU는 not_available placeholder 포함."""
    resp = _run(infra_adapter.get_infra_nodes("c1"))
    node_with = next(n for n in resp.nodes if n.resources.accelerators)
    kinds = {a.kind for a in node_with.resources.accelerators}
    assert "gpu" in kinds

    gpu = next(a for a in node_with.resources.accelerators if a.kind == "gpu")
    assert gpu.status == "available"
    assert gpu.metrics.get("utilization_percent") is not None

    npu = next(
        (a for a in node_with.resources.accelerators if a.kind == "npu"),
        None,
    )
    assert npu is not None
    assert npu.status == "not_available"


def test_get_infra_resources_cpu_only():
    resp = _run(infra_adapter.get_infra_resources("c1", "cpu"))
    assert resp.resource_type == "cpu"
    assert len(resp.nodes) >= 1
    for entry in resp.nodes:
        assert entry.cpu is not None
        assert entry.memory is None
        assert entry.filesystems is None
        assert entry.accelerators is None


def test_get_infra_resources_accelerator_returns_all_kinds():
    resp = _run(infra_adapter.get_infra_resources("c1", "accelerator"))
    assert resp.resource_type == "accelerator"

    accel_nodes = [n for n in resp.nodes if n.accelerators]
    assert len(accel_nodes) >= 1

    for a in accel_nodes[0].accelerators:
        assert a.kind in ("gpu", "npu", "tpu", "other")
