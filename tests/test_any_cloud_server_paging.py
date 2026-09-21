"""게이트웨이가 백엔드 페이지를 다시 자르지 않는지 본다.

백엔드가 전량을 주고 게이트웨이가 기본 20건으로 자르는 동안, 화면은 21번째부터를 영영
보지 못했다. 자르는 곳은 한 곳이어야 한다.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.any_cloud_service import AnyCloudService


@pytest.fixture
def service():
    return AnyCloudService()


def _backend_page(items, total):
    return {"data": {"items": items}, "meta": {"pagination": {"totalEstimate": total}}}


@pytest.mark.asyncio
async def test_backend_page_is_passed_through_untouched(service):
    with patch.object(service, "_make_request", new=AsyncMock(return_value=_backend_page(["a", "b"], 57))) as call:
        result = await service.list_nodes(user_info={}, page=3, size=2)

    assert result.data == ["a", "b"]
    assert result.total == 57
    assert result.page == 3
    # 백엔드는 0-based 다. 1-based 를 그대로 넘기면 한 페이지씩 밀린다.
    assert call.await_args.kwargs["params"]["page"] == 2
    assert call.await_args.kwargs["params"]["size"] == 2


@pytest.mark.asyncio
async def test_total_falls_back_to_this_page_when_meta_is_missing(service):
    # 메타가 없으면 이 페이지 길이밖에 모른다. 없는 수를 지어내지 않는다.
    with patch.object(service, "_make_request", new=AsyncMock(return_value={"data": {"items": ["a"]}})):
        result = await service.list_nodes(user_info={}, page=1, size=20)

    assert result.total == 1


@pytest.mark.asyncio
async def test_search_still_filters_across_the_whole_list(service):
    """검색은 백엔드가 모르는 기능이라 그때는 전량을 받아 거른다."""
    rows = [{"clusterName": f"c-{i}"} for i in range(30)] + [{"clusterName": "needle"}]
    with patch.object(service, "generic_get", new=AsyncMock(return_value={"data": {"items": rows}})):
        result = await service.list_vms(user_info={}, page=1, size=20, search="needle")

    assert [row["clusterName"] for row in result.data] == ["needle"]
