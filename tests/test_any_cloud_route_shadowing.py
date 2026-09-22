"""라우트 선언 순서와 query 전달을 실제 요청 경로로 고정한다.

둘 다 시그니처만 봐서는 드러나지 않는다. 함수는 멀쩡히 존재하고 인자도 다 받는데,
FastAPI 가 다른 핸들러로 보내거나 인자가 upstream 까지 가지 않는다. TestClient 로
진짜 URL 을 태워야 잡힌다.
"""

from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.auth import get_current_admin_user, get_current_user
from app.main import app
from app.models.member import Member
from app.services.any_cloud_service import any_cloud_service


def _member() -> Member:
    member = Member()
    member.member_id = "tester"
    member.name = "테스터"
    member.email = "tester@example.com"
    return member


@contextmanager
def _client():
    # values 는 admin 전용이다. 두 의존성을 다 덮어야 라우팅만 검증할 수 있다.
    app.dependency_overrides[get_current_user] = _member
    app.dependency_overrides[get_current_admin_user] = _member
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()


@contextmanager
def _recorded_upstream(monkeypatch):
    """upstream 으로 나간 (method, path, params) 를 그대로 받아 둔다."""
    calls = []

    async def fake_request(self, method, path, user_info=None, **kwargs):
        calls.append((method, path, kwargs.get("params") or {}))
        return {"data": {}}

    monkeypatch.setattr(
        type(any_cloud_service), "_make_request", fake_request, raising=True
    )
    yield calls


def test_release_values_reaches_its_own_handler(monkeypatch):
    """/catalog/releases/{name}/values 가 {repoName}/{chartName}/values 에 가려지면 안 된다.

    가려지면 releases 가 저장소 이름으로 해석돼 차트 values 경로로 나간다. 200 이 떨어져
    실패로 보이지도 않는다.
    """
    with _recorded_upstream(monkeypatch) as calls, _client() as client:
        response = client.get(
            "/api/v1/any-cloud/catalog/releases/nginx-test/values",
            params={"clusterId": "cluster-001", "namespace": "default"},
        )

    assert response.status_code == 200, response.text
    assert len(calls) == 1
    _, path, params = calls[0]
    assert "helm-repos" not in path, f"차트 values 경로로 샜다: {path}"
    assert "nginx-test" in path
    assert params.get("namespace") == "default"


def test_chart_values_still_reaches_the_chart_handler(monkeypatch):
    """고정 경로를 앞으로 올리면서 동적 경로가 막히지 않았는지."""
    with _recorded_upstream(monkeypatch) as calls, _client() as client:
        response = client.get(
            "/api/v1/any-cloud/catalog/my-repo/nginx/values",
            params={"version": "15.4.4"},
        )

    assert response.status_code == 200, response.text
    _, path, _ = calls[0]
    assert "my-repo" in path and "nginx" in path


def test_release_resources_reaches_its_own_handler(monkeypatch):
    """resources 도 같은 자리에 있다. 지금은 안 가려지지만 순서에 기대고 있다."""
    with _recorded_upstream(monkeypatch) as calls, _client() as client:
        response = client.get(
            "/api/v1/any-cloud/catalog/releases/nginx-test/resources",
            params={"clusterId": "cluster-001", "namespace": "default"},
        )

    assert response.status_code == 200, response.text
    _, path, _ = calls[0]
    assert "helm-repos" not in path, f"차트 경로로 샜다: {path}"


def test_spec_filters_reach_upstream(monkeypatch):
    """minVcpu, minMemoryGb, gpu 가 백엔드까지 가야 한다.

    라우트가 받기만 하고 서비스에 넘기지 않으면 어떤 조건을 보내도 기본값으로 조회된다.
    화면에는 "조건에 맞는 사양이 없다" 가 아니라 엉뚱한 사양이 뜬다.
    """
    with _recorded_upstream(monkeypatch) as calls, _client() as client:
        response = client.get(
            "/api/v1/any-cloud/providers/provisioning-defaults",
            params={
                "provider": "aws",
                "minVcpu": 8,
                "minMemoryGb": 32,
                "gpu": "true",
            },
        )

    assert response.status_code == 200, response.text
    _, path, params = calls[0]
    assert path.endswith("/provisioning-defaults")
    assert params.get("provider") == "aws"
    assert params.get("minVcpu") == 8
    assert params.get("minMemoryGb") == 32
    assert params.get("gpu") is True


def test_gpu_false_is_not_dropped(monkeypatch):
    """gpu=false 는 "GPU 제외" 라는 값이지 "지정 안 함" 이 아니다.

    falsy 로 거르면 두 경우가 같아진다.
    """
    with _recorded_upstream(monkeypatch) as calls, _client() as client:
        client.get(
            "/api/v1/any-cloud/providers/provisioning-defaults",
            params={"gpu": "false"},
        )

    _, _, params = calls[0]
    assert params.get("gpu") is False


def test_omitted_filters_do_not_become_empty_params(monkeypatch):
    """비운 값은 아예 빼야 한다. 빈 문자열로 붙으면 백엔드가 파싱에 실패한다."""
    with _recorded_upstream(monkeypatch) as calls, _client() as client:
        client.get("/api/v1/any-cloud/providers/provisioning-defaults")

    _, _, params = calls[0]
    assert params == {}, f"빈 파라미터가 붙었다: {params}"
