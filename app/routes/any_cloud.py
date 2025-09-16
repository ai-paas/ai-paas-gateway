from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Body, Request
from typing import Optional, Any, Dict
import logging

from app.auth import get_current_user
from app.schemas.any_cloud import AnyCloudResponse, GenericRequest
from app.services.any_cloud_service import any_cloud_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/any-cloud", tags=["Any Cloud"])


def _create_user_info_dict(user: Member) -> Dict[str, str]:
    """Member 객체에서 user_info 딕셔너리 생성"""
    return {
        'member_id': user.member_id,
        'role': user.role,
        'name': user.name
    }


# 클러스터 목록 조회
@router.get("/system/clusters", response_model=AnyCloudResponse)
async def any_cloud_get_api(
        # path: str = Path(..., description="Any Cloud API 경로"),
        request: Request = None,
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터 전체 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        # 쿼리 파라미터를 dict로 변환
        query_params = dict(request.query_params) if request else {}

        response = await any_cloud_service.generic_get(
            path=f"/system/clusters",
            user_info=user_info,
            **query_params
        )

        return AnyCloudResponse(data=response["data"])

    except Exception as e:
        logger.error(f"Error calling Any Cloud GET API for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to call Any Cloud API: {str(e)}"
        )


# 범용 POST API
@router.post("/api/{path:path}", response_model=AnyCloudResponse)
async def any_cloud_post_api(
        path: str = Path(..., description="Any Cloud API 경로"),
        request_data: GenericRequest = Body(...),
        request: Request = None,
        current_user: Member = Depends(get_current_user)
):
    """
    Any Cloud 범용 POST API 호출

    예시:
    - POST /any-cloud/api/resources
    - POST /any-cloud/api/instances/123/start
    - POST /any-cloud/api/services/deploy
    """
    try:
        user_info = _create_user_info_dict(current_user)

        # 쿼리 파라미터도 함께 전달
        query_params = dict(request.query_params) if request else {}

        response = await any_cloud_service.generic_post(
            path=f"/{path}",
            data=request_data.data,
            user_info=user_info,
            **query_params
        )

        return AnyCloudResponse(data=response["data"])

    except Exception as e:
        logger.error(f"Error calling Any Cloud POST API {path} for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to call Any Cloud POST API: {str(e)}"
        )


# 범용 PUT API
@router.put("/api/{path:path}", response_model=AnyCloudResponse)
async def any_cloud_put_api(
        path: str = Path(..., description="Any Cloud API 경로"),
        request_data: GenericRequest = Body(...),
        request: Request = None,
        current_user: Member = Depends(get_current_user)
):
    """
    Any Cloud 범용 PUT API 호출
    """
    try:
        user_info = _create_user_info_dict(current_user)

        query_params = dict(request.query_params) if request else {}

        response = await any_cloud_service.generic_put(
            path=f"/{path}",
            data=request_data.data,
            user_info=user_info,
            **query_params
        )

        return AnyCloudResponse(data=response["data"])

    except Exception as e:
        logger.error(f"Error calling Any Cloud PUT API {path} for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to call Any Cloud PUT API: {str(e)}"
        )


# 범용 DELETE API
@router.delete("/api/{path:path}", response_model=AnyCloudResponse)
async def any_cloud_delete_api(
        path: str = Path(..., description="Any Cloud API 경로"),
        request: Request = None,
        current_user: Member = Depends(get_current_user)
):
    """
    Any Cloud 범용 DELETE API 호출
    """
    try:
        user_info = _create_user_info_dict(current_user)

        query_params = dict(request.query_params) if request else {}

        response = await any_cloud_service.generic_delete(
            path=f"/{path}",
            user_info=user_info,
            **query_params
        )

        return AnyCloudResponse(data=response["data"])

    except Exception as e:
        logger.error(f"Error calling Any Cloud DELETE API {path} for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to call Any Cloud DELETE API: {str(e)}"
        )