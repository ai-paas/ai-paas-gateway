from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Body, Request
from typing import Optional, Any, Dict
import logging

from app.auth import get_current_user
from app.schemas.any_cloud import AnyCloudResponse, AnyCloudDataResponse, GenericRequest, ClusterCreateRequest, ClusterDeleteResponse
from app.services.any_cloud_service import any_cloud_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Test 용"])
router_cluster = APIRouter(prefix="/any-cloud/system", tags=["Any Cloud - Cluster"])
router_helm = APIRouter(prefix="/any-cloud", tags=["Any Cloud - HelmRepository"])

def _create_user_info_dict(user: Member) -> Dict[str, str]:
    """Member 객체에서 user_info 딕셔너리 생성"""
    return {
        'member_id': user.member_id,
        'role': user.role,
        'name': user.name
    }

# 클러스터 목록 조회 API
@router_cluster.get("/clusters", response_model=AnyCloudDataResponse)
async def get_clusters(
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터 전체 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_clusters(
            user_info=user_info
        )

        # 목록 조회는 data로 래핑하여 반환
        return AnyCloudDataResponse(data=response["data"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting clusters for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve clusters"
        )

# 클러스터 존재 여부 확인 API
@router_cluster.get("/cluster/exists")
async def check_cluster_exists(
        cluster_id: str = Query(..., alias="_clusterId", description="조회할 클러스터 ID"),
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터 존재 여부를 확인합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.check_cluster_exists(
            cluster_id=cluster_id,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error checking cluster {cluster_id} existence for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check cluster existence"
        )

# 클러스터 상세 조회 API
@router_cluster.get("/cluster/{cluster_id}")
async def get_cluster_detail(
        cluster_id: str = Path(..., description="조회할 클러스터 ID"),
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터 상세 정보를 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_cluster_detail(
            cluster_id=cluster_id,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting cluster {cluster_id} detail for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve cluster details"
        )

# 클러스터 생성
@router_cluster.post("/cluster", response_model=AnyCloudResponse)
async def create_any_cloud_cluster(
        cluster_data: ClusterCreateRequest,
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터를 생성합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        # 클러스터 데이터를 딕셔너리로 변환
        cluster_dict = cluster_data.dict()

        # Any Cloud 서비스 호출
        response = await any_cloud_service.create_cluster(
            data=cluster_dict,
            user_info=user_info
        )

        return AnyCloudResponse(data=response["data"])

    except ValueError as ve:
        logger.error(f"Validation error creating cluster for {current_user.member_id}: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cluster data: {str(ve)}"
        )

    except Exception as e:
        logger.error(f"Error creating cluster for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create cluster: {str(e)}"
        )

# 클러스터 삭제
@router_cluster.delete("/cluster/{cluster_id}", response_model=AnyCloudResponse)
async def any_cloud_delete_api(
        cluster_id: str = Path(..., description="cluster_id"),
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터를 삭제합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        # Any Cloud 서비스 호출
        response = await any_cloud_service.delete_cluster(
            cluster_id=cluster_id,
            user_info=user_info
        )

        return response

    except ValueError as ve:
        logger.error(f"Validation error deleting cluster {cluster_id} for {current_user.member_id}: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cluster ID: {str(ve)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error deleting cluster {cluster_id} for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred while deleting cluster"
        )

# 헬름 저장소 목록 조회 API
@router_helm.get("/helm-repos", response_model=AnyCloudDataResponse)
async def get_helms(
        current_user: Member = Depends(get_current_user)
):
    """
    헬름 저장소 전체 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_helm_repos(
            user_info=user_info
        )

        # 목록 조회는 data로 래핑하여 반환
        return AnyCloudDataResponse(data=response["data"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting helm-repos for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve helm-repos"
        )

# 헬름 저장소 존재 여부 확인 API
@router_helm.get("/helm-repos/{helm_repo_name}/exists")
async def get_helms_exists(
        helm_repo_name: str = Path(..., description="조회할 헬름 저장소 이름"),
        current_user: Member = Depends(get_current_user)
):
    """
    헬름 저장소 존재 여부를 확인합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.check_helm_repos_exists(
            helm_repo_name=helm_repo_name,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting helm-repos for {helm_repo_name} existence for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check helm-repos existence"
        )

# 헬름 저장소 상세 조회 API
@router_helm.get("/helm-repos/{helm_repo_name}")
async def get_helm_repo_detail(
        helm_repo_name: str = Path(..., description="조회할 헬름 저장소 이름"),
        current_user: Member = Depends(get_current_user)
):
    """
    헬름 저장소 상세 정보를 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_helm_repos_detail(
            helm_repo_name=helm_repo_name,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting helm-repo {helm_repo_name} detail for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve helm-repo details"
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