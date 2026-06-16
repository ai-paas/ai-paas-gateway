from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Body, Request, UploadFile, File, Form
from typing import Optional, Any, Dict
import logging

from app.auth import get_current_user
from app.schemas.any_cloud import AnyCloudResponse, ClusterCreateRequest, \
    HelmRepoCreateRequest, ClusterUpdateRequest, AnyCloudPagedResponse, \
    CredentialCreateRequest, ClusterValidationRequest, AddonInstallRequest, \
    HelmReleaseInstallRequest, OperationResponse, UnifiedClusterResponse
from app.services.any_cloud_service import any_cloud_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Test"])
router_cluster = APIRouter(prefix="/any-cloud/system", tags=["Any Cloud - Cluster"])
router_helm = APIRouter(prefix="/any-cloud", tags=["Any Cloud - HelmRepository"])
router_monit = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Monitoring"])
router_package = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Kubernetes"])
router_catalog = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Catalog"])
router_ops = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Operations"])
router_provider = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Providers"])
router_credential = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Credentials"])
router_addon = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Addons"])
router_admin = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Admin"])

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
@router_cluster.get("/cluster/{cluster_id}", response_model=UnifiedClusterResponse)
async def get_cluster_detail(
        cluster_id: str = Path(..., description="조회할 클러스터 이름 (RFC 1123 label)"),
        current_user: Member = Depends(get_current_user)
):
    """클러스터 상세 정보 — VM/Registered 통합 schema.

    `source` 가 vm 인지 registered 인지에 따라 일부 필드가 null:
    - VM 전용: `workerCount`, `workflowProgress`
    - Registered 전용: `agentConnectivity`, `agentHeartbeatSecondsAgo`, `agentHealthSummary`
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
        request: Request,
        cluster_data: ClusterUpdateRequest = Body(
            ...,
            openapi_examples={
                "scale-out": {
                    "summary": "워커 5개로 증가",
                    "value": {"spec": {"workerCount": 5}}
                },
                "scale-in": {
                    "summary": "워커 1개로 감소",
                    "value": {"spec": {"workerCount": 1}}
                }
            }
        ),
        cluster_id: str = Path(..., description="수정할 클러스터 이름 (RFC 1123 label)"),
        current_user: Member = Depends(get_current_user)
):
    """클러스터 수정 (현재 워커 수 변경만 지원)"""
    try:
        user_info = _create_user_info_dict(current_user)

        cluster_dict = cluster_data.model_dump(exclude_none=True)

        response = await any_cloud_service.update_cluster(
            data=cluster_dict,
            cluster_id=cluster_id,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
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
        cluster_data: ClusterCreateRequest = Body(
            ...,
            openapi_examples={
                "registered-eks": {
                    "summary": "외부 EKS 등록",
                    "value": {
                        "source": "registered",
                        "clusterName": "imported-aws-01",
                        "spec": {
                            "provider": "AWS",
                            "clusterType": "EKS",
                            "description": "Production EKS cluster in Seoul",
                            "hasGpuNodes": False
                        }
                    }
                },
                "registered-self-managed": {
                    "summary": "온프레미스 클러스터 등록",
                    "value": {
                        "source": "registered",
                        "clusterName": "on-prem-01",
                        "spec": {
                            "provider": "OPENSTACK",
                            "clusterType": "Self-managed",
                            "description": "On-premise kubeadm cluster",
                            "hasGpuNodes": True
                        }
                    }
                },
                "vm-aws": {
                    "summary": "AWS VM 신규 생성",
                    "value": {
                        "source": "vm",
                        "clusterName": "demo-aws-01",
                        "spec": {
                            "provider": "aws",
                            "region": "ap-northeast-2",
                            "environment": "dev",
                            "credentialId": "cred-aws-001",
                            "config": {
                                "workerCount": "3",
                                "instanceType": "t3.medium"
                            },
                            "hasGpuNodes": False,
                            "useSpot": False
                        }
                    }
                },
                "vm-gcp-gpu": {
                    "summary": "GCP VM 신규 생성 (GPU + spot)",
                    "value": {
                        "source": "vm",
                        "clusterName": "ml-gcp-01",
                        "spec": {
                            "provider": "gcp",
                            "region": "asia-northeast3",
                            "environment": "dev",
                            "credentialId": "cred-gcp-001",
                            "config": {
                                "workerCount": "2",
                                "machineType": "n1-standard-4",
                                "acceleratorType": "nvidia-tesla-t4",
                                "acceleratorCount": "1"
                            },
                            "hasGpuNodes": True,
                            "useSpot": True
                        }
                    }
                }
            }
        ),
        current_user: Member = Depends(get_current_user)
):
    """클러스터 생성

    source=vm 이면 신규 VM 생성, source=registered 면 외부 클러스터 등록.
    kubeconfig 파일로 등록하려면 POST /system/clusters/importKubeconfig 사용.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        cluster_dict = cluster_data.model_dump(exclude_none=True)

        response = await any_cloud_service.create_cluster(
            data=cluster_dict,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
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

    except HTTPException:
        raise
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

    except HTTPException:
        raise
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
        helm_repo_data: HelmRepoCreateRequest = Body(
            ...,
            openapi_examples={
                "prometheus-community": {
                    "summary": "Prometheus Community (public, anonymous)",
                    "value": {
                        "name": "prometheus-community",
                        "url": "https://prometheus-community.github.io/helm-charts",
                        "source": "EXTERNAL",
                        "tags": "monitoring,default"
                    }
                },
                "bitnami": {
                    "summary": "Bitnami (public)",
                    "value": {
                        "name": "bitnami",
                        "url": "https://charts.bitnami.com/bitnami",
                        "source": "EXTERNAL"
                    }
                },
                "internal-chartmuseum": {
                    "summary": "내부 ChartMuseum (인증 + 사설 인증서)",
                    "value": {
                        "name": "internal-charts",
                        "url": "https://chartmuseum.internal/charts",
                        "username": "charts-ro",
                        "password": "***",
                        "insecureSkipTLSVerify": True,
                        "source": "INTERNAL",
                        "tags": "internal"
                    }
                }
            }
        ),
        current_user: Member = Depends(get_current_user)
):
    """헬름 저장소 등록"""
    try:
        user_info = _create_user_info_dict(current_user)

        # 헬름 저장소 데이터를 딕셔너리로 변환
        helm_repo_dict = helm_repo_data.model_dump(exclude_none=True)

        # Any Cloud 서비스 호출
        response = await any_cloud_service.create_helm_repo(
            data=helm_repo_dict,
            user_info=user_info
        )

        # service.generic_post 가 이미 v1 envelope 의 data 를 unwrap 하여 반환
        return AnyCloudResponse(data=response)

    except HTTPException:
        raise
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

    except HTTPException:
        raise
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

@router_monit.get("/monit/{cluster_name}/query")
async def get_prometheus_query(
        cluster_name: str = Path(..., description="대상 클러스터 이름", examples=["on-prem-01"]),
        query: str = Query(..., description="PromQL 표현식", examples=["up", "rate(http_requests_total[5m])"]),
        time: Optional[str] = Query(None, description="평가 시각 (RFC3339 또는 unix ts, 미지정 시 현재)"),
        timeout: Optional[str] = Query(None, description="평가 timeout (예: \"30s\")"),
        limit: Optional[int] = Query(None, description="결과 행 제한", ge=1),
        current_user: Member = Depends(get_current_user)
):
    """Prometheus instant query

    클러스터에 모니터링 애드온이 설치돼 있어야 동작.
    """
    try:
        user_info = _create_user_info_dict(current_user)
        query_params: Dict[str, Any] = {"query": query}
        if time:
            query_params["time"] = time
        if timeout:
            query_params["timeout"] = timeout
        if limit is not None:
            query_params["limit"] = limit

        response = await any_cloud_service.get_prometheus_query(
            cluster_name=cluster_name,
            query_params=query_params,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting Prometheus instant query for {cluster_name} "
            f"by {current_user.member_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get Prometheus instant query"
        )


@router_monit.get("/monit/{cluster_name}/query_range")
async def get_prometheus_query_range(
        cluster_name: str = Path(..., description="대상 클러스터 이름", examples=["on-prem-01"]),
        query: str = Query(..., description="PromQL 표현식", examples=["up"]),
        start: str = Query(..., description="시작 시각 (RFC3339 또는 unix ts)", examples=["2026-06-16T00:00:00Z"]),
        end: str = Query(..., description="종료 시각 (RFC3339 또는 unix ts)", examples=["2026-06-16T01:00:00Z"]),
        step: str = Query(..., description="구간 간격 (예: \"60s\", \"5m\")", examples=["60s"]),
        timeout: Optional[str] = Query(None, description="평가 timeout"),
        limit: Optional[int] = Query(None, description="결과 행 제한", ge=1),
        current_user: Member = Depends(get_current_user)
):
    """Prometheus range query"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params: Dict[str, Any] = {
            "query": query,
            "start": start,
            "end": end,
            "step": step,
        }
        if timeout:
            query_params["timeout"] = timeout
        if limit is not None:
            query_params["limit"] = limit

        response = await any_cloud_service.get_prometheus_query_range(
            cluster_name=cluster_name,
            query_params=query_params,
            user_info=user_info
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Error getting Prometheus range query for {cluster_name} "
            f"by {current_user.member_id}: {str(e)}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get Prometheus range query"
        )

# 클러스터 연결 테스트 API — wildcard {resource_type} 보다 먼저 선언해 경로 충돌 회피
@router_package.get("/kubernetes/test-connection", response_model=AnyCloudResponse)
async def test_cluster(
        clusterName: str = Query(..., description="대상 클러스터 이름", examples=["imported-aws-01"]),
        current_user: Member = Depends(get_current_user)
):
    """클러스터 K8s API 연결 상태 확인"""
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
        logger.error(f"Error testing connectivity for {clusterName}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to test cluster connectivity"
        )

# 클러스터 특정 리소스 목록 조회 API
@router_package.get("/kubernetes/{resource_type}", response_model=AnyCloudPagedResponse)
async def get_kubernetes_resource(
        resource_type: str = Path(..., description="조회할 Resource 타입"),
        clusterName: str = Query(..., description="조회할 cluster 이름", examples=["aws-kubernetes-001"]),
        namespace: str = Query("", description="조회할 namespace 이름", examples=["default"]),
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작, search 모드에서만 사용)"),
        size: int = Query(20, ge=1, le=500, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어 (리소스 이름 등) — 명시 시 모든 페이지 fetch 후 client-side filter"),
        pageToken: Optional[str] = Query(None, description="cursor — 이전 응답의 nextPageToken"),
        labelSelector: Optional[str] = Query(None, description="K8s label selector (예: app=nginx)"),
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
            search=search,
            pageToken=pageToken,
            labelSelector=labelSelector
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
        resource_type: str = Path(..., description="조회할 Resource 타입 (예 : daemonSets. deployments, replicaSets, statefulSets, jobs, cronJobs, endpoints, namespaces, nodes, persistentVolumes, persistentVolumeClaims, pods, secrets,servies, serviceAccounts, configMaps, events, roles, roleBindings, clusterRoles, clusterRoleBindings, horizontalPodAuoscalers, ingresses, storageClasses)", examples=["nodes"]),
        resource_name: str = Path(..., description="조회할 Resource 이름", examples=["master"]),
        clusterName: str = Query(..., description="조회할 cluster 이름", examples=["aws-kubernetes-001"]),
        namespace: str = Query("", description="조회할 namespace 이름", examples=["default"]),
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
        resource_type: str = Path(..., description="조회할 Resource 타입 (예 : daemonSets. deployments, replicaSets, statefulSets, jobs, cronJobs, endpoints, namespaces, nodes, persistentVolumes, persistentVolumeClaims, pods, secrets,servies, serviceAccounts, configMaps, events, roles, roleBindings, clusterRoles, clusterRoleBindings, horizontalPodAuoscalers, ingresses, storageClasses)", examples=["nodes"]),
        resource_name: str = Path(..., description="조회할 Resource 이름", examples=["master"]),
        clusterName: str = Query(..., description="조회할 cluster 이름", examples=["aws-kubernetes-001"]),
        namespace: str = Query("", description="조회할 namespace 이름", examples=["default"]),
        current_user: Member = Depends(get_current_user)
):
    """
    쿠버네티스 특정 리소스를 삭제합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await any_cloud_service.delete_kubernetes_resource(
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

# 카탈로그 목록 조회 API
@router_catalog.get("/catalog/releases", response_model=AnyCloudPagedResponse)
async def get_helm_releases(
        clusterId: str = Query(..., description="조회할 cluster ID", examples=["aws-kubernetes-001"]),
        namespace: str = Query("", description="조회할 namespace 이름", examples=["default"]),
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
        repoName: str = Path(..., description="Helm repository 이름", examples=["chart-museum-external"]),
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
        repoName: str = Path(..., description="Helm repository 이름", examples=["chart-museum-external"]),
        chartName: str = Path(..., description="조회할 차트 이름", examples=["nginx"]),
        version: Optional[str] = Query(None, description="차트 버전 (선택사항, 없으면 최신 버전)", examples=["22.1.1"]),
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
        repoName: str = Path(..., description="Helm repository 이름", examples=["chart-museum-external"]),
        chartName: str = Path(..., description="조회할 차트 이름", examples=["nginx"]),
        version: Optional[str] = Query(None, description="차트 버전 (선택사항, 없으면 최신 버전)", examples=["15.4.4"]),
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
        repoName: str = Path(..., description="Helm repository 이름", examples=["chart-museum-external"]),
        chartName: str = Path(..., description="조회할 차트 이름", examples=["nginx"]),
        releaseName: str = Query(..., description="릴리즈 이름", examples=["nginx-test-release"]),
        clusterId: str = Query(..., description="클러스터 ID", examples=["cluster-001"]),
        namespace: str = Query("", description="네임스페이스", examples=["default"]),
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
        repoName: str = Path(..., description="Helm repository 이름", examples=["chart-museum-external"]),
        chartName: str = Path(..., description="조회할 차트 이름", examples=["nginx"]),
        version: Optional[str] = Query(None, description="차트 버전 (선택사항, 없으면 최신 버전)", examples=["15.4.4"]),
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
        clusterId: str = Query(..., description="클러스터 ID", examples=["cluster-001"]),
        namespace: str = Query(..., description="네임스페이스", examples=["default"]),
        releaseName: str = Path(..., description="릴리즈 이름", examples=["nginx-test-release"]),
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
        repoName: str = Path(
            ...,
            description="Helm repository 이름 (POST /helm-repos 에서 등록한 이름)",
            examples=["bitnami"]
        ),
        chartName: str = Path(..., description="차트 이름", examples=["nginx"]),
        releaseName: str = Form(
            ...,
            description="Helm release 이름 (K8s name, RFC 1123 label)",
            examples=["my-nginx"]
        ),
        clusterId: str = Form(
            ...,
            description="배포 대상 cluster 이름",
            examples=["imported-aws-01"]
        ),
        namespace: str = Form(
            default="default",
            description="배포 namespace (선택, default \"default\")",
            examples=["web"]
        ),
        version: Optional[str] = Form(
            default=None,
            description="차트 버전 (미지정 시 latest)",
            examples=["15.3.0"]
        ),
        valuesFile: Optional[UploadFile] = File(
            default=None,
            description="values.yaml 파일 — Helm CLI 의 -f 인자로 전달. JSON values 사용이 더 깔끔."
        ),
        current_user: Member = Depends(get_current_user)
):
    """차트 배포 (values.yaml 파일 업로드 가능)"""
    try:
        user_info = _create_user_info_dict(current_user)

        values_content = None
        if valuesFile:
            values_content = await valuesFile.read()
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


# ============================================================================
# v1 추가 엔드포인트 — operations / validations / providers / credentials /
# kubeconfig import / addons / audit-logs
# ============================================================================

# 작업 이력 검색
@router_ops.get("/operations")
async def list_operations(
        state: Optional[str] = Query(None, description="필터 — 상태 (RUNNING, SUCCEEDED, FAILED 등)"),
        type: Optional[str] = Query(None, description="필터 — 작업 종류"),
        resourceType: Optional[str] = Query(None, description="필터 — 리소스 타입"),
        resourceId: Optional[str] = Query(None, description="필터 — 리소스 ID"),
        pageSize: int = Query(50, ge=1, le=500, description="페이지 크기"),
        current_user: Member = Depends(get_current_user)
):
    """작업 이력 목록 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        query = {"pageSize": pageSize}
        if state:
            query["state"] = state
        if type:
            query["type"] = type
        if resourceType:
            query["resourceType"] = resourceType
        if resourceId:
            query["resourceId"] = resourceId
        return await any_cloud_service.get_operations(user_info=user_info, **query)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing operations for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list operations"
        )


# 작업 단건 조회
@router_ops.get("/operations/{operation_id}", response_model=OperationResponse)
async def get_operation(
        operation_id: str = Path(..., description="작업 ID (예: op-xxxxxxxx)"),
        current_user: Member = Depends(get_current_user)
):
    """작업 단건 조회

    state: PENDING / RUNNING / SUCCEEDED / FAILED / CANCELLED
    """
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_operation(
            operation_id=operation_id,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting operation {operation_id} for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve operation"
        )


# 작업 취소
@router_ops.post("/operations/{operation_id}/cancel", response_model=OperationResponse)
async def cancel_operation(
        operation_id: str = Path(..., description="작업 ID"),
        current_user: Member = Depends(get_current_user)
):
    """진행 중 작업 취소 요청"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.cancel_operation(
            operation_id=operation_id,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling operation {operation_id} for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel operation"
        )


# VM 클러스터 생성 사전 검증
@router_cluster.post("/cluster-validations")
async def validate_cluster(
        body: ClusterValidationRequest = Body(
            ...,
            openapi_examples={
                "aws-preflight": {
                    "summary": "AWS VM 클러스터 검증",
                    "value": {
                        "clusterProvider": "AWS",
                        "clusterName": "demo-aws-01",
                        "description": "AWS development cluster",
                        "environment": "dev",
                        "region": "ap-northeast-2",
                        "credentialId": "cred-aws-001",
                        "config": {
                            "workerCount": "3",
                            "instanceType": "t3.medium"
                        },
                        "hasGpuNodes": False
                    }
                },
                "openstack-preflight": {
                    "summary": "OpenStack VM 클러스터 검증",
                    "value": {
                        "clusterProvider": "OPENSTACK",
                        "clusterName": "demo-os-01",
                        "environment": "dev",
                        "region": "RegionOne",
                        "credentialId": "cred-os-001",
                        "config": {
                            "workerCount": "2",
                            "flavorName": "m1.medium",
                            "imageName": "ubuntu-22.04"
                        }
                    }
                }
            }
        ),
        current_user: Member = Depends(get_current_user)
):
    """VM 클러스터 생성 사전 검증 (정적 검증만, 실제 자원 생성 X)

    실제 Pulumi 호출이 필요하면 /cluster-validations/preview 사용.
    """
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.validate_cluster(
            data=body.model_dump(exclude_none=True),
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating cluster for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to validate cluster"
        )


# 클러스터 생성 미리보기
@router_cluster.post("/cluster-validations/preview")
async def preview_cluster(
        body: ClusterValidationRequest = Body(
            ...,
            openapi_examples={
                "aws-preview": {
                    "summary": "AWS VM 클러스터 미리보기",
                    "value": {
                        "clusterProvider": "AWS",
                        "clusterName": "demo-aws-01",
                        "environment": "dev",
                        "region": "ap-northeast-2",
                        "credentialId": "cred-aws-001",
                        "config": {
                            "workerCount": "3",
                            "instanceType": "t3.medium"
                        }
                    }
                }
            }
        ),
        current_user: Member = Depends(get_current_user)
):
    """VM 클러스터 생성 미리보기 — 실제 생성될 자원 계획만 반환 (실제 생성 X)

    수십 초 소요 가능 — client timeout 60s 이상 권장.
    """
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.preview_cluster(
            data=body.model_dump(exclude_none=True),
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error previewing cluster for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to preview cluster"
        )


# Kubeconfig 업로드로 외부 클러스터 등록 (multipart)
@router_cluster.post("/clusters/importKubeconfig")
async def import_kubeconfig(
        kubeconfigFile: UploadFile = File(
            ...,
            description="kubeconfig YAML 파일 (current-context 사용)"
        ),
        clusterName: str = Form(
            ...,
            description="등록할 클러스터 이름 (RFC 1123 label)",
            examples=["imported-aws-01"]
        ),
        provider: str = Form(
            ...,
            description='CSP — "AWS" | "GCP" | "AZURE" | "OPENSTACK" 등',
            examples=["AWS"]
        ),
        clusterType: Optional[str] = Form(
            None,
            description='클러스터 타입 — "EKS" | "GKE" | "AKS" | "Self-managed" 등 (기본값 "Imported")',
            examples=["EKS"]
        ),
        description: Optional[str] = Form(None, description="설명"),
        validate: bool = Form(
            True,
            description="등록 직후 연결성 검증 수행 (기본 true)"
        ),
        strict: bool = Form(
            False,
            description="true 면 검증 실패 시 등록 롤백, false 면 결과만 기록"
        ),
        current_user: Member = Depends(get_current_user)
):
    """kubeconfig 파일 업로드로 외부 클러스터 등록

    수동 입력 흐름은 POST /system/cluster (source=registered) 사용.
    """
    try:
        user_info = _create_user_info_dict(current_user)
        content = await kubeconfigFile.read()
        return await any_cloud_service.import_kubeconfig(
            file_content=content,
            file_name=kubeconfigFile.filename or "kubeconfig",
            cluster_name=clusterName,
            provider=provider,
            user_info=user_info,
            cluster_type=clusterType,
            description=description,
            validate=validate,
            strict=strict
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error importing kubeconfig for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to import kubeconfig: {str(e)}"
        )


# 지원 CSP 목록
@router_provider.get("/providers")
async def list_providers(current_user: Member = Depends(get_current_user)):
    """지원 CSP 목록 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.list_providers(user_info=user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing providers for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list providers"
        )


@router_provider.get("/providers/{provider}/regions")
async def get_provider_regions(
        provider: str = Path(..., description="CSP 식별자 (aws/gcp/azure/...)"),
        current_user: Member = Depends(get_current_user)
):
    """CSP 별 region 목록 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_provider_regions(provider=provider, user_info=user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting regions for {provider}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get regions"
        )


@router_provider.get("/providers/{provider}/specs")
async def get_provider_specs(
        request: Request,
        provider: str = Path(..., description="CSP 식별자"),
        current_user: Member = Depends(get_current_user)
):
    """CSP 별 VM spec 목록 — region 등 query 필터 그대로 forward."""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.get_provider_specs(
            provider=provider,
            user_info=user_info,
            **query_params
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting specs for {provider}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get specs"
        )


@router_provider.get("/providers/{provider}/config-schema")
async def get_provider_config_schema(
        provider: str = Path(..., description="CSP 식별자"),
        current_user: Member = Depends(get_current_user)
):
    """CSP 별 클러스터 설정 스키마 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_provider_config_schema(provider=provider, user_info=user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting config-schema for {provider}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get config schema"
        )


@router_provider.get("/providers/{provider}/images")
async def get_provider_images(
        request: Request,
        provider: str = Path(..., description="CSP 식별자"),
        current_user: Member = Depends(get_current_user)
):
    """CSP 별 OS 이미지 목록 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.get_provider_images(
            provider=provider,
            user_info=user_info,
            **query_params
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting images for {provider}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get images"
        )


# CSP 자격증명 CRUD
@router_credential.get("/credentials")
async def list_credentials(
        request: Request,
        current_user: Member = Depends(get_current_user)
):
    """CSP 자격증명 목록 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.list_credentials(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing credentials for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list credentials"
        )


@router_credential.get("/credentials/{credential_id}")
async def get_credential(
        credential_id: str = Path(..., description="자격증명 ID"),
        current_user: Member = Depends(get_current_user)
):
    """CSP 자격증명 단건 조회 (secret 은 마스킹 처리됨)"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_credential(credential_id=credential_id, user_info=user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting credential {credential_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get credential"
        )


@router_credential.post("/credentials")
async def create_credential(
        body: CredentialCreateRequest = Body(
            ...,
            openapi_examples={
                "aws-manual": {
                    "summary": "AWS MANUAL — access key 직접 저장",
                    "value": {
                        "provider": "AWS",
                        "name": "aws-dev",
                        "description": "AWS dev account",
                        "sourceType": "MANUAL",
                        "credentials": {
                            "AWS_ACCESS_KEY_ID": "AKIAIOSFODNN7EXAMPLE",
                            "AWS_SECRET_ACCESS_KEY": "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
                        }
                    }
                },
                "gcp-manual": {
                    "summary": "GCP MANUAL — service account JSON",
                    "value": {
                        "provider": "GCP",
                        "name": "gcp-dev",
                        "sourceType": "MANUAL",
                        "credentials": {
                            "GOOGLE_APPLICATION_CREDENTIALS_JSON": "{\"type\":\"service_account\",...}"
                        }
                    }
                },
                "openstack-manual": {
                    "summary": "OpenStack MANUAL — application credential",
                    "value": {
                        "provider": "OPENSTACK",
                        "name": "os-dev",
                        "sourceType": "MANUAL",
                        "credentials": {
                            "OS_AUTH_URL": "https://keystone.local:5000/v3",
                            "OS_APPLICATION_CREDENTIAL_ID": "abc...",
                            "OS_APPLICATION_CREDENTIAL_SECRET": "***"
                        }
                    }
                },
                "aws-env": {
                    "summary": "AWS ENV — 환경변수 사용",
                    "value": {
                        "provider": "AWS",
                        "name": "aws-from-env",
                        "sourceType": "ENV"
                    }
                }
            }
        ),
        current_user: Member = Depends(get_current_user)
):
    """CSP 자격증명 등록

    MANUAL: credentials 에 키/값 직접 입력 (백엔드에서 암호화 저장)
    ENV: 백엔드 환경변수 사용 (credentials 생략)

    생성된 credentialId 는 클러스터 생성/검증 시 spec.credentialId 로 사용.
    """
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.create_credential(
            data=body.model_dump(exclude_none=True),
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating credential for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create credential: {str(e)}"
        )


@router_credential.delete("/credentials/{credential_id}")
async def delete_credential(
        credential_id: str = Path(..., description="자격증명 ID"),
        current_user: Member = Depends(get_current_user)
):
    """CSP 자격증명 삭제"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.delete_credential(credential_id=credential_id, user_info=user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting credential {credential_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete credential"
        )


# 애드온 카탈로그
@router_addon.get("/addons")
async def list_addon_catalog(current_user: Member = Depends(get_current_user)):
    """설치 가능한 애드온 카탈로그 목록"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.list_addon_catalog(user_info=user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing addon catalog for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list addon catalog"
        )


# 클러스터별 애드온
@router_addon.get("/clusters/{cluster_name}/addons")
async def list_cluster_addons(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_user)
):
    """클러스터에 설치된 애드온 목록 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.list_cluster_addons(cluster_name=cluster_name, user_info=user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing cluster addons for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list cluster addons"
        )


@router_addon.get("/clusters/{cluster_name}/addons/{addon_id}")
async def get_cluster_addon(
        cluster_name: str = Path(..., description="클러스터 이름"),
        addon_id: str = Path(..., description="애드온 ID"),
        current_user: Member = Depends(get_current_user)
):
    """애드온 단건 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_cluster_addon(
            cluster_name=cluster_name,
            addon_id=addon_id,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting addon {addon_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get addon"
        )


@router_addon.post("/clusters/{cluster_name}/addons")
async def install_cluster_addon(
        cluster_name: str = Path(..., description="클러스터 이름"),
        body: AddonInstallRequest = Body(
            ...,
            openapi_examples={
                "monitoring-catalog": {
                    "summary": "Monitoring (카탈로그)",
                    "value": {
                        "type": "MONITORING",
                        "catalogId": "kube-prometheus-stack",
                        "namespace": "monitoring"
                    }
                },
                "ingress-nginx-catalog": {
                    "summary": "Ingress-NGINX (카탈로그)",
                    "value": {
                        "type": "INGRESS_NGINX",
                        "catalogId": "ingress-nginx",
                        "namespace": "ingress-nginx"
                    }
                },
                "cert-manager-catalog": {
                    "summary": "Cert-manager (카탈로그)",
                    "value": {
                        "type": "CERT_MANAGER",
                        "catalogId": "cert-manager",
                        "namespace": "cert-manager"
                    }
                },
                "monitoring-custom": {
                    "summary": "Monitoring (직접 지정)",
                    "value": {
                        "type": "MONITORING",
                        "releaseName": "kube-prometheus-stack",
                        "namespace": "monitoring",
                        "chartRepo": "prometheus-community",
                        "chartName": "kube-prometheus-stack",
                        "chartVersion": "65.0.0",
                        "repoUrl": "https://prometheus-community.github.io/helm-charts",
                        "valuesYaml": "grafana:\n  enabled: true\nprometheus:\n  prometheusSpec:\n    retention: 30d\n"
                    }
                },
                "soft-disabled": {
                    "summary": "비활성 상태로 등록",
                    "value": {
                        "type": "VELERO",
                        "catalogId": "velero",
                        "enabled": False
                    }
                }
            }
        ),
        current_user: Member = Depends(get_current_user)
):
    """애드온 설치 요청"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.install_cluster_addon(
            cluster_name=cluster_name,
            data=body.model_dump(exclude_none=True),
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error installing addon for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to install addon: {str(e)}"
        )


@router_addon.delete("/clusters/{cluster_name}/addons/{addon_id}")
async def uninstall_cluster_addon(
        cluster_name: str = Path(..., description="클러스터 이름"),
        addon_id: str = Path(..., description="애드온 ID"),
        current_user: Member = Depends(get_current_user)
):
    """애드온 제거 요청"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.uninstall_cluster_addon(
            cluster_name=cluster_name,
            addon_id=addon_id,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uninstalling addon {addon_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to uninstall addon"
        )


@router_addon.post("/clusters/{cluster_name}/addons/{addon_id}/retry")
async def retry_cluster_addon(
        cluster_name: str = Path(..., description="클러스터 이름"),
        addon_id: str = Path(..., description="애드온 ID"),
        current_user: Member = Depends(get_current_user)
):
    """실패한 애드온 재시도"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.retry_cluster_addon(
            cluster_name=cluster_name,
            addon_id=addon_id,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying addon {addon_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retry addon"
        )


# Helm 릴리즈 설치 (JSON body)
@router_catalog.post("/clusters/{cluster_name}/helm-releases")
async def install_helm_release(
        cluster_name: str = Path(..., description="대상 클러스터 이름"),
        body: HelmReleaseInstallRequest = Body(
            ...,
            openapi_examples={
                "nginx-minimal": {
                    "summary": "Bitnami nginx — 최소 설정",
                    "value": {
                        "releaseName": "ingress",
                        "chart": "bitnami/nginx",
                        "namespace": "web"
                    }
                },
                "nginx-with-values": {
                    "summary": "Bitnami nginx — JSON values",
                    "value": {
                        "releaseName": "ingress",
                        "chart": "bitnami/nginx",
                        "version": "15.3.0",
                        "namespace": "web",
                        "values": {
                            "replicaCount": 3,
                            "image": {"repository": "nginx", "tag": "1.27"},
                            "service": {"type": "LoadBalancer"}
                        }
                    }
                },
                "prometheus-values-yaml": {
                    "summary": "Prometheus — values.yaml 문자열",
                    "value": {
                        "releaseName": "kube-prometheus",
                        "chart": "prometheus-community/kube-prometheus-stack",
                        "version": "65.0.0",
                        "namespace": "monitoring",
                        "valuesYaml": "grafana:\n  enabled: true\nprometheus:\n  prometheusSpec:\n    retention: 30d\n"
                    }
                }
            }
        ),
        current_user: Member = Depends(get_current_user)
):
    """Helm 릴리즈 설치 (JSON body)

    파일 업로드가 필요하면 POST /catalog/{repo}/{chart}/deploy 사용.
    """
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.install_helm_release(
            cluster_name=cluster_name,
            data=body.model_dump(exclude_none=True),
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error installing helm release for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to install helm release: {str(e)}"
        )


# 감사 로그
@router_admin.get("/audit-logs")
async def list_audit_logs(
        request: Request,
        current_user: Member = Depends(get_current_user)
):
    """감사 로그 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.get_audit_logs(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing audit logs for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list audit logs"
        )
