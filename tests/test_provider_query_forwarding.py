"""조회 라우트가 credentialId 를 백엔드까지 넘기는지.

넘기지 않으면 백엔드는 환경변수 fallback 으로 떨어진다. 등록한 자격증명이 있어도 목록이
비어 나오고, 화면에는 "리전이 없습니다"로 보인다 — 인증 실패라는 단서가 없다.
"""

import inspect

import pytest

from app.routes import any_cloud
from app.services import any_cloud_service as service_module


FORWARDING_ROUTES = ["get_provider_regions", "get_provider_specs", "get_provider_images"]


@pytest.mark.parametrize("name", FORWARDING_ROUTES)
def test_route_accepts_the_raw_request_so_filters_survive(name):
    params = inspect.signature(getattr(any_cloud, name)).parameters
    assert "request" in params, f"{name} 이 query 를 읽지 못한다"


@pytest.mark.parametrize("name", FORWARDING_ROUTES)
def test_service_method_accepts_arbitrary_query_params(name):
    method = getattr(service_module.AnyCloudService, name)
    kinds = [p.kind for p in inspect.signature(method).parameters.values()]
    assert inspect.Parameter.VAR_KEYWORD in kinds, f"{name} 이 query 를 전달하지 못한다"


@pytest.mark.parametrize("name", FORWARDING_ROUTES)
def test_route_body_forwards_the_query(name):
    source = inspect.getsource(getattr(any_cloud, name))
    assert "request.query_params" in source
    assert "**query_params" in source


def test_config_schema_forwards_the_keys_that_unlock_account_values():
    # credentialId 와 region 이 있어야 백엔드가 allowedValues 를 채운다.
    params = inspect.signature(any_cloud.get_provider_config_schema).parameters
    assert "credentialId" in params
    assert "region" in params
