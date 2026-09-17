"""
백엔드 엔드포인트마다 게이트웨이 라우팅이 있는지 고정한다.

백엔드에 경로를 추가하고 게이트웨이에 라우팅을 빠뜨리면 화면에서 Not Found 가 난다.
자격증명 가용성 확인과 값 조회에서 두 번 그랬다. 백엔드 테스트는 이걸 잡지 못한다 —
백엔드는 정상이기 때문이다.
"""

from app.routes.any_cloud import (
    router_credential,
    router_events,
    router_node,
    router_shell,
    router_vm,
)


def _paths(router):
    return {(route.path, tuple(sorted(route.methods))) for route in router.routes}


def test_credential_health_and_reveal_are_routed():
    paths = _paths(router_credential)

    assert ("/any-cloud/credentials/{credential_id}/health", ("POST",)) in paths
    assert ("/any-cloud/credentials/{credential_id}/health/refresh", ("POST",)) in paths
    # 값 조회는 GET 이다. 목록 응답에는 값이 없고 이 경로만 노출한다.
    assert ("/any-cloud/credentials/{credential_id}/reveal", ("GET",)) in paths


def test_credential_crud_is_routed():
    paths = {path for path, _ in _paths(router_credential)}

    assert "/any-cloud/credentials" in paths
    assert "/any-cloud/credentials/{credential_id}" in paths


def test_vm_list_accepts_include_deleted():
    """토글이 삭제된 것을 "함께" 보려면 파라미터가 전달돼야 한다."""
    route = next(r for r in router_vm.routes if r.path == "/any-cloud/vms" and "GET" in r.methods)

    # alias 를 쓰면 내부 이름과 노출 이름이 다르다. 클라이언트가 보는 쪽을 본다.
    exposed = {p.field_info.alias or p.name for p in route.dependant.query_params}
    assert "includeDeleted" in exposed
    assert "status" in exposed


def test_node_list_is_routed_outside_the_vm_namespace():
    """/any-cloud/vms/{vm_name} 와 겹치지 않게 별도 namespace 여야 한다."""
    paths = _paths(router_node)

    assert ("/any-cloud/nodes", ("GET",)) in paths


def test_node_list_can_narrow_to_one_cluster():
    """클러스터 상세의 노드 탭이 같은 경로를 스코프만 좁혀 쓴다."""
    route = next(r for r in router_node.routes if r.path == "/any-cloud/nodes" and "GET" in r.methods)

    exposed = {p.field_info.alias or p.name for p in route.dependant.query_params}
    assert "clusterName" in exposed
    assert "provider" in exposed


def test_vm_delete_accepts_force():
    """강제 삭제는 백엔드의 force 파라미터로만 열린다."""
    route = next(r for r in router_vm.routes if r.path == "/any-cloud/vms/{vm_name}" and "DELETE" in r.methods)

    exposed = {p.field_info.alias or p.name for p in route.dependant.query_params}
    assert "force" in exposed


def test_sse_streams_are_routed():
    """진행 상황 스트림이 게이트웨이에 없으면 화면은 영영 폴링만 한다 — 실제로 404 였다."""
    paths = _paths(router_events)

    assert ("/any-cloud/events", ("GET",)) in paths
    assert ("/any-cloud/operations/{operation_id}/events", ("GET",)) in paths


def test_credential_update_is_routed():
    """수정은 PATCH 다 — 값은 통째로 교체되지만 설명만 보내는 경우가 더 흔하다."""
    paths = _paths(router_credential)

    assert ("/any-cloud/credentials/{credential_id}", ("PATCH",)) in paths


def test_node_debug_pod_is_routed():
    """터미널은 백엔드에 이미 있던 debug-pod 를 쓴다 — 같은 일을 두 번 만들지 않는다."""
    paths = _paths(router_shell)

    assert ("/any-cloud/clusters/{cluster_name}/nodes/{node_name}/debug-pod", ("POST",)) in paths


def test_node_ssh_websocket_is_routed():
    """노드 SSH 는 파드 exec 와 다른 경로다 — 클러스터가 죽었을 때 쓰라고 만든 것이라
    에이전트를 거치는 경로로 대신할 수 없다."""
    paths = {r.path for r in router_vm.routes}

    assert "/any-cloud/vms/{vm_name}/nodes/{host}/ssh" in paths


def _app_ws_paths():
    """앱에 실제로 붙은 WebSocket 경로.

    라우터에 선언만 하고 main 에 include 하지 않으면 Starlette 는 그 경로를 찾지 못해 403 으로
    닫는다. 라우터만 들여다보는 위 검사들은 그걸 통과시킨다 — 실제로 노드 SSH 터미널이 그렇게
    한 번도 연결되지 못했다.
    """
    from starlette.routing import WebSocketRoute

    from app.main import app

    return {route.path for route in app.routes if isinstance(route, WebSocketRoute)}


def test_node_ssh_websocket_is_mounted_on_the_app():
    assert "/api/v1/any-cloud/vms/{vm_name}/nodes/{host}/ssh" in _app_ws_paths()


def test_pod_exec_websocket_is_mounted_on_the_app():
    assert (
        "/api/v1/any-cloud/kubernetes/clusters/{cluster_name}/pods/{namespace}/{pod_name}/exec"
        in _app_ws_paths()
    )


def test_credential_schema_is_routed():
    """화면이 KEY=VALUE 를 직접 받지 않으려면 프로바이더별 입력 필드를 물어볼 수 있어야 한다."""
    from app.routes.any_cloud import router_provider

    paths = _paths(router_provider)

    assert ("/any-cloud/providers/{provider}/credential-schema", ("GET",)) in paths
