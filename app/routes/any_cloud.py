from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Body, Request, UploadFile, File, Form
from typing import Optional, Any, Dict
import logging
import json

from app.auth import get_current_user
from app.schemas.any_cloud import AnyCloudResponse, AnyCloudDataResponse, GenericRequest, ClusterCreateRequest, \
    ClusterDeleteResponse, HelmRepoCreateRequest, FilterModel, ClusterUpdateRequest, AnyCloudPagedResponse
from app.services.any_cloud_service import any_cloud_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Test"])
router_cluster = APIRouter(prefix="/any-cloud/system", tags=["Any Cloud - Cluster"])
router_helm = APIRouter(prefix="/any-cloud", tags=["Any Cloud - HelmRepository"])
router_monit = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Monitoring"])
router_package = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Packages"])
router_catalog = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Catalog"])

def _create_user_info_dict(user: Member) -> Dict[str, str]:
    """Member 객체에서 user_info 딕셔너리 생성"""
    return {
        'member_id': user.member_id,
        'role': user.role,
        'name': user.name
    }

# 클러스터 목록 조회 API
@router_cluster.get("/clusters", response_model=AnyCloudPagedResponse)
async def get_clusters(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어 (클러스터 이름, ID 등)"),
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터 전체 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_clusters(
            user_info=user_info,
            page=page,
            size=size,
            search=search
        )

        return response

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
        cluster_id: str = Query(..., alias="cluster_id", description="조회할 클러스터 ID"),
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


# 클러스터 연결 테스트
@router_cluster.get("/cluster/{cluster_id}/test-connection")
async def get_cluster_test_connection(
        cluster_id: str = Path(..., description="조회할 클러스터 ID"),
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터 연결 상태를 테스트합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_cluster_test_connection(
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

# 클러스터 수정
@router_cluster.put("/cluster/{cluster_id}")
async def update_any_cloud_cluster(
        request: Request,  # 추가
        cluster_data: ClusterUpdateRequest,
        cluster_id: str = Path(..., description="수정할 클러스터 ID"),
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터를 업데이트합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        # 클러스터 데이터를 딕셔너리로 변환
        cluster_dict = cluster_data.dict()

        # Any Cloud 서비스 호출
        response = await any_cloud_service.update_cluster(
            data=cluster_dict,
            cluster_id=cluster_id,
            user_info=user_info
        )

        return response

    except ValueError as ve:
        logger.error(f"Validation error updating cluster for {current_user.member_id}: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cluster data: {str(ve)}"
        )

    except Exception as e:
        logger.error(f"Error updating cluster for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update cluster: {str(e)}"
        )

# 클러스터 생성
@router_cluster.post("/cluster")
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

        return response

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


# 클러스터 상태 강제 업데이트
@router_cluster.post("/cluster/{cluster_id}/refresh")
async def cluster_refresh(
        cluster_id: str = Path(..., description="조회할 클러스터 ID"),
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터 상태를 강제로 업데이트합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.cluster_refresh(
            cluster_id=cluster_id,
            user_info=user_info
        )

        return response

    except ValueError as ve:
        logger.error(f"Validation error refresh cluster for {current_user.member_id}: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid cluster data: {str(ve)}"
        )

    except Exception as e:
        logger.error(f"Error refresh cluster for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to refresh cluster: {str(e)}"
        )

# 클러스터 삭제
@router_cluster.delete("/cluster/{cluster_id}")
async def cluster_delete_api(
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
@router_helm.get("/helm-repos", response_model=AnyCloudPagedResponse)
async def get_helms(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어 (저장소 이름, URL 등)"),
        current_user: Member = Depends(get_current_user)
):
    """
    헬름 저장소 전체 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_helm_repos(
            user_info=user_info,
            page=page,
            size=size,
            search=search
        )

        return response

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

# 헬름 저장소 생성
@router_helm.post("/helm-repos", response_model=AnyCloudResponse)
async def create_helm_repo(
        helm_repo_data: HelmRepoCreateRequest,
        current_user: Member = Depends(get_current_user)
):
    """
    헬름 저장소를 생성합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        # 헬름 저장소 데이터를 딕셔너리로 변환
        helm_repo_dict = helm_repo_data.dict()

        # Any Cloud 서비스 호출
        response = await any_cloud_service.create_helm_repo(
            data=helm_repo_dict,
            user_info=user_info
        )

        return AnyCloudResponse(data=response["data"])

    except ValueError as ve:
        logger.error(f"Validation error creating helm repo for {current_user.member_id}: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid helm repo data: {str(ve)}"
        )

    except Exception as e:
        logger.error(f"Error creating helm repo for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create helm repo: {str(e)}"
        )

# 헬름 저장소 삭제
@router_helm.delete("/helm-repos/{helm_repo_name}", response_model=AnyCloudResponse)
async def helm_repo_delete_api(
        helm_repo_name: str = Path(..., description="헬름 저장소 이름"),
        current_user: Member = Depends(get_current_user)
):
    """
    헬름 저장소를 삭제합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        # Any Cloud 서비스 호출
        response = await any_cloud_service.delete_helm_repo(
            helm_repo_name=helm_repo_name,
            user_info=user_info
        )

        return response

    except ValueError as ve:
        logger.error(f"Validation error deleting helm repo {helm_repo_name} for {current_user.member_id}: {str(ve)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid helm repo Name: {str(ve)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error deleting helm repo {helm_repo_name} for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred while deleting helm repo"
        )

# 클러스터 내 노드별 상태 조회 API
@router_monit.get("/monit/nodeStatus/{cluster_name}")
async def get_monitoring_cluster_node(
        cluster_name: str = Path(..., description="조회할 cluster 이름", example="openstack"),
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터 내 노드별 상태 조회
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_monitoring_node(
            cluster_name=cluster_name,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting monitoring {cluster_name} detail for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to monitoring"
        )

# 대시보드 모니터링 메트릭 조회 API
@router_monit.get(
    "/monit/resourceMonit/{cluster_name}/{type}/{key}",
    openapi_extra={
        "parameters": [
            {
                "name": "filter",
                "in": "query",
                "required": True,
                "description": "node,namespace filter 및 duration",
                "schema": {
                    "type": "object",
                    "example": {"namespace": "kubeflow", "duration": "3600"},
                    "properties": {
                        "namespace": {"type": "string"},
                        "duration": {"type": "string"}
                    }
                },
                "style": "form",
                "explode": True
            }
        ]
    }
)
async def get_monitoring_metric(
        request: Request,
        cluster_name: str = Path(..., description="조회할 cluster 이름", example="openstack"),
        type: str = Path(..., description="메트릭 타입", example="cpu"),
        key: str = Path(..., description="조회할 메트릭 key", example="usage_namespace"),
        current_user: Member = Depends(get_current_user)
):
    """
    대시보드 모니터링 메트릭 조회 https://github.com/ai-paas/any-cloud-management/blob/main/anycloud/src/main/resources/application.yaml 참고
    """
    try:
        user_info = _create_user_info_dict(current_user)

        # 쿼리 파라미터를 filter dict로 변환
        filter_dict = dict(request.query_params)

        response = await any_cloud_service.get_monitoring_metric(
            cluster_name=cluster_name,
            type=type,
            key=key,
            filter=filter_dict,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting monitoring {cluster_name} detail for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get monitoring metric"
        )

# 클러스터 특정 리소스 목록 조회 API
@router_package.get("/kubernetes/{resource_type}", response_model=AnyCloudPagedResponse)
async def get_kubernetes_resource(
        resource_type: str = Path(..., description="조회할 Resource 타입"),
        clusterName: str = Query(..., description="조회할 cluster 이름", example="aws-kubernetes-001"),
        namespace: str = Query("", description="조회할 namespace 이름", example="default"),
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어 (리소스 이름 등)"),
        current_user: Member = Depends(get_current_user)
):
    """
    쿠버네티스 특정 리소스 전체를 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_kubernetes_resource(
            resource_type=resource_type,
            clusterName=clusterName,
            namespace=namespace,
            user_info=user_info,
            page=page,
            size=size,
            search=search
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting kubernetes cluster resource for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve kubernetes cluster resource"
        )

# 클러스터 특정 리소스 목록 조회 API
@router_package.get("/kubernetes/{resource_type}/{resource_name}", response_model=AnyCloudResponse)
async def get_kubernetes_resource_name(
        resource_type: str = Path(..., description="조회할 Resource 타입 (예 : daemonSets. deployments, replicaSets, statefulSets, jobs, cronJobs, endpoints, namespaces, nodes, persistentVolumes, persistentVolumeClaims, pods, secrets,servies, serviceAccounts, configMaps, events, roles, roleBindings, clusterRoles, clusterRoleBindings, horizontalPodAuoscalers, ingresses, storageClasses)", example="nodes"),
        resource_name: str = Path(..., description="조회할 Resource 이름", example="master"),
        clusterName: str = Query(..., description="조회할 cluster 이름", example="aws-kubernetes-001"),
        namespace: str = Query("", description="조회할 namespace 이름", example="default"),
        current_user: Member = Depends(get_current_user)
):
    """
    쿠버네티스 특정 리소스 전체를 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_kubernetes_resource_name(
            resource_type=resource_type,
            resource_name=resource_name,
            clusterName=clusterName,
            namespace=namespace,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting kubernetes cluster resource for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve kubernetes cluster resource"
        )

# 클러스터 특정 리소스 삭제 API
@router_package.delete("/kubernetes/{resource_type}/{resource_name}", response_model=AnyCloudResponse)
async def delete_kubernetes_resource_name(
        resource_type: str = Path(..., description="조회할 Resource 타입 (예 : daemonSets. deployments, replicaSets, statefulSets, jobs, cronJobs, endpoints, namespaces, nodes, persistentVolumes, persistentVolumeClaims, pods, secrets,servies, serviceAccounts, configMaps, events, roles, roleBindings, clusterRoles, clusterRoleBindings, horizontalPodAuoscalers, ingresses, storageClasses)", example="nodes"),
        resource_name: str = Path(..., description="조회할 Resource 이름", example="master"),
        clusterName: str = Query(..., description="조회할 cluster 이름", example="aws-kubernetes-001"),
        namespace: str = Query("", description="조회할 namespace 이름", example="default"),
        current_user: Member = Depends(get_current_user)
):
    """
    쿠버네티스 특정 리소스를 삭제합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_kubernetes_resource_name(
            resource_type=resource_type,
            resource_name=resource_name,
            clusterName=clusterName,
            namespace=namespace,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting deleting cluster resource for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error occurred while deleting kubernetes cluster resource"
        )

# 클러스터 연결 테스트 API
@router_package.get("/kubernetes/test-connection", response_model=AnyCloudResponse)
async def test_cluster(
        clusterName: str = Query(..., description="조회할 cluster 이름", example="openstack"),
        current_user: Member = Depends(get_current_user)
):
    """
    클러스터 연결 상태를 테스트합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_kubernetes_test(
            clusterName=clusterName,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting kubernetes cluster for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve kubernetes cluster"
        )

# 카탈로그 목록 조회 API
@router_catalog.get("/catalog/releases", response_model=AnyCloudPagedResponse)
async def get_helm_releases(
        clusterId: str = Query(..., description="조회할 cluster ID", example="aws-kubernetes-001"),
        namespace: str = Query("", description="조회할 namespace 이름", example="default"),
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어 (릴리즈 이름 등)"),
        current_user: Member = Depends(get_current_user)
):
    """
    Helm CLI를 사용하여 클러스터의 모든 릴리즈 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_catalog_releases(
            clusterId=clusterId,
            namespace=namespace,
            user_info=user_info,
            page=page,
            size=size,
            search=search
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting clusters releases for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve clusters releases"
        )

# 카탈로그 목록 조회 API
@router_catalog.get("/catalog/{repoName}", response_model=AnyCloudPagedResponse)
async def get_catalog_list(
        repoName: str = Path(..., description="Helm repository 이름", example="chart-museum-external"),
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어 (차트 이름 등)"),
        current_user: Member = Depends(get_current_user)
):
    """
    DB에서 repoName으로 RepositoryEntity 조회 후 해당 url에서 index.yaml을 다운로드하여 차트 목록을 반환합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_catalog_list(
            repoName=repoName,
            user_info=user_info,
            page=page,
            size=size,
            search=search
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting catalogs for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve catalogs"
        )

# 차트 상세 조회 API
@router_catalog.get("/catalog/{repoName}/{chartName}/detail")
async def get_catalog_detail(
        repoName: str = Path(..., description="Helm repository 이름", example="chart-museum-external"),
        chartName: str = Path(..., description="조회할 차트 이름", example="nginx"),
        version: str = Query("", description="차트 버전 (선택사항, 없으면 최신 버전)", example="22.1.1"),
        current_user: Member = Depends(get_current_user)
):
    """
    DB에서 repoName 또는 이름으로 RepositoryEntity 조회 후 해당 url에서 index.yaml을 다운로드하여 특정 차트 상세 정보를 반환합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_catalog_chart(
            repoName=repoName,
            chartName=chartName,
            version=version,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting chart for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve chart"
        )

# 차트 README.md 조회 API
@router_catalog.get("/catalog/{repoName}/{chartName}/readme")
async def get_catalog_readme(
        repoName: str = Path(..., description="Helm repository 이름", example="chart-museum-external"),
        chartName: str = Path(..., description="조회할 차트 이름", example="nginx"),
        version: str = Query("", description="차트 버전 (선택사항)", example="15.4.4"),
        current_user: Member = Depends(get_current_user)
):
    """
    Helm CLI를 사용하여 지정된 차트의 README.md 내용을 실시간으로 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_catalog_readme(
            repoName=repoName,
            chartName=chartName,
            version=version,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting README.md for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve README.md"
        )

# 차트 배포 상태 조회 API
@router_catalog.get("/catalog/{repoName}/{chartName}/status")
async def get_catalog_status(
        repoName: str = Path(..., description="Helm repository 이름", example="chart-museum-external"),
        chartName: str = Path(..., description="조회할 차트 이름", example="nginx"),
        releaseName: str = Query(..., description="릴리즈 이름", example="nginx-test-release"),
        clusterId: str = Query(..., description="클러스터 ID", example="cluster-001"),
        namespace: str = Query("", description="네임스페이스", example="default"),
        current_user: Member = Depends(get_current_user)
):
    """
    Helm CLI를 사용하여 특정 릴리즈의 배포 상태를 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_catalog_status(
            repoName=repoName,
            chartName=chartName,
            releaseName=releaseName,
            clusterId=clusterId,
            namespace=namespace,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting status for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve status"
        )

# 차트 values.yaml 조회 API
@router_catalog.get("/catalog/{repoName}/{chartName}/values")
async def get_catalog_values(
        repoName: str = Path(..., description="Helm repository 이름", example="chart-museum-external"),
        chartName: str = Path(..., description="조회할 차트 이름", example="nginx"),
        version: str = Query("", description="차트 버전 (선택사항)", example="15.4.4"),
        current_user: Member = Depends(get_current_user)
):
    """
    Helm CLI를 사용하여 지정된 차트의 values.yaml 내용을 실시간으로 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_catalog_values(
            repoName=repoName,
            chartName=chartName,
            version=version,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting values for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve values"
        )

# 차트 resources.yaml 조회 API
@router_catalog.get("/catalog/releases/{releaseName}/resources")
async def get_catalog_resources(
        clusterId: str = Query(..., description="클러스터 ID", example="cluster-001"),
        namespace: str = Query(..., description="네임스페이스", example="default"),
        releaseName: str = Path(..., description="릴리즈 이름", example="nginx-test-release"),
        current_user: Member = Depends(get_current_user)
):
    """
    Helm CLI를 사용하여 특정 릴리즈의 리소스 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.get_catalog_resources(
            clusterId=clusterId,
            namespace=namespace,
            releaseName=releaseName,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting resources for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve resource"
        )


@router_catalog.post("/catalog/{repoName}/{chartName}/deploy")
async def post_catalog_deploy(
        repoName: str = Path(..., description="Helm repository 이름", example="my-repo"),
        chartName: str = Path(..., description="차트 이름", example="nginx"),
        releaseName: str = Form(..., description="Helm 릴리즈 이름", example="my-nginx"),
        clusterId: str = Form(..., description="배포할 클러스터 ID", example="cluster-001"),
        namespace: str = Form(default="default", description="배포할 네임스페이스", example="default"),
        version: Optional[str] = Form(default=None, description="차트 버전 (미지정시 최신 버전)", example="15.4.4"),
        valuesFile: Optional[UploadFile] = File(default=None, description="파일 선택"),
        current_user: Member = Depends(get_current_user)
):
    """
    ProcessBuilder를 사용하여 Helm CLI(helm install/upgrade)를 호출하여 차트를 배포합니다. values.yaml 파일 업로드가 가능합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        # valuesFile 처리
        values_content = None
        if valuesFile:
            values_content = await valuesFile.read()
            # 파일 타입 검증
            if not valuesFile.filename.endswith(('.yaml', '.yml')):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Values file must be a YAML file"
                )

        response = await any_cloud_service.create_catalog_deploy(
            repoName=repoName,
            chartName=chartName,
            releaseName=releaseName,
            clusterId=clusterId,
            namespace=namespace,
            version=version,
            valuesFile=values_content,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deploying chart for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to deploy chart"
        )
