"""Any Cloud v0.3.0 라우트의 권한/경로/라우팅 회귀 테스트.

PR #81 에서 확인된 4건을 고정한다.
1. 인프라 변경계 라우트가 admin 전용인지 (라우트 정의 자체를 검사 — 신규 라우트 추가 시에도 걸림)
2. pod exec WebSocket 이 무인증 연결을 거부하는지
3. clusterName 등에 `../` 를 넣어도 upstream 경로를 벗어나지 못하는지
4. `install-all` 이 `{rule_set_id}` wildcard 에 먹히지 않는지
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_admin_user, get_current_user
from app.main import app
from app.routes import any_cloud
from app.services.any_cloud_service import _seg

API = "/api/v1"

# 조회 성격이라 일반 사용자에게 열어 둔 변경계 라우트 (모니터링 배치 조회)
MUTATING_USER_ALLOWLIST = {("POST", f"{API}/any-cloud/monit/{{cluster_name}}/multi-query")}


def _any_cloud_routes():
    for route in app.routes:
        path = getattr(route, "path", "")
        if "/any-cloud" not in path:
            continue
        yield route, path, getattr(route, "methods", None) or set()


def _dependency_names(route) -> set:
    return {d.call.__name__ for d in route.dependant.dependencies if getattr(d, "call", None)}


def test_every_mutating_any_cloud_route_requires_admin():
    """POST/PUT/PATCH/DELETE 는 allowlist 를 빼면 전부 admin 이어야 한다."""
    offenders = []
    for route, path, methods in _any_cloud_routes():
        mutating = methods & {"POST", "PUT", "PATCH", "DELETE"}
        if not mutating:
            continue
        names = _dependency_names(route)
        for method in sorted(mutating):
            if (method, path) in MUTATING_USER_ALLOWLIST:
                continue
            if "get_current_admin_user" not in names:
                offenders.append(f"{method} {path}")
    assert offenders == [], f"admin 게이트 누락: {offenders}"


@pytest.mark.parametrize(
    "path",
    [
        f"{API}/any-cloud/credentials",
        f"{API}/any-cloud/audit-logs",
        f"{API}/any-cloud/system/cluster/{{cluster_name}}/kubeconfig",
        f"{API}/any-cloud/system/cluster/{{cluster_name}}/agent-bootstrap",
        f"{API}/any-cloud/vms/{{vm_name}}/kubeconfig",
    ],
)
def test_secret_bearing_reads_require_admin(path):
    """자격증명·kubeconfig·부트스트랩 토큰을 반출하는 조회는 admin 전용."""
    for route, route_path, methods in _any_cloud_routes():
        if route_path == path and "GET" in methods:
            assert "get_current_admin_user" in _dependency_names(route)
            return
    pytest.fail(f"라우트를 찾지 못함: {path}")


def test_pod_exec_websocket_rejects_anonymous():
    client = TestClient(app)
    url = f"{API}/any-cloud/kubernetes/clusters/c1/pods/kube-system/p1/exec"

    with pytest.raises(Exception):
        with client.websocket_connect(url):
            pass

    with pytest.raises(Exception):
        with client.websocket_connect(url, subprotocols=["bearer", "not-a-real-token"]):
            pass


def test_pod_exec_websocket_is_admin_only():
    for route, path, _ in _any_cloud_routes():
        if path.endswith("/exec"):
            assert "get_ws_admin_user" in _dependency_names(route)
            return
    pytest.fail("pod exec WebSocket 라우트를 찾지 못함")


def test_path_segment_encoding_blocks_traversal():
    """clusterName 에 ../ 를 넣어도 upstream 경로를 벗어나지 못한다.

    httpx 는 URL 조립 시 dot-segment 를 정규화하므로 인코딩하지 않으면 실제로 다른
    엔드포인트가 호출된다. 비교 대상은 wire 로 나가는 raw_path.
    """
    hostile = "../../admin/agents"
    base = "http://backend:8888/v1/clusters/{}/namespaces/-/pods"

    # 인코딩 없이 넣으면 upstream 의 /admin/agents 로 탈출한다 (회귀 감시용 대조군)
    escaped = httpx.URL(base.format(hostile)).raw_path
    assert escaped == b"/admin/agents/namespaces/-/pods"

    # _seg 를 거치면 한 세그먼트 안에 갇힌다
    guarded = httpx.URL(base.format(_seg(hostile))).raw_path
    assert guarded == b"/v1/clusters/..%2F..%2Fadmin%2Fagents/namespaces/-/pods"

    # 정상 값은 그대로 통과 (no-op)
    assert _seg("imported-aws-01") == "imported-aws-01"
    assert _seg("kube-system") == "kube-system"


def test_install_all_is_not_shadowed_by_rule_set_id():
    """`install-all` 이 `{rule_set_id}` wildcard 보다 먼저 선언돼 있어야 한다."""
    paths = [p for _, p, m in _any_cloud_routes() if "alert-rules" in p and "POST" in m]
    install_all = f"{API}/any-cloud/clusters/{{cluster_name}}/observability/alert-rules/install-all"
    wildcard = f"{API}/any-cloud/clusters/{{cluster_name}}/observability/alert-rules/{{rule_set_id}}"
    assert paths.index(install_all) < paths.index(wildcard)


def test_multi_query_rejects_oversized_batch(admin_member):
    """fan-out 증폭 방지 — queries 상한(50) 초과는 422."""
    app.dependency_overrides[get_current_user] = lambda: admin_member
    app.dependency_overrides[get_current_admin_user] = lambda: admin_member
    try:
        client = TestClient(app)
        body = {"queries": [{"name": f"q{i}", "query": "up"} for i in range(51)]}
        response = client.post(f"{API}/any-cloud/monit/c1/multi-query", json=body)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_no_duplicate_any_cloud_routes():
    seen = set()
    duplicates = []
    for _, path, methods in _any_cloud_routes():
        for method in methods or {"WEBSOCKET"}:
            if (method, path) in seen:
                duplicates.append(f"{method} {path}")
            seen.add((method, path))
    assert duplicates == [], f"중복 라우트: {duplicates}"


def test_paged_response_has_next_covers_both_modes():
    from app.schemas.any_cloud import AnyCloudPagedResponse

    offset_mid = AnyCloudPagedResponse.create(data=[1], total=10, page=1, size=5)
    offset_last = AnyCloudPagedResponse.create(data=[1], total=10, page=2, size=5)
    cursor = AnyCloudPagedResponse.create(data=[1], total=1, page=1, size=20, next_page_token="tok")

    assert offset_mid.has_next is True
    assert offset_last.has_next is False
    assert cursor.has_next is True
    assert cursor.nextPageToken == "tok"


def test_upstream_5xx_is_mapped_to_502():
    """upstream 5xx 본문을 그대로 프론트에 흘리지 않는다."""
    from fastapi import HTTPException

    from app.services.any_cloud_service import raise_for_upstream

    response = httpx.Response(500, text="internal stacktrace with secrets")
    with pytest.raises(HTTPException) as exc:
        raise_for_upstream(response, "/v1/clusters/x")
    assert exc.value.status_code == 502
    assert "stacktrace" not in exc.value.detail

    # 4xx 는 사유를 그대로 전달해야 프론트가 검증 실패를 표시할 수 있다
    response = httpx.Response(400, json={"detail": "clusterName is invalid"})
    with pytest.raises(HTTPException) as exc:
        raise_for_upstream(response, "/v1/clusters/x")
    assert exc.value.status_code == 400
    assert exc.value.detail == "clusterName is invalid"


def test_public_pagination_params_use_gateway_vocabulary():
    """public 시그니처에 upstream 페이지네이션 키워드를 노출하지 않는다."""
    banned = {"skip", "limit", "offset", "page_size", "pageSize"}
    # pageToken 은 K8s continue 토큰 pass-through 로 예외 표에 등록됨
    offenders = []
    for route, path, _ in _any_cloud_routes():
        if not hasattr(route, "dependant"):
            continue
        for param in route.dependant.query_params:
            if param.name in banned and path != f"{API}/any-cloud/monit/{{cluster_name}}/query" \
                    and path != f"{API}/any-cloud/monit/{{cluster_name}}/query_range":
                offenders.append(f"{path} -> {param.name}")
    assert offenders == [], f"upstream 키워드 노출: {offenders}"
