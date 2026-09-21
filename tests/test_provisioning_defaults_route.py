"""일괄 생성 화면이 쓰는 경로가 게이트웨이에 있는지 본다.

백엔드에 엔드포인트를 만들어도 게이트웨이에 중계를 빼면 화면에서만 빈 목록이 된다.
주소 체계가 달라(/v1/... 대 /api/v1/any-cloud/...) 백엔드 테스트로는 잡히지 않는다.
"""

from app.main import app


def test_provisioning_defaults_route_is_registered():
    paths = {route.path for route in app.routes}
    assert "/api/v1/any-cloud/providers/provisioning-defaults" in paths


def test_fixed_path_is_declared_before_the_provider_variable():
    """/providers/{provider}/... 가 먼저면 provider="provisioning-defaults" 로 잡힌다."""
    ordered = [route.path for route in app.routes if "/any-cloud/providers/" in route.path]
    fixed = ordered.index("/api/v1/any-cloud/providers/provisioning-defaults")
    variable = next(i for i, path in enumerate(ordered) if "{provider}" in path)
    assert fixed < variable


def test_vm_preflight_route_is_registered():
    """생성 화면이 쓰는 검증 경로. 빠지면 화면에서만 검증이 건너뛰어진다."""
    paths = {route.path for route in app.routes}
    assert "/api/v1/any-cloud/vms/preflight" in paths


def test_preflight_is_declared_before_the_vm_name_variable():
    """POST /vms/{vm_name} 이 먼저면 vm_name="preflight" 로 잡힌다.

    메서드가 다르면 충돌하지 않는다 — 같은 POST 끼리만 순서를 본다.
    """
    posts = [
        route.path
        for route in app.routes
        if route.path.startswith("/api/v1/any-cloud/vms") and "POST" in getattr(route, "methods", set())
    ]
    fixed = posts.index("/api/v1/any-cloud/vms/preflight")
    variable = next((i for i, path in enumerate(posts) if "{vm_name}" in path), len(posts))
    assert fixed < variable
