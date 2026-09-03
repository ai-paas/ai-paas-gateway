import asyncio
import logging
from typing import Any, Dict, Optional
from urllib.parse import quote, urlencode

import websockets as ws_lib
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Path, Query, \
    Request, UploadFile, WebSocket, WebSocketDisconnect, status

from app.auth import get_current_admin_user, get_current_user, get_ws_admin_user, \
    ws_bearer_subprotocol
from app.config import settings
from app.models import Member
from app.schemas.any_cloud import AnyCloudResponse, ClusterCreateRequest, \
    HelmRepoCreateRequest, ClusterUpdateRequest, AnyCloudPagedResponse, \
    CredentialCreateRequest, ClusterValidationRequest, AddonInstallRequest, \
    HelmReleaseInstallRequest, OperationResponse, PrometheusMultiQueryRequest, \
    UnifiedClusterResponse
from app.services.any_cloud_service import any_cloud_service

logger = logging.getLogger(__name__)


def require_any_cloud_enabled() -> None:
    """ANY_CLOUD_ENABLED=false 면 503. 플래그를 껐는데 upstream 연결 실패(502)로
    보이던 문제를 없앤다. Swagger 계약은 그대로 유지된다."""
    if not settings.ANY_CLOUD_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Any Cloud provider is disabled (ANY_CLOUD_ENABLED=false)",
        )


_enabled = [Depends(require_any_cloud_enabled)]

router = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Test"], dependencies=_enabled)
router_cluster = APIRouter(prefix="/any-cloud/system", tags=["Any Cloud - Cluster"], dependencies=_enabled)
router_helm = APIRouter(prefix="/any-cloud", tags=["Any Cloud - HelmRepository"], dependencies=_enabled)
router_monit = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Monitoring"], dependencies=_enabled)
router_package = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Kubernetes"], dependencies=_enabled)
router_catalog = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Catalog"], dependencies=_enabled)
router_ops = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Operations"], dependencies=_enabled)
router_provider = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Providers"], dependencies=_enabled)
router_credential = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Credentials"], dependencies=_enabled)
router_addon = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Addons"], dependencies=_enabled)
router_admin = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Admin"], dependencies=_enabled)
router_obs = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Observability"], dependencies=_enabled)
router_workflow = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Workflow"], dependencies=_enabled)
router_admin_cluster = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Admin Cluster"], dependencies=_enabled)
router_admin_agent = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Admin Agent"], dependencies=_enabled)
router_fleet = APIRouter(prefix="/any-cloud", tags=["Any Cloud - Fleet Upgrade"], dependencies=_enabled)
router_vm = APIRouter(prefix="/any-cloud/vms", tags=["Any Cloud - VM"], dependencies=_enabled)


def _backend_ws_base() -> str:
    """ANY_CLOUD_TARGET_WS_URL override 가 있으면 사용, 아니면 HTTP base 의 scheme 만 ws/wss 로 치환."""
    override = (settings.ANY_CLOUD_TARGET_WS_URL or "").strip()
    if override:
        return override.rstrip("/")
    base = (settings.ANY_CLOUD_TARGET_BASE_URL or "").rstrip("/")
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):]
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):]
    return base


async def _ws_forward_client_to_backend(client: WebSocket, backend) -> None:
    while True:
        msg = await client.receive()
        if msg.get("type") == "websocket.disconnect":
            return
        if msg.get("bytes") is not None:
            await backend.send(msg["bytes"])
        elif msg.get("text") is not None:
            await backend.send(msg["text"])


async def _ws_forward_backend_to_client(client: WebSocket, backend) -> None:
    async for msg in backend:
        if isinstance(msg, bytes):
            await client.send_bytes(msg)
        else:
            await client.send_text(msg)


@router_package.websocket("/kubernetes/clusters/{cluster_name}/pods/{namespace}/{pod_name}/exec")
async def pod_exec_proxy(
        websocket: WebSocket,
        cluster_name: str,
        namespace: str,
        pod_name: str,
        container: str = Query("", description="컨테이너 이름 (비우면 첫 컨테이너)"),
        command: str = Query("/bin/sh", description="실행 명령"),
        tty: bool = Query(True, description="TTY 할당 여부"),
        stdin: bool = Query(True, description="stdin 연결 여부"),
        current_user: Member = Depends(get_ws_admin_user),
):
    """Pod exec WebSocket proxy (admin 전용).

    파드 셸을 그대로 여는 통로라 REST 변경계와 동일하게 admin 으로 제한한다.
    토큰 전달: `Authorization: Bearer <token>` 헤더, 또는 브라우저에서는
    `new WebSocket(url, ["bearer", "<access_token>"])` 서브프로토콜.
    """
    await websocket.accept(subprotocol=ws_bearer_subprotocol(websocket))
    logger.info(f"pod_exec_proxy opened by {current_user.member_id}: {cluster_name}/{namespace}/{pod_name}")
    qs = urlencode({
        **({"container": container} if container else {}),
        **({"command": command} if command else {}),
        "tty": "true" if tty else "false",
        "stdin": "true" if stdin else "false",
    })
    backend_path = "/".join(
        quote(seg, safe="") for seg in ("v1", "clusters", cluster_name, "pods", namespace, pod_name, "exec")
    )
    backend_url = f"{_backend_ws_base()}/{backend_path}?{qs}"

    try:
        async with ws_lib.connect(backend_url) as backend_ws:
            tasks = [
                asyncio.create_task(_ws_forward_client_to_backend(websocket, backend_ws)),
                asyncio.create_task(_ws_forward_backend_to_client(websocket, backend_ws)),
            ]
            _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except (WebSocketDisconnect, ws_lib.ConnectionClosed):
        pass
    except Exception as e:
        logger.warning(f"pod_exec_proxy: {e}")
    await websocket.close()

def _attachment(filename: str) -> str:
    """Content-Disposition 헤더 값. 파일명은 사용자 입력에서 오므로 quote 한다."""
    return f"attachment; filename=\"{quote(filename)}\""


def _create_user_info_dict(user: Member) -> Dict[str, str]:
    """Member 객체에서 user_info 딕셔너리 생성"""
    return {
        'member_id': user.member_id,
        'role': user.role,
        'name': user.name
    }


# 허용 kind = (upstream v0.3.0 ClusterKubernetesController 지원 목록)
#            ∩ (develop 이 의도적으로 차단한 secrets/RBAC 제외)
#
# 값은 반드시 소문자다. upstream 검증이 K8S_KIND_PATTERN `^[a-z][a-z0-9]{0,49}$` 이므로
# camelCase 를 넣으면 게이트웨이는 통과시키고 upstream 이 400 을 낸다(lockstep 위반).
# secrets / roles / roleBindings / clusterRoles / clusterRoleBindings 는 정책상 차단 —
# tests/test_security_p0.py 가 고정하고 있다.
_ALLOWED_KUBERNETES_RESOURCE_TYPES = {
    # namespaced
    "pods",
    "services",
    "deployments",
    "statefulsets",
    "daemonsets",
    "replicasets",
    "configmaps",
    "persistentvolumeclaims",
    "jobs",
    "cronjobs",
    # cluster-scoped ({namespace} 자리에 "-" 사용)
    "nodes",
    "namespaces",
    "persistentvolumes",
    "storageclasses",
}


def _validate_kubernetes_resource_type(resource_type: str) -> str:
    if resource_type not in _ALLOWED_KUBERNETES_RESOURCE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Kubernetes resource type is not allowed",
        )
    return resource_type

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
        current_user: Member = Depends(get_current_admin_user)
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
            detail="Failed to update cluster"
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
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 등록 (외부 K8s cluster 만).

    VM 인프라 신규 생성은 별도 namespace 사용 — POST /any-cloud/vms.
    응답 BootstrapInfo 의 helm/kubectl install 명령을 사용자가 자신의 kubectl context 에서 실행.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        cluster_dict = cluster_data.model_dump(exclude_none=True)

        # VM 생성은 /vms namespace 로 이동했다 — gateway 단에서 빠르게 명시 에러.
        if cluster_dict.get("source") == "vm":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="VM provisioning moved to POST /any-cloud/vms — use that endpoint instead."
            )

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
            detail="Failed to create cluster"
        )


# 클러스터 상태 강제 업데이트
@router_cluster.post("/cluster/{cluster_id}/refresh")
async def cluster_refresh(
        cluster_id: str = Path(..., description="조회할 클러스터 ID"),
        current_user: Member = Depends(get_current_admin_user)
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
            detail="Failed to refresh cluster"
        )

# 클러스터 삭제
@router_cluster.delete("/cluster/{cluster_id}")
async def cluster_delete_api(
        cluster_id: str = Path(..., description="cluster_id"),
        current_user: Member = Depends(get_current_admin_user)
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
        current_user: Member = Depends(get_current_admin_user)
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
            detail="Failed to create helm repo"
        )

# 헬름 저장소 삭제
@router_helm.delete("/helm-repos/{helm_repo_name}", response_model=AnyCloudResponse)
async def helm_repo_delete_api(
        helm_repo_name: str = Path(..., description="헬름 저장소 이름"),
        current_user: Member = Depends(get_current_admin_user)
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


@router_monit.post("/monit/{cluster_name}/multi-query", response_model=AnyCloudResponse)
async def post_prometheus_multi_query(
        cluster_name: str = Path(..., description="대상 클러스터 이름", examples=["on-prem-01"]),
        body: PrometheusMultiQueryRequest = Body(...),
        current_user: Member = Depends(get_current_user)
):
    """Prometheus N PromQL 병렬 fan-out — 모니터링 페이지의 다중 요청을 1 요청으로 묶기 위한 batch."""
    try:
        user_info = _create_user_info_dict(current_user)
        queries = [q.model_dump(exclude_none=True) for q in body.queries]
        return await any_cloud_service.multi_query_prometheus(
            cluster_name=cluster_name,
            queries=queries,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error multi-query for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to multi-query Prometheus"
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
        resource_type = _validate_kubernetes_resource_type(resource_type)
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
        resource_type = _validate_kubernetes_resource_type(resource_type)
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

# 클러스터 특정 리소스의 K8s Event 목록
@router_package.get("/kubernetes/{resource_type}/{resource_name}/events", response_model=AnyCloudResponse)
async def list_kubernetes_resource_events(
        resource_type: str = Path(..., description="Resource 타입 (예: pods, deployments)", examples=["pods"]),
        resource_name: str = Path(..., description="Resource 이름", examples=["my-pod-abc123"]),
        clusterName: str = Query(..., description="조회할 cluster 이름", examples=["aws-kubernetes-001"]),
        namespace: str = Query("", description="namespace (cluster-scoped 면 무시)", examples=["default"]),
        current_user: Member = Depends(get_current_user)
):
    """
    지정 리소스에 연관된 K8s Event 목록 (involvedObject.kind/name 으로 fieldSelector 필터링).
    core/v1 Event 만 지원.
    """
    try:
        resource_type = _validate_kubernetes_resource_type(resource_type)
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_kubernetes_resource_events(
            resource_type=resource_type,
            resource_name=resource_name,
            clusterName=clusterName,
            namespace=namespace,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing kubernetes resource events for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list kubernetes resource events"
        )


# 클러스터 특정 리소스 재시작
@router_package.post("/kubernetes/{resource_type}/{resource_name}/restart", response_model=AnyCloudResponse)
async def restart_kubernetes_resource(
        resource_type: str = Path(..., description="Resource 타입 (pods/deployments/statefulsets/daemonsets)", examples=["deployments"]),
        resource_name: str = Path(..., description="Resource 이름", examples=["my-deployment"]),
        clusterName: str = Query(..., description="조회할 cluster 이름", examples=["aws-kubernetes-001"]),
        namespace: str = Query("", description="namespace", examples=["default"]),
        current_user: Member = Depends(get_current_admin_user)
):
    """
    리소스 재시작.

    - pods: 단순 delete (컨트롤러가 재생성).
    - deployments/statefulsets/daemonsets: spec.template.metadata.annotations 의
      kubectl.kubernetes.io/restartedAt 갱신으로 rollout restart.
    - 그 외 kind 는 400.
    """
    try:
        resource_type = _validate_kubernetes_resource_type(resource_type)
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.restart_kubernetes_resource(
            resource_type=resource_type,
            resource_name=resource_name,
            clusterName=clusterName,
            namespace=namespace,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error restarting kubernetes resource for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to restart kubernetes resource"
        )


# 클러스터 특정 리소스 스케일
@router_package.post("/kubernetes/{resource_type}/{resource_name}/scale", response_model=AnyCloudResponse)
async def scale_kubernetes_resource(
        resource_type: str = Path(..., description="Resource 타입 (deployments/replicasets/statefulsets)", examples=["deployments"]),
        resource_name: str = Path(..., description="Resource 이름", examples=["my-deployment"]),
        clusterName: str = Query(..., description="조회할 cluster 이름", examples=["aws-kubernetes-001"]),
        namespace: str = Query("", description="namespace", examples=["default"]),
        replicas: int = Query(..., ge=0, le=1000, description="목표 replicas (0..1000)", examples=[3]),
        current_user: Member = Depends(get_current_admin_user)
):
    """
    replicas 변경. deployments/replicasets/statefulsets 만 지원. 그 외 kind 는 400.
    """
    try:
        resource_type = _validate_kubernetes_resource_type(resource_type)
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.scale_kubernetes_resource(
            resource_type=resource_type,
            resource_name=resource_name,
            clusterName=clusterName,
            namespace=namespace,
            replicas=replicas,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scaling kubernetes resource for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to scale kubernetes resource"
        )


# 클러스터 특정 리소스 삭제 API
@router_package.delete("/kubernetes/{resource_type}/{resource_name}", response_model=AnyCloudResponse)
async def delete_kubernetes_resource_name(
        resource_type: str = Path(..., description="조회할 Resource 타입 (예 : daemonSets. deployments, replicaSets, statefulSets, jobs, cronJobs, endpoints, namespaces, nodes, persistentVolumes, persistentVolumeClaims, pods, secrets,servies, serviceAccounts, configMaps, events, roles, roleBindings, clusterRoles, clusterRoleBindings, horizontalPodAuoscalers, ingresses, storageClasses)", examples=["nodes"]),
        resource_name: str = Path(..., description="조회할 Resource 이름", examples=["master"]),
        clusterName: str = Query(..., description="조회할 cluster 이름", examples=["aws-kubernetes-001"]),
        namespace: str = Query("", description="조회할 namespace 이름", examples=["default"]),
        current_user: Member = Depends(get_current_admin_user)
):
    """
    쿠버네티스 특정 리소스를 삭제합니다.
    """
    try:
        resource_type = _validate_kubernetes_resource_type(resource_type)
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
        current_user: Member = Depends(get_current_admin_user)
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
        size: int = Query(50, ge=1, le=500, description="페이지 크기"),
        current_user: Member = Depends(get_current_user)
):
    """작업 이력 목록 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        query = {"pageSize": size}   # gateway size -> upstream pageSize
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
        current_user: Member = Depends(get_current_admin_user)
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
        current_user: Member = Depends(get_current_admin_user)
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
        current_user: Member = Depends(get_current_admin_user)
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
        current_user: Member = Depends(get_current_admin_user)
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
        current_user: Member = Depends(get_current_admin_user)
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
                "aws": {
                    "summary": "AWS access key",
                    "value": {
                        "provider": "AWS",
                        "name": "aws-dev",
                        "description": "AWS dev account",
                        "credentials": {
                            "AWS_ACCESS_KEY_ID": "AKIA...",
                            "AWS_SECRET_ACCESS_KEY": "..."
                        }
                    }
                },
                "gcp": {
                    "summary": "GCP service account",
                    "value": {
                        "provider": "GCP",
                        "name": "gcp-dev",
                        "credentials": {
                            "GOOGLE_CREDENTIALS": "{\"type\":\"service_account\",...}"
                        }
                    }
                },
                "openstack": {
                    "summary": "OpenStack application credential",
                    "value": {
                        "provider": "OPENSTACK",
                        "name": "os-dev",
                        "credentials": {
                            "OS_AUTH_URL": "https://keystone.local:5000/v3",
                            "OS_APPLICATION_CREDENTIAL_ID": "...",
                            "OS_APPLICATION_CREDENTIAL_SECRET": "***"
                        }
                    }
                }
            }
        ),
        current_user: Member = Depends(get_current_admin_user)
):
    """CSP 자격증명 등록 — credentials 에 키/값 직접 입력 (백엔드에서 암호화 저장).

    생성된 credentialId 는 VM 생성/검증 시 사용.
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
            detail="Failed to create credential"
        )


@router_credential.delete("/credentials/{credential_id}")
async def delete_credential(
        credential_id: str = Path(..., description="자격증명 ID"),
        current_user: Member = Depends(get_current_admin_user)
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
        current_user: Member = Depends(get_current_admin_user)
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
            detail="Failed to install addon"
        )


@router_addon.delete("/clusters/{cluster_name}/addons/{addon_id}")
async def uninstall_cluster_addon(
        cluster_name: str = Path(..., description="클러스터 이름"),
        addon_id: str = Path(..., description="애드온 ID"),
        current_user: Member = Depends(get_current_admin_user)
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
        current_user: Member = Depends(get_current_admin_user)
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
        current_user: Member = Depends(get_current_admin_user)
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
            detail="Failed to install helm release"
        )


# 감사 로그
@router_admin.get("/audit-logs")
async def list_audit_logs(
        request: Request,
        current_user: Member = Depends(get_current_admin_user)
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


# ============================================================================
# P1 추가 — kubeconfig / agent-manifest 다운로드, health, state-history, cluster operations,
#          ssh-key, resource-kinds
# ============================================================================

from fastapi.responses import PlainTextResponse


# kubeconfig 다운로드 (YAML)
@router_cluster.get(
    "/cluster/{cluster_name}/kubeconfig",
    response_class=PlainTextResponse,
)
async def download_cluster_kubeconfig(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 kubeconfig 다운로드 (YAML)"""
    try:
        user_info = _create_user_info_dict(current_user)
        content = await any_cloud_service.get_cluster_kubeconfig(
            cluster_name=cluster_name,
            user_info=user_info
        )
        return PlainTextResponse(
            content,
            media_type="application/yaml",
            headers={"Content-Disposition": _attachment(f"{cluster_name}-kubeconfig.yaml")}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading kubeconfig for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download kubeconfig"
        )


# agent-bootstrap (JSON) — helm/kubectl install command + token + 만료시각.
# Cluster 상세에서 modal 로 재발급 시 사용. 매 호출 새 token.
@router_cluster.get("/cluster/{cluster_name}/agent-bootstrap")
async def get_cluster_agent_bootstrap(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_admin_user),
):
    """Cluster-agent bootstrap 정보 (helmInstallCommand / kubectlApplyCommand / token / expiresAt)"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.generic_get_unwrapped(
            path=f"/v1/clusters/{quote(cluster_name, safe='')}/agent-bootstrap",
            user_info=user_info,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching agent bootstrap for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch agent bootstrap"
        )


# agent-manifest 다운로드 (YAML) — registered cluster 의 agent install
@router_cluster.get(
    "/cluster/{cluster_name}/agent-manifest",
    response_class=PlainTextResponse,
)
async def download_cluster_agent_manifest(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 agent install manifest 다운로드 (YAML)"""
    try:
        user_info = _create_user_info_dict(current_user)
        content = await any_cloud_service.get_cluster_agent_manifest(
            cluster_name=cluster_name,
            user_info=user_info
        )
        return PlainTextResponse(
            content,
            media_type="application/yaml",
            headers={"Content-Disposition": _attachment(f"{cluster_name}-agent-manifest.yaml")}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading agent manifest for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to download agent manifest"
        )


# 클러스터 종합 health
@router_cluster.get("/cluster/{cluster_name}/health")
async def get_cluster_health(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_user)
):
    """클러스터 종합 health 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_cluster_health(
            cluster_name=cluster_name,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting health for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get cluster health"
        )


# fleet-wide 에이전트 health 요약
@router_cluster.get("/agents/health")
async def get_agents_health(
        request: Request,
        current_user: Member = Depends(get_current_admin_user)
):
    """모든 클러스터의 에이전트 health 요약"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.get_agents_health(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agents health: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get agents health"
        )


# 클러스터별 작업 이력
@router_cluster.get("/cluster/{cluster_name}/operations")
async def get_cluster_operations(
        cluster_name: str = Path(..., description="클러스터 이름"),
        request: Request = None,
        current_user: Member = Depends(get_current_user)
):
    """특정 클러스터의 작업 이력 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params) if request else {}
        return await any_cloud_service.get_cluster_operations(
            cluster_name=cluster_name,
            user_info=user_info,
            **query_params
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting operations for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get cluster operations"
        )


# 클러스터 state history
@router_cluster.get("/cluster/{cluster_name}/state-history")
async def get_cluster_state_history(
        cluster_name: str = Path(..., description="클러스터 이름"),
        request: Request = None,
        current_user: Member = Depends(get_current_user)
):
    """VM 클러스터 workflow state 변경 이력"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params) if request else {}
        return await any_cloud_service.get_cluster_state_history(
            cluster_name=cluster_name,
            user_info=user_info,
            **query_params
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting state history for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get cluster state history"
        )


# SSH 키 발급
@router_cluster.post("/cluster/{cluster_name}/ssh-key")
async def post_cluster_ssh_key(
        cluster_name: str = Path(..., description="클러스터 이름"),
        body: Optional[Dict[str, Any]] = Body(default=None),
        current_user: Member = Depends(get_current_admin_user)
):
    """VM 클러스터 SSH 키 발급/조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.post_cluster_ssh_key(
            cluster_name=cluster_name,
            user_info=user_info,
            data=body or {}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error issuing ssh-key for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to issue ssh key"
        )


# 클러스터 지원 kind 목록
@router_cluster.get("/cluster/{cluster_name}/resource-kinds")
async def get_cluster_resource_kinds(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_user)
):
    """클러스터가 지원하는 K8s kind 목록 (CRD 포함)"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_cluster_resource_kinds(
            cluster_name=cluster_name,
            user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting resource-kinds for {cluster_name}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get resource kinds"
        )


# ============================================================================
# P2 추가 — observability (alerts / silences / rules / dashboard) + standard metrics
# ============================================================================

@router_obs.get("/clusters/{cluster_name}/observability/targets")
async def get_observability_targets(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_user)
):
    """Prometheus scrape target 상태"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_observability_targets(cluster_name, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting targets for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get observability targets")


@router_obs.get("/clusters/{cluster_name}/observability/alerts")
async def get_observability_alerts(
        request: Request,
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_user)
):
    """발생 중 alert 목록"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.get_observability_alerts(
            cluster_name=cluster_name, user_info=user_info, **query_params
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting alerts for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get alerts")


@router_obs.get("/clusters/{cluster_name}/observability/alert-silences")
async def list_alert_silences(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_user)
):
    """alert silence 목록"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_observability_alert_silences(cluster_name, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing silences for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list alert silences")


@router_obs.post("/clusters/{cluster_name}/observability/alert-silences")
async def create_alert_silence(
        cluster_name: str = Path(..., description="클러스터 이름"),
        body: Dict[str, Any] = Body(...),
        current_user: Member = Depends(get_current_admin_user)
):
    """alert silence 생성"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.create_observability_alert_silence(
            cluster_name=cluster_name, data=body, user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating silence for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create alert silence")


@router_obs.delete("/clusters/{cluster_name}/observability/alert-silences/{silence_id}")
async def delete_alert_silence(
        cluster_name: str = Path(..., description="클러스터 이름"),
        silence_id: str = Path(..., description="silence id"),
        current_user: Member = Depends(get_current_admin_user)
):
    """alert silence 제거"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.delete_observability_alert_silence(
            cluster_name=cluster_name, silence_id=silence_id, user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting silence {silence_id}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete alert silence")


@router_obs.get("/observability/alert-rules")
async def list_alert_rules(current_user: Member = Depends(get_current_user)):
    """alert rule 카탈로그 (전역)"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.list_alert_rules(user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing alert rules: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list alert rules")


@router_obs.post("/clusters/{cluster_name}/observability/alert-rules/install-all")
async def install_all_alert_rules(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_admin_user)
):
    """alert rule 전체 설치"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.install_all_alert_rules(cluster_name, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error installing all rules: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to install all alert rules")


@router_obs.post("/clusters/{cluster_name}/observability/alert-rules/{rule_set_id}")
async def install_alert_rule(
        cluster_name: str = Path(..., description="클러스터 이름"),
        rule_set_id: str = Path(..., description="rule set id"),
        current_user: Member = Depends(get_current_admin_user)
):
    """alert rule set 설치"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.install_alert_rule(
            cluster_name=cluster_name, rule_set_id=rule_set_id, user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error installing rule {rule_set_id}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to install alert rule")


@router_obs.delete("/clusters/{cluster_name}/observability/alert-rules/{rule_set_id}")
async def delete_alert_rule(
        cluster_name: str = Path(..., description="클러스터 이름"),
        rule_set_id: str = Path(..., description="rule set id"),
        current_user: Member = Depends(get_current_admin_user)
):
    """alert rule set 제거"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.delete_alert_rule(
            cluster_name=cluster_name, rule_set_id=rule_set_id, user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting rule {rule_set_id}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete alert rule")


@router_obs.get("/clusters/{cluster_name}/observability/dashboard")
async def get_observability_dashboard(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_user)
):
    """클러스터 대시보드 메타"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_observability_dashboard(cluster_name, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dashboard for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get dashboard")


@router_obs.get("/observability/standard-queries")
async def list_standard_queries(current_user: Member = Depends(get_current_user)):
    """표준 query 카탈로그 (전역)"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.list_standard_queries(user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing standard queries: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list standard queries")


@router_obs.get("/observability/aggregate")
async def get_observability_aggregate(
        request: Request,
        current_user: Member = Depends(get_current_user)
):
    """다 클러스터 통합 지표"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.get_observability_aggregate(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting aggregate: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get aggregate")


# 표준 metric — node-cpu / node-memory / namespace-cpu / namespace-memory / pod-phases / top-cpu
@router_monit.get("/monit/{cluster_name}/standard/{metric}")
async def get_standard_metric(
        request: Request,
        cluster_name: str = Path(..., description="클러스터 이름"),
        metric: str = Path(..., description="표준 metric 종류"),
        current_user: Member = Depends(get_current_user)
):
    """Prometheus 표준 metric — 사전 정의된 query 묶음"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.get_standard_metric(
            cluster_name=cluster_name, metric=metric, user_info=user_info, **query_params
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting standard metric {metric} for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get standard metric")


# v0.2 프론트 호환용 alias. upstream 의 /monit/nodeStatus 는 v0.3.0 에서 사라졌으므로
# 동등한 K8s nodes 목록으로 위임한다. **응답 형태가 v0.2 와 다르다** — 프론트는
# GET /any-cloud/kubernetes/nodes?clusterName=... 로 이관할 것.
@router_monit.get("/monit/nodeStatus/{cluster_name}", deprecated=True)
async def get_monitoring_cluster_node(
        cluster_name: str = Path(..., description="조회할 cluster 이름", examples=["openstack"]),
        page: int = Query(1, ge=1, description="페이지 번호"),
        size: int = Query(20, ge=1, le=500, description="페이지 크기"),
        current_user: Member = Depends(get_current_user)
):
    """[deprecated] 클러스터 노드 상태 조회.

    Any Cloud v0.3.0 대체 경로: `GET /any-cloud/kubernetes/nodes?clusterName={cluster_name}`
    """
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_kubernetes_resource(
            resource_type="nodes",
            clusterName=cluster_name,
            namespace="",
            user_info=user_info,
            page=page,
            size=size,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting node status for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get node status")


# ============================================================================
# P3 추가 — workflow / admin (cluster cleanup / drift / agent) / fleet upgrade / pod logs
# ============================================================================

@router_workflow.get("/workflow/queues")
async def list_workflow_queues(
        request: Request,
        current_user: Member = Depends(get_current_admin_user)
):
    """워크플로우 큐 상태"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.list_workflow_queues(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing workflow queues: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list workflow queues")


@router_workflow.get("/workflow/dead-letter-messages")
async def list_dead_letter_messages(
        request: Request,
        current_user: Member = Depends(get_current_admin_user)
):
    """DLQ 메시지 목록"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.list_dead_letter_messages(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing DLQ messages: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list DLQ messages")


@router_workflow.post("/workflow/dead-letter-messages/{message_id}/operations")
async def operate_dead_letter_message(
        message_id: str = Path(..., description="DLQ 메시지 id"),
        body: Dict[str, Any] = Body(...),
        current_user: Member = Depends(get_current_admin_user)
):
    """DLQ 메시지 처리 (재시도 / 폐기)"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.operate_dead_letter_message(
            message_id=message_id, data=body, user_info=user_info
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error operating DLQ {message_id}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to operate DLQ message")


@router_admin_cluster.delete("/admin/clusters/{cluster_name}/force")
async def admin_force_delete_cluster(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 강제 삭제 (admin)"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.admin_force_delete_cluster(cluster_name, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error force-deleting {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to force delete cluster")


@router_admin_cluster.delete("/admin/clusters/{stack_name}/orphan-state")
async def admin_delete_orphan_state(
        stack_name: str = Path(..., description="Pulumi stack 이름"),
        current_user: Member = Depends(get_current_admin_user)
):
    """오펀 Pulumi state 삭제 (admin)"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.admin_delete_orphan_state(stack_name, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting orphan state {stack_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete orphan state")


@router_admin_cluster.get("/admin/clusters/{cluster_name}/drift")
async def admin_get_cluster_drift(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 drift 조회"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.admin_get_cluster_drift(cluster_name, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting drift for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get drift")


@router_admin_cluster.post("/admin/clusters/{cluster_name}/refresh-state")
async def admin_refresh_cluster_state(
        cluster_name: str = Path(..., description="클러스터 이름"),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 state 강제 갱신"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.admin_refresh_cluster_state(cluster_name, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error refreshing state for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to refresh state")


@router_fleet.get("/fleet/upgrade/preview")
async def fleet_upgrade_preview(
        request: Request,
        current_user: Member = Depends(get_current_admin_user)
):
    """fleet upgrade 미리보기"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.fleet_upgrade_preview(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fleet upgrade preview: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get fleet upgrade preview")


@router_fleet.get("/fleet/upgrade/runs")
async def fleet_upgrade_runs(
        request: Request,
        current_user: Member = Depends(get_current_admin_user)
):
    """fleet upgrade 실행 이력"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.fleet_upgrade_runs(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting fleet upgrade runs: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get fleet upgrade runs")


@router_fleet.put("/clusters/{cluster_name}/upgrade-wave")
async def patch_cluster_upgrade_wave(
        cluster_name: str = Path(..., description="클러스터 이름"),
        body: Dict[str, Any] = Body(...),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 upgrade wave 변경"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.patch_cluster_upgrade_wave(cluster_name, body, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error patching upgrade-wave for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to patch upgrade wave")


@router_fleet.post("/clusters/{cluster_name}/upgrade")
async def trigger_cluster_upgrade(
        cluster_name: str = Path(..., description="클러스터 이름"),
        body: Dict[str, Any] = Body(...),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 upgrade 실행"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.trigger_cluster_upgrade(cluster_name, body, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error triggering upgrade for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to trigger upgrade")


@router_admin_agent.get("/admin/agents", response_model=AnyCloudPagedResponse)
async def list_admin_agents(
        status: Optional[str] = Query(None, description="콤마 multi (REGISTERING/REGISTERED/ACTIVE/DEGRADED/FAILED/REVOKED)"),
        clusterName: Optional[str] = Query(None, description="콤마 multi"),
        versionPrefix: Optional[str] = Query(None),
        lastSeenOlderThanSec: Optional[int] = Query(None, ge=0),
        page: int = Query(1, ge=1, description="페이지 번호 (1부터)"),
        size: int = Query(50, ge=1, le=200, description="페이지 크기"),
        current_user: Member = Depends(get_current_admin_user),
):
    """Admin fleet — cluster-agent 전체 목록"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_admin_agents(
            user_info=user_info,
            status=status,
            clusterName=clusterName,
            versionPrefix=versionPrefix,
            lastSeenOlderThanSec=lastSeenOlderThanSec,
            page=page,
            size=size,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing admin agents for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail="Failed to list admin agents",
        )


@router_admin_agent.get("/admin/agent/heartbeat-staleness")
async def admin_agent_heartbeat_staleness(
        current_user: Member = Depends(get_current_admin_user)
):
    """에이전트 heartbeat 정체 상태"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.admin_agent_heartbeat_staleness(user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting agent heartbeat staleness: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get heartbeat staleness")


@router_admin_agent.post("/admin/agent/heartbeat-staleness")
async def admin_agent_heartbeat_staleness_run(
        body: Dict[str, Any] = Body(default={}),
        current_user: Member = Depends(get_current_admin_user)
):
    """heartbeat 정체 처리 실행"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.admin_agent_heartbeat_staleness_run(body or {}, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error running heartbeat staleness: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to run heartbeat staleness")


@router_admin_agent.get("/admin/agent/policy/preview")
async def admin_agent_policy_preview(
        request: Request,
        current_user: Member = Depends(get_current_admin_user)
):
    """에이전트 정책 미리보기"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.admin_agent_policy_preview(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error previewing agent policy: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to preview agent policy")


@router_admin_agent.get("/admin/agent/policy/audit")
async def admin_agent_policy_audit(
        request: Request,
        current_user: Member = Depends(get_current_admin_user)
):
    """에이전트 정책 audit"""
    try:
        user_info = _create_user_info_dict(current_user)
        query_params = dict(request.query_params)
        return await any_cloud_service.admin_agent_policy_audit(user_info=user_info, **query_params)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error auditing agent policy: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to audit agent policy")


@router_admin_agent.put("/admin/clusters/{cluster_name}/agent-policy")
async def admin_put_cluster_agent_policy(
        cluster_name: str = Path(..., description="클러스터 이름"),
        body: Dict[str, Any] = Body(...),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 에이전트 정책 적용"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.admin_put_cluster_agent_policy(cluster_name, body, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying agent policy for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to apply agent policy")


@router_admin_agent.patch("/admin/clusters/{cluster_name}/agent-policy")
async def admin_patch_cluster_agent_policy(
        cluster_name: str = Path(..., description="클러스터 이름"),
        body: Dict[str, Any] = Body(...),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 에이전트 정책 부분 변경"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.admin_patch_cluster_agent_policy(cluster_name, body, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error patching agent policy for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to patch agent policy")


@router_admin_agent.post("/admin/clusters/{cluster_name}/agent/reinstall")
async def admin_reinstall_cluster_agent(
        cluster_name: str = Path(..., description="클러스터 이름"),
        body: Dict[str, Any] = Body(default={}),
        current_user: Member = Depends(get_current_admin_user)
):
    """클러스터 에이전트 재설치"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.admin_reinstall_cluster_agent(cluster_name, body or {}, user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error reinstalling agent for {cluster_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to reinstall agent")


@router_package.get(
    "/kubernetes/pods/{pod_name}/logs",
    response_class=PlainTextResponse,
)
async def get_pod_logs(
        request: Request,
        pod_name: str = Path(..., description="파드 이름"),
        clusterName: str = Query(..., description="클러스터 이름"),
        namespace: str = Query("", description="네임스페이스"),
        current_user: Member = Depends(get_current_user)
):
    """파드 로그 (text/plain — SSE 아닌 단일 조회)"""
    try:
        user_info = _create_user_info_dict(current_user)
        # 컨트롤 query 제외
        excluded = {"clusterName", "namespace"}
        extra_params = {
            k: v for k, v in dict(request.query_params).items() if k not in excluded
        }
        text = await any_cloud_service.get_pod_logs(
            cluster_name=clusterName,
            namespace=namespace,
            pod_name=pod_name,
            user_info=user_info,
            **extra_params,
        )
        return PlainTextResponse(text, media_type="text/plain")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting pod logs {pod_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get pod logs")


@router_package.post("/kubernetes/{resource_type}", response_model=AnyCloudResponse)
async def create_kubernetes_resource(
        resource_type: str = Path(..., description="리소스 타입"),
        body: Dict[str, Any] = Body(...),
        clusterName: str = Query(..., description="클러스터 이름"),
        namespace: str = Query("", description="네임스페이스"),
        current_user: Member = Depends(get_current_admin_user)
):
    """쿠버네티스 리소스 생성 (JSON 또는 YAML 객체 형태)"""
    try:
        resource_type = _validate_kubernetes_resource_type(resource_type)
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.create_kubernetes_resource(
            resource_type=resource_type,
            clusterName=clusterName,
            namespace=namespace,
            data=body,
            user_info=user_info,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating k8s resource {resource_type}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create kubernetes resource")


# ==================== VM resource (/v1/vms backend) ====================

from app.schemas.any_cloud import VmGatewayCreateRequest, VmGatewayPatchRequest


@router_vm.get("", response_model=AnyCloudPagedResponse)
async def list_vms(
        page: int = Query(1, ge=1),
        size: int = Query(20, ge=1, le=100),
        provider: Optional[str] = Query(None, description="CSP filter"),
        environment: Optional[str] = Query(None, description="환경 filter"),
        status_filter: Optional[str] = Query(None, alias="status", description="VM 상태 filter"),
        search: Optional[str] = Query(None, description="검색어"),
        current_user: Member = Depends(get_current_user),
):
    """VM 인프라 목록"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.list_vms(
            user_info=user_info,
            provider=provider,
            environment=environment,
            status_filter=status_filter,
            page=page,
            size=size,
            search=search,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing vms: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to list VMs")


@router_vm.get("/{vm_name}")
async def get_vm(
        vm_name: str = Path(..., description="VM cluster 이름"),
        current_user: Member = Depends(get_current_user),
):
    """VM 상세 (workflow / stack outputs / 진행 상태)"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.get_vm_detail(vm_name=vm_name, user_info=user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting vm {vm_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get VM")


@router_vm.post("")
async def create_vm(
        request: VmGatewayCreateRequest = Body(...),
        current_user: Member = Depends(get_current_admin_user),
):
    """VM 생성 (Pulumi provision) — 202 + Operation"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.create_vm(
            request_data=request.model_dump(exclude_none=True),
            user_info=user_info,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating vm: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create VM")


@router_vm.patch("/{vm_name}")
async def patch_vm(
        vm_name: str = Path(...),
        request: VmGatewayPatchRequest = Body(...),
        current_user: Member = Depends(get_current_admin_user),
):
    """VM scale (workerCount 변경) — 202 + Operation"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.patch_vm(
            vm_name=vm_name,
            request_data=request.model_dump(exclude_none=True),
            user_info=user_info,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error patching vm {vm_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to patch VM")


@router_vm.delete("/{vm_name}")
async def delete_vm(
        vm_name: str = Path(...),
        current_user: Member = Depends(get_current_admin_user),
):
    """VM 삭제 (Pulumi destroy) — 202 + Operation"""
    try:
        user_info = _create_user_info_dict(current_user)
        return await any_cloud_service.delete_vm(vm_name=vm_name, user_info=user_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting vm {vm_name}: {str(e)}")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to delete VM")


@router_vm.get("/{vm_name}/operations")
async def list_vm_operations(
        vm_name: str = Path(...),
        size: int = Query(50, ge=1, le=500, description="페이지 크기"),
        current_user: Member = Depends(get_current_user),
):
    """이 VM 의 operation 이력"""
    user_info = _create_user_info_dict(current_user)
    return await any_cloud_service.list_vm_operations(vm_name=vm_name, user_info=user_info, page_size=size)


@router_vm.post("/{vm_name}/operations")
async def create_vm_operation(
        vm_name: str = Path(...),
        op_type: str = Body(..., embed=True, alias="type"),
        current_user: Member = Depends(get_current_admin_user),
):
    """VM 액션 (retryWorkflow / retryRegistration / refreshStatus)"""
    user_info = _create_user_info_dict(current_user)
    return await any_cloud_service.create_vm_operation(vm_name=vm_name, op_type=op_type, user_info=user_info)


@router_vm.get("/{vm_name}/state-history")
async def get_vm_state_history(
        vm_name: str = Path(...),
        size: int = Query(50, ge=1, le=500, description="페이지 크기"),
        current_user: Member = Depends(get_current_user),
):
    """VM workflow state transition 이력"""
    user_info = _create_user_info_dict(current_user)
    return await any_cloud_service.get_vm_state_history(vm_name=vm_name, user_info=user_info, page_size=size)


@router_vm.get("/{vm_name}/nodes")
async def get_vm_nodes(
        vm_name: str = Path(...),
        current_user: Member = Depends(get_current_user),
):
    """VM 노드 목록 (role / publicIp / privateIp + SSH 사용자)"""
    user_info = _create_user_info_dict(current_user)
    return await any_cloud_service.get_vm_nodes(vm_name=vm_name, user_info=user_info)


@router_vm.post("/{vm_name}/ssh-key")
async def issue_vm_ssh_key(
        vm_name: str = Path(...),
        format: str = Query("json", pattern="^(json|pem)$"),
        current_user: Member = Depends(get_current_admin_user),
):
    """VM SSH private key 발급. format=pem 이면 raw PEM 파일로 내려간다."""
    user_info = _create_user_info_dict(current_user)
    result = await any_cloud_service.issue_vm_ssh_key(vm_name=vm_name, user_info=user_info, fmt=format)
    if format == "pem":
        return PlainTextResponse(
            result,
            media_type="application/x-pem-file",
            headers={"Content-Disposition": _attachment(f"{vm_name}.pem")},
        )
    return result


@router_vm.get("/{vm_name}/kubeconfig", response_class=PlainTextResponse)
async def download_vm_kubeconfig(
        vm_name: str = Path(...),
        serviceAccount: Optional[str] = Query(None),
        namespace: Optional[str] = Query(None),
        ttlSeconds: Optional[int] = Query(None),
        current_user: Member = Depends(get_current_admin_user),
):
    """VM 의 kubeconfig YAML 다운로드 (단기 SA token)"""
    user_info = _create_user_info_dict(current_user)
    params = {k: v for k, v in {
        "serviceAccount": serviceAccount,
        "namespace": namespace,
        "ttlSeconds": ttlSeconds,
    }.items() if v is not None}
    content = await any_cloud_service.download_vm_kubeconfig(vm_name=vm_name, user_info=user_info, **params)
    return PlainTextResponse(
        content,
        media_type="application/yaml",
        headers={"Content-Disposition": _attachment(f"{vm_name}-kubeconfig.yaml")},
    )
