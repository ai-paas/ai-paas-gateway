"""Any Cloud v0.3.0 라우트의 권한/경로/라우팅 회귀 테스트.

PR #81 에서 확인된 4건을 고정한다.
1. 인프라 변경계 라우트가 admin 전용인지 (라우트 정의 자체를 검사 — 신규 라우트 추가 시에도 걸림)
2. pod exec WebSocket 이 무인증 연결을 거부하는지
3. clusterName 등에 `../` 를 넣어도 upstream 경로를 벗어나지 못하는지
4. `install-all` 이 `{rule_set_id}` wildcard 에 먹히지 않는지
"""

import re

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


# ---------------------------------------------------------------------------
# 2차 리뷰 대응 — upstream v0.3.0 lockstep / 텍스트 응답 / 페이지 기준
# ---------------------------------------------------------------------------

# upstream ClusterKubernetesController 가 문서화한 지원 kind (release/v0.3.0)
UPSTREAM_KINDS = {
    "pods", "services", "deployments", "statefulsets", "daemonsets", "replicasets",
    "configmaps", "secrets", "persistentvolumeclaims", "jobs", "cronjobs",
    "nodes", "namespaces", "persistentvolumes", "storageclasses",
    "customresourcedefinitions",
}
# 정책상 게이트웨이가 막는 kind (tests/test_security_p0.py 가 고정)
POLICY_BLOCKED = {"secrets", "customresourcedefinitions"}
# upstream ApiValidationConstants.K8S_KIND_PATTERN
K8S_KIND_PATTERN = re.compile(r"^[a-z][a-z0-9]{0,49}$")


def test_resource_type_allowlist_matches_upstream_contract():
    """게이트웨이 화이트리스트가 upstream 규격보다 좁으면 프론트가 여기서 먼저 403 을 받는다."""
    from app.routes.any_cloud import _ALLOWED_KUBERNETES_RESOURCE_TYPES as allowed

    bad_case = sorted(k for k in allowed if not K8S_KIND_PATTERN.match(k))
    assert bad_case == [], f"upstream K8S_KIND_PATTERN 위반(대문자 등): {bad_case}"
    # upstream 이 모르는 kind 를 허용하면 안 되고, 정책 차단분은 빠져 있어야 한다
    assert allowed <= UPSTREAM_KINDS
    assert allowed == UPSTREAM_KINDS - POLICY_BLOCKED


@pytest.mark.parametrize("kind", sorted(["statefulsets", "replicasets", "daemonsets", "configmaps"]))
def test_frontend_resource_types_pass_validation(kind):
    """현재 프론트가 실제로 호출하는 kind 는 통과해야 한다."""
    from app.routes.any_cloud import _validate_kubernetes_resource_type

    assert _validate_kubernetes_resource_type(kind) == kind


def test_unknown_resource_type_is_rejected():
    from fastapi import HTTPException as _HTTPException

    from app.routes.any_cloud import _validate_kubernetes_resource_type

    for bad in ("../secrets", "statefulSets", "secrets", "clusterRoleBindings"):
        with pytest.raises(_HTTPException) as exc:
            _validate_kubernetes_resource_type(bad)
        assert exc.value.status_code == 403, bad


def test_every_resource_type_route_validates_kind():
    """{resource_type} 을 받는 라우트는 전부 화이트리스트를 통과시켜야 한다."""
    import inspect

    from app.routes import any_cloud as mod

    missing = []
    for route, path, _ in _any_cloud_routes():
        if "{resource_type}" not in path:
            continue
        fn = getattr(route, "endpoint", None)
        if fn is None:
            continue
        if "_validate_kubernetes_resource_type" not in inspect.getsource(fn):
            missing.append(f"{sorted(route.methods)[0]} {path}")
    assert missing == [], f"kind 검증 누락: {missing}"


def _mock_service(monkeypatch, handler):
    from app.services import any_cloud_service as mod

    svc = mod.any_cloud_service
    monkeypatch.setattr(svc, "base_url", "http://backend:8888")
    monkeypatch.setattr(svc, "client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return svc


def test_text_responses_do_not_500(monkeypatch):
    """PEM / kubeconfig 는 JSON 이 아니다 — _make_request 경로를 타면 500 이 된다."""
    import asyncio

    def handler(request):
        if request.url.path.endswith("/ssh-key"):
            return httpx.Response(200, text="-----BEGIN RSA PRIVATE KEY-----",
                                  headers={"content-type": "text/plain"})
        return httpx.Response(200, text="apiVersion: v1\nkind: Config",
                              headers={"content-type": "application/yaml"})

    svc = _mock_service(monkeypatch, handler)
    ui = {"member_id": "a", "role": "admin", "name": "T"}

    pem = asyncio.run(svc.issue_vm_ssh_key("vm1", ui, fmt="pem"))
    assert pem.startswith("-----BEGIN RSA PRIVATE KEY-----")

    kubeconfig = asyncio.run(svc.download_vm_kubeconfig("vm1", ui))
    assert kubeconfig.startswith("apiVersion: v1")


def test_degraded_signal_is_forwarded(monkeypatch):
    """agent 장애로 인한 부분가용을 '리소스 없음'으로 보이게 두지 않는다."""
    import asyncio

    def handler(request):
        return httpx.Response(200, json={
            "items": [], "degraded": True, "degradedReason": "AGENT_INACTIVE",
            "degradedMessage": "Cluster agent not connected",
        })

    svc = _mock_service(monkeypatch, handler)
    result = asyncio.run(svc.get_kubernetes_resource(
        "pods", "c1", "default", {"member_id": "a", "role": "admin", "name": "T"}))
    assert result.data == []
    assert result.degraded is True
    assert result.degradedReason == "AGENT_INACTIVE"


def test_admin_agents_page_is_one_based(monkeypatch):
    """public page 는 1-based, upstream 은 0-based — adapter 에서 변환한다."""
    import asyncio

    seen = {}

    def handler(request):
        seen["page"] = request.url.params.get("page")
        return httpx.Response(200, json={"items": [{"id": "a1"}], "total": 1})

    svc = _mock_service(monkeypatch, handler)
    result = asyncio.run(svc.get_admin_agents(
        {"member_id": "a", "role": "admin", "name": "T"}, page=1, size=50))
    assert seen["page"] == "0"
    assert result.page == 1
    assert result.has_next is False


def test_disabled_provider_returns_503(monkeypatch):
    from app.routes import any_cloud as mod

    monkeypatch.setattr(mod.settings, "ANY_CLOUD_ENABLED", False)
    client = TestClient(app)
    response = client.get(f"{API}/any-cloud/system/clusters")
    assert response.status_code == 503
    assert "disabled" in response.json()["detail"]


def test_no_unencoded_path_interpolation_in_routes():
    """라우트 파일에서 upstream 경로를 조립할 때도 세그먼트를 인코딩해야 한다."""
    import pathlib

    source = pathlib.Path("app/routes/any_cloud.py").read_text(encoding="utf-8")
    offenders = [
        line.strip() for line in source.splitlines()
        if 'path=f"' in line and "_seg(" not in line and "quote(" not in line
    ]
    assert offenders == [], f"미인코딩 경로 보간: {offenders}"
