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
