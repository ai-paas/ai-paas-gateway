import logging
from typing import Dict, Any, Optional, List
from urllib.parse import quote

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.schemas.any_cloud import AnyCloudPagedResponse

logger = logging.getLogger(__name__)


def _seg(value: Any) -> str:
    """upstream 경로 세그먼트 인코딩.

    클러스터명/네임스페이스 등은 사용자 입력(Path·Query)에서 오므로 그대로 f-string 에
    넣으면 `../` 로 upstream 의 다른 엔드포인트를 호출할 수 있다(httpx 가 dot-segment 를
    정규화한다). 정상 값(RFC 1123 label 등)에는 인코딩 대상 문자가 없어 no-op.
    """
    return quote(str(value), safe="")


class AnyCloudService:
    """Any Cloud 연결 서비스 - 외부 Any Cloud API 라우팅 게이트웨이"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=settings.ANY_CLOUD_TIMEOUT,
                connect=settings.ANY_CLOUD_CONNECT_TIMEOUT
            ),
            limits=httpx.Limits(
                max_keepalive_connections=settings.ANY_CLOUD_MAX_KEEPALIVE_CONNECTIONS,
                max_connections=settings.ANY_CLOUD_MAX_CONNECTIONS
            ),
            follow_redirects=True
        )
        # 외부 Any Cloud API URL
        self.base_url = settings.ANY_CLOUD_TARGET_BASE_URL

    async def close(self):
        """HTTP 클라이언트 종료"""
        await self.client.aclose()

    def _get_headers(self, user_info: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """요청 헤더 생성"""
        headers = {
            'Accept': 'application/json',
            'Content-Type': 'application/json',
            'User-Agent': 'AIPaaS-AnyCloud-Gateway/1.0'
        }

        # 사용자 정보 추가
        if user_info:
            if user_info.get('member_id'):
                headers['X-User-ID'] = str(user_info['member_id'])
            if user_info.get('role'):
                headers['X-User-Role'] = str(user_info['role'])
            if user_info.get('name'):
                import base64
                name_b64 = base64.b64encode(str(user_info['name']).encode('utf-8')).decode('ascii')
                headers['X-User-Name-B64'] = name_b64

        return headers

    def _apply_client_side_pagination(
            self,
            data: List[Any],
            page: int,
            size: int,
            search: Optional[str] = None,
            search_fields: Optional[List[str]] = None
    ) -> AnyCloudPagedResponse:
        """
        클라이언트 사이드 페이징 처리
        백엔드에서 전체 데이터를 받아서 페이징 처리
        """
        def get_nested_value(item: Any, field: str) -> Any:
            value = item

            for key in field.split("."):
                if not isinstance(value, dict):
                    return ""

                value = value.get(key)

            return value if value is not None else ""

        # 검색 처리
        filtered_data = data
        if search and search_fields:
            search_lower = search.lower()
            filtered_data = [
                item for item in data
                if any(
                    search_lower in str(get_nested_value(item, field)).lower()
                    for field in search_fields
                )
            ]

        total = len(filtered_data)
        start = (page - 1) * size
        end = start + size
        paginated_data = filtered_data[start:end]

        return AnyCloudPagedResponse.create(
            data=paginated_data,
            total=total,
            page=page,
            size=size
        )

    async def _make_request(
            self,
            method: str,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **kwargs
    ) -> Dict[str, Any]:
        """Any Cloud API 요청 실행 및 응답을 data로 래핑"""
        try:
            url = f"{self.base_url}{path}"

            # 헤더 설정
            headers = self._get_headers(user_info)

            # 기존 헤더와 병합
            if 'headers' in kwargs:
                kwargs['headers'].update(headers)
            else:
                kwargs['headers'] = headers

            logger.info(f"Making {method} request to Any Cloud: {url}")
            if kwargs.get('params'):
                logger.info(f"Parameters: {kwargs['params']}")

            # 요청 실행
            response = await getattr(self.client, method.lower())(url, **kwargs)

            if 200 <= response.status_code < 300:
                if response.status_code == 204 or not response.content:
                    return {"data": None}
                response_data = response.json()
                # success/data 형태로 감싸 내려오는 응답은 data 만 추출
                if isinstance(response_data, dict) and "data" in response_data and "success" in response_data:
                    response_data = response_data["data"]
                return {"data": response_data}
            else:
                logger.error(f"Any Cloud API error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Any Cloud API request failed: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout calling Any Cloud API {path}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Any Cloud service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error calling Any Cloud API {path}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Any Cloud service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error calling Any Cloud API {path}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def generic_get_unwrapped(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Any:
        """GET 요청 — data 필드만 반환"""
        response = await self._make_request(
            "GET", path, user_info=user_info, params=query_params
        )
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def generic_get(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """GET 요청"""
        return await self._make_request(
            "GET", path, user_info=user_info, params=query_params
        )

    async def generic_put(
            self,
            path: str,
            data: Dict[str, Any],
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """PUT 요청"""
        response = await self._make_request(
            "PUT", path, user_info=user_info, json=data, params=query_params
        )
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def generic_delete(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """DELETE 요청"""
        response = await self._make_request(
            "DELETE", path, user_info=user_info, params=query_params
        )
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def generic_post(
            self,
            path: str,
            data: Dict[str, Any],
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """POST 요청"""
        response = await self._make_request(
            "POST", path, user_info=user_info, json=data, params=query_params
        )
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def simple_post(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """본문 없는 POST 요청"""
        response = await self._make_request(
            "POST", path, user_info=user_info, params=query_params
        )
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def generic_post_file(
            self,
            path: str,
            data: Dict[str, Any],
            user_info: Optional[Dict[str, str]] = None,
            files: Optional[Dict[str, Any]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """파일 업로드 가능한 POST 요청"""
        if files or any(key == "valuesFile" for key in data.keys()):
            response = await self._make_multipart_request(
                "POST", path, data=data, files=files, user_info=user_info, params=query_params
            )
        else:
            response = await self._make_request(
                "POST", path, user_info=user_info, json=data, params=query_params
            )

        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def _make_multipart_request(
            self,
            method: str,
            path: str,
            data: Optional[Dict[str, Any]] = None,
            files: Optional[Dict[str, Any]] = None,
            user_info: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """멀티파트 요청"""
        headers = self._get_headers(user_info)
        # Content-Type 은 httpx 가 boundary 와 함께 자동 설정
        headers.pop('Content-Type', None)

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

        form_data: Dict[str, Any] = {}
        file_data: Dict[str, Any] = {}

        if data:
            for key, value in data.items():
                if key == "valuesFile" and isinstance(value, str):
                    import base64
                    file_content = base64.b64decode(value)
                    file_data["valuesFile"] = ("values.yaml", file_content, "application/x-yaml")
                else:
                    form_data[key] = value

        if files:
            file_data.update(files)

        try:
            response = await self.client.request(
                method=method,
                url=url,
                headers=headers,
                data=form_data,
                files=file_data,
                params=params
            )
        except httpx.TimeoutException:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail="Any Cloud service timeout")
        except httpx.ConnectError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Any Cloud service unavailable")

        if not (200 <= response.status_code < 300):
            logger.error(f"Any Cloud API error: {response.status_code} - {response.text}")
            raise HTTPException(response.status_code, detail=f"Any Cloud API request failed: {response.text}")

        if response.status_code == 204 or not response.content:
            return {"data": None}
        body = response.json()
        if isinstance(body, dict) and "data" in body and "success" in body:
            return {"data": body["data"]}
        return {"data": body}

    async def get_clusters(
            self,
            user_info: dict,
            page: int = 1,
            size: int = 20,
            search: Optional[str] = None
    ) -> AnyCloudPagedResponse:
        """클러스터 목록 조회"""
        response = await self.generic_get(
            path="/v1/clusters",
            user_info=user_info
        )

        data = response.get("data", [])
        if isinstance(data, dict):
            data = data.get("items", [])

        return self._apply_client_side_pagination(
            data=data,
            page=page,
            size=size,
            search=search,
            search_fields=["clusterName", "clusterId", "clusterProvider", "clusterType"]
        )

    async def check_cluster_exists(self, cluster_id: str, user_info: dict) -> dict:
        """클러스터 존재 여부 확인 — 별도 엔드포인트가 없어 상세조회의 404 여부로 판정"""
        try:
            await self.generic_get_unwrapped(
                path=f"/v1/clusters/{_seg(cluster_id)}",
                user_info=user_info
            )
            return {"data": {"exists": True}}
        except HTTPException as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                return {"data": {"exists": False}}
            raise

    async def get_cluster_detail(self, cluster_id: str, user_info: dict) -> dict:
        """클러스터 상세 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{_seg(cluster_id)}",
            user_info=user_info
        )

    async def get_cluster_test_connection(self, cluster_id: str, user_info: dict) -> dict:
        """클러스터 연결 상태 확인"""
        return await self.simple_post(
            path=f"/v1/clusters/{_seg(cluster_id)}/connectivity-checks",
            user_info=user_info
        )

    async def cluster_refresh(self, cluster_id: str, user_info: dict) -> dict:
        """클러스터 상태 강제 갱신"""
        return await self.generic_post(
            path=f"/v1/clusters/{_seg(cluster_id)}/operations",
            data={"type": "refreshStatus"},
            user_info=user_info
        )

    # ==================== VM resource (/v1/vms) ====================

    async def list_vms(
            self,
            user_info: dict,
            provider: Optional[str] = None,
            environment: Optional[str] = None,
            status_filter: Optional[str] = None,
            page: int = 1,
            size: int = 20,
            search: Optional[str] = None
    ) -> AnyCloudPagedResponse:
        """VM 인프라 목록"""
        params: Dict[str, Any] = {}
        if provider:
            params["provider"] = provider
        if environment:
            params["environment"] = environment
        if status_filter:
            params["status"] = status_filter
        response = await self.generic_get(path="/v1/vms", user_info=user_info, **params)
        data = response.get("data", [])
        if isinstance(data, dict):
            data = data.get("items", [])
        return self._apply_client_side_pagination(
            data=data,
            page=page,
            size=size,
            search=search,
            search_fields=["clusterName", "clusterProvider", "region", "environment", "status"]
        )

    async def get_vm_detail(self, vm_name: str, user_info: dict) -> dict:
        """VM 상세 (workflow / stack outputs)"""
        return await self.generic_get_unwrapped(path=f"/v1/vms/{_seg(vm_name)}", user_info=user_info)

    async def create_vm(self, request_data: Dict[str, Any], user_info: dict) -> dict:
        """VM 생성 (Pulumi provision 트리거 — 202 + Operation)"""
        return await self.generic_post(path="/v1/vms", data=request_data, user_info=user_info)

    async def patch_vm(self, vm_name: str, request_data: Dict[str, Any], user_info: dict) -> dict:
        """VM scale — workerCount 변경"""
        response = await self._make_request(
            "PATCH", f"/v1/vms/{_seg(vm_name)}", user_info=user_info, json=request_data
        )
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def delete_vm(self, vm_name: str, user_info: dict) -> dict:
        """VM 삭제 (Pulumi destroy — 202 + Operation)"""
        return await self.generic_delete(path=f"/v1/vms/{_seg(vm_name)}", user_info=user_info)

    async def list_vm_operations(self, vm_name: str, user_info: dict, page_size: int = 50) -> dict:
        """VM 의 operation 이력"""
        return await self.generic_get_unwrapped(
            path=f"/v1/vms/{_seg(vm_name)}/operations", user_info=user_info, pageSize=page_size
        )

    async def create_vm_operation(self, vm_name: str, op_type: str, user_info: dict) -> dict:
        """VM 액션 (retryWorkflow / retryRegistration / refreshStatus)"""
        return await self.generic_post(
            path=f"/v1/vms/{_seg(vm_name)}/operations",
            data={"type": op_type},
            user_info=user_info
        )

    async def get_vm_state_history(self, vm_name: str, user_info: dict, page_size: int = 50) -> dict:
        """VM workflow state transition history"""
        return await self.generic_get_unwrapped(
            path=f"/v1/vms/{_seg(vm_name)}/state-history", user_info=user_info, pageSize=page_size
        )

    async def get_vm_nodes(self, vm_name: str, user_info: dict) -> dict:
        """VM 노드 목록 (role / publicIp / privateIp)"""
        return await self.generic_get_unwrapped(path=f"/v1/vms/{_seg(vm_name)}/nodes", user_info=user_info)

    async def issue_vm_ssh_key(self, vm_name: str, user_info: dict, fmt: str = "json") -> Any:
        """VM SSH private key 발급 (json=metadata, pem=raw file)"""
        if fmt == "pem":
            # raw PEM 응답 — text/plain. _make_request 의 JSON 가정 우회 필요하여 직접 처리.
            return await self._make_request(
                "POST", f"/v1/vms/{_seg(vm_name)}/ssh-key",
                user_info=user_info, params={"format": "pem"}
            )
        return await self.generic_post(
            path=f"/v1/vms/{_seg(vm_name)}/ssh-key", data={}, user_info=user_info, format=fmt
        )

    async def download_vm_kubeconfig(self, vm_name: str, user_info: dict, **params) -> Any:
        """VM 의 kubeconfig YAML 다운로드 (단기 SA token)"""
        return await self._make_request(
            "GET", f"/v1/vms/{_seg(vm_name)}/kubeconfig", user_info=user_info, params=params
        )

    async def get_helm_repos(
            self,
            user_info: dict,
            page: int = 1,
            size: int = 20,
            search: Optional[str] = None
    ) -> AnyCloudPagedResponse:
        """헬름 저장소 목록 조회"""
        response = await self.generic_get(
            path="/v1/helm-repos",
            user_info=user_info
        )

        data = response.get("data", [])
        if isinstance(data, dict):
            data = data.get("items", [])

        return self._apply_client_side_pagination(
            data=data,
            page=page,
            size=size,
            search=search,
            search_fields=["name", "url"]
        )

    async def check_helm_repos_exists(self, helm_repo_name: str, user_info: dict) -> dict:
        """헬름 저장소 존재 여부 확인 — 별도 엔드포인트가 없어 상세조회의 404 여부로 판정"""
        try:
            await self.generic_get_unwrapped(
                path=f"/v1/helm-repos/{_seg(helm_repo_name)}",
                user_info=user_info
            )
            return {"data": {"exists": True}}
        except HTTPException as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                return {"data": {"exists": False}}
            raise

    async def get_helm_repos_detail(self, helm_repo_name: str, user_info: dict) -> dict:
        """헬름 저장소 상세 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/helm-repos/{_seg(helm_repo_name)}",
            user_info=user_info
        )

    async def get_prometheus_query(
            self,
            cluster_name: str,
            query_params: dict,
            user_info: dict
    ) -> dict:
        """Prometheus instant query (raw passthrough). _make_request 의 outer data wrap 만 strip."""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{_seg(cluster_name)}/metrics/query",
            user_info=user_info,
            **query_params
        )

    async def get_prometheus_query_range(
            self,
            cluster_name: str,
            query_params: dict,
            user_info: dict
    ) -> dict:
        """Prometheus range query (raw passthrough)."""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{_seg(cluster_name)}/metrics/query_range",
            user_info=user_info,
            **query_params
        )

    async def multi_query_prometheus(
            self,
            cluster_name: str,
            queries: list,
            user_info: dict
    ) -> dict:
        """N개의 PromQL 을 한 번에 backend 로 위임 — name → Prometheus envelope map."""
        return await self.generic_post(
            path=f"/v1/clusters/{_seg(cluster_name)}/metrics/multi-query",
            data={"queries": queries},
            user_info=user_info
        )

    async def get_kubernetes_resource(
            self,
            resource_type: str,
            clusterName: str,
            namespace: str,
            user_info: dict,
            page: int = 1,
            size: int = 20,
            search: Optional[str] = None,
            pageToken: Optional[str] = None,
            labelSelector: Optional[str] = None
    ) -> AnyCloudPagedResponse:
        """쿠버네티스 리소스 목록 조회"""
        # 클러스터 범위 리소스는 namespace 자리에 '-' 를 사용
        ns_path = namespace if namespace else "-"

        # search 가 명시되면 전체를 받아 메모리에서 필터, 아니면 페이지 단위 그대로 전달
        if search:
            backend_params = {"pageSize": 500}
        else:
            backend_params = {"pageSize": size}
            if pageToken:
                backend_params["pageToken"] = pageToken
        if labelSelector:
            backend_params["labelSelector"] = labelSelector

        response = await self.generic_get(
            path=f"/v1/clusters/{_seg(clusterName)}/namespaces/{_seg(ns_path)}/{_seg(resource_type)}",
            user_info=user_info,
            **backend_params
        )

        raw_data = response.get("data", [])
        next_token = None

        if isinstance(raw_data, dict):
            data = raw_data.get("items")
            if data is None:
                data = raw_data.get("data", [])
            # 쿠버네티스 응답이 한 번 더 감싸진 형태일 때 안쪽 items 를 사용
            if isinstance(data, dict):
                inner_meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
                next_token = (
                    raw_data.get("continueToken")
                    or raw_data.get("nextPageToken")
                    or inner_meta.get("continue")
                )
                data = data.get("items", [])
            else:
                next_token = raw_data.get("continueToken") or raw_data.get("nextPageToken")
        else:
            data = raw_data

        if not isinstance(data, list):
            data = []

        if search:
            return self._apply_client_side_pagination(
                data=data,
                page=page,
                size=size,
                search=search,
                search_fields=["metadata.name"]
            )

        return AnyCloudPagedResponse.create(
            data=data,
            total=len(data),
            page=page,
            size=size,
            next_page_token=next_token
        )

    async def get_kubernetes_resource_name(self, resource_type: str, resource_name: str, clusterName: str, namespace: str, user_info: dict) -> dict:
        """쿠버네티스 리소스 단건 조회"""
        ns_path = namespace if namespace else "-"
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(clusterName)}/namespaces/{_seg(ns_path)}/{_seg(resource_type)}/{_seg(resource_name)}",
            user_info=user_info
        )

    async def delete_kubernetes_resource(self, resource_type: str, resource_name: str, clusterName: str, namespace: str, user_info: dict) -> dict:
        """쿠버네티스 리소스 삭제"""
        ns_path = namespace if namespace else "-"
        return await self.generic_delete(
            path=f"/v1/clusters/{_seg(clusterName)}/namespaces/{_seg(ns_path)}/{_seg(resource_type)}/{_seg(resource_name)}",
            user_info=user_info
        )

    async def get_kubernetes_resource_events(self, resource_type: str, resource_name: str, clusterName: str, namespace: str, user_info: dict) -> dict:
        """쿠버네티스 리소스의 K8s Event 목록 (involvedObject 필터)"""
        ns_path = namespace if namespace else "-"
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(clusterName)}/namespaces/{_seg(ns_path)}/{_seg(resource_type)}/{_seg(resource_name)}/events",
            user_info=user_info
        )

    async def restart_kubernetes_resource(self, resource_type: str, resource_name: str, clusterName: str, namespace: str, user_info: dict) -> dict:
        """쿠버네티스 리소스 재시작 (pods: delete / deployments+: rollout restart annotation)"""
        ns_path = namespace if namespace else "-"
        return await self.simple_post(
            path=f"/v1/clusters/{_seg(clusterName)}/namespaces/{_seg(ns_path)}/{_seg(resource_type)}/{_seg(resource_name)}/restart",
            user_info=user_info
        )

    async def scale_kubernetes_resource(self, resource_type: str, resource_name: str, clusterName: str, namespace: str, replicas: int, user_info: dict) -> dict:
        """쿠버네티스 리소스 스케일 (replicas 변경) — deployments/replicasets/statefulsets"""
        ns_path = namespace if namespace else "-"
        return await self.simple_post(
            path=f"/v1/clusters/{_seg(clusterName)}/namespaces/{_seg(ns_path)}/{_seg(resource_type)}/{_seg(resource_name)}/scale",
            user_info=user_info,
            replicas=replicas
        )

    async def get_kubernetes_test(self, clusterName: str, user_info: dict) -> dict:
        """클러스터 연결 상태 확인"""
        return await self.simple_post(
            path=f"/v1/clusters/{_seg(clusterName)}/connectivity-checks",
            user_info=user_info
        )

    async def create_cluster(self, data: dict, user_info: dict) -> dict:
        """클러스터 생성"""
        return await self.generic_post(
            path="/v1/clusters",
            data=data,
            user_info=user_info
        )

    async def update_cluster(self, data: dict, cluster_id: str, user_info: dict) -> dict:
        """클러스터 수정"""
        logger.info(f"Sending data to Any Cloud: {data}")
        response = await self._make_request(
            "PATCH", f"/v1/clusters/{_seg(cluster_id)}", user_info=user_info, json=data
        )
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def create_helm_repo(self, data: dict, user_info: dict) -> dict:
        """헬름 저장소 생성"""
        return await self.generic_post(
            path="/v1/helm-repos",
            data=data,
            user_info=user_info
        )

    async def delete_cluster(self, cluster_id: str, user_info: dict) -> dict:
        """클러스터 삭제"""
        return await self.generic_delete(
            path=f"/v1/clusters/{_seg(cluster_id)}",
            user_info=user_info
        )

    async def delete_helm_repo(self, helm_repo_name: str, user_info: dict) -> dict:
        """헬름 저장소 삭제"""
        return await self.generic_delete(
            path=f"/v1/helm-repos/{_seg(helm_repo_name)}",
            user_info=user_info
        )

    async def get_catalog_releases(
            self,
            clusterId: str,
            namespace: str,
            user_info: dict,
            page: int = 1,
            size: int = 20,
            search: Optional[str] = None
    ) -> AnyCloudPagedResponse:
        """Helm release 목록 조회"""
        # backend 가 namespace 를 정규식으로 검증 — 빈 문자열 거절. 전체 namespace 는 '_all'.
        ns_query = namespace if namespace else "_all"
        response = await self.generic_get(
            path=f"/v1/clusters/{_seg(clusterId)}/helm-releases",
            namespace=ns_query,
            user_info=user_info
        )

        data = response.get("data", {})
        if isinstance(data, dict) and "data" in data:
            data = data.get("data", {})
        if isinstance(data, dict):
            data = data.get("releases", [])

        return self._apply_client_side_pagination(
            data=data,
            page=page,
            size=size,
            search=search,
            search_fields=["name", "chart", "namespace", "revision", "status"]
        )

    async def get_catalog_list(
            self,
            repoName: str,
            user_info: dict,
            page: int = 1,
            size: int = 20,
            search: Optional[str] = None
    ) -> AnyCloudPagedResponse:
        """Helm 차트 목록 조회"""
        response = await self.generic_get(
            path=f"/v1/helm-repos/{_seg(repoName)}/charts",
            user_info=user_info
        )

        data = response.get("data", {})
        if isinstance(data, dict) and "data" in data:
            data = data.get("data", {})
        if isinstance(data, dict):
            data = data.get("charts", [])

        return self._apply_client_side_pagination(
            data=data,
            page=page,
            size=size,
            search=search,
            search_fields=["name", "description", "version", "appVersion"]
        )

    async def get_catalog_chart(self, repoName: str, chartName: str, version: Optional[str], user_info: dict) -> dict:
        """차트 상세 조회"""
        # 빈 문자열을 보내면 백엔드 검증을 통과하지 못하므로 값이 있을 때만 전달
        params: Dict[str, Any] = {}
        if version:
            params["version"] = version
        return await self.generic_get_unwrapped(
            path=f"/v1/helm-repos/{_seg(repoName)}/charts/{_seg(chartName)}",
            user_info=user_info,
            **params
        )

    async def get_catalog_readme(self, repoName: str, chartName: str, version: Optional[str], user_info: dict) -> dict:
        """차트 README 조회"""
        params: Dict[str, Any] = {}
        if version:
            params["version"] = version
        return await self.generic_get_unwrapped(
            path=f"/v1/helm-repos/{_seg(repoName)}/charts/{_seg(chartName)}/readme",
            user_info=user_info,
            **params
        )

    async def get_catalog_status(self, repoName: str, chartName: str, releaseName: str, clusterId: str, namespace: str, user_info: dict) -> dict:
        """릴리즈 상태 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{_seg(clusterId)}/helm-releases/{_seg(releaseName)}",
            namespace=namespace,
            user_info=user_info
        )

    async def get_catalog_values(self, repoName: str, chartName: str, version: Optional[str], user_info: dict) -> dict:
        """차트 values 조회"""
        params: Dict[str, Any] = {}
        if version:
            params["version"] = version
        return await self.generic_get_unwrapped(
            path=f"/v1/helm-repos/{_seg(repoName)}/charts/{_seg(chartName)}/values",
            user_info=user_info,
            **params
        )

    async def get_catalog_resources(self, clusterId: str, namespace: str, releaseName: str, user_info: dict) -> dict:
        """릴리즈 리소스 목록 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{_seg(clusterId)}/helm-releases/{_seg(releaseName)}/resources",
            namespace=namespace,
            user_info=user_info
        )

    async def create_catalog_deploy(
            self,
            repoName: str,
            chartName: str,
            releaseName: str,
            clusterId: str,
            namespace: str = "default",
            version: Optional[str] = None,
            valuesFile: Optional[bytes] = None,
            user_info: dict = None
    ) -> dict:
        """차트 배포"""
        deploy_data = {
            "releaseName": releaseName,
            "chartRef": f"{repoName}/{chartName}",
            "namespace": namespace
        }
        if version:
            deploy_data["version"] = version
        if valuesFile:
            import base64
            deploy_data["valuesFile"] = base64.b64encode(valuesFile).decode('utf-8')

        return await self.generic_post_file(
            path=f"/v1/clusters/{_seg(clusterId)}/helm-releases",
            data=deploy_data,
            user_info=user_info
        )

    async def get_operations(self, user_info: dict, **query_params) -> dict:
        """작업 이력 목록 조회"""
        return await self.generic_get(
            path="/v1/operations",
            user_info=user_info,
            **query_params
        )

    async def get_operation(self, operation_id: str, user_info: dict) -> dict:
        """작업 단건 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/operations/{_seg(operation_id)}",
            user_info=user_info
        )

    async def cancel_operation(self, operation_id: str, user_info: dict) -> dict:
        """진행 중 작업 취소"""
        return await self.simple_post(
            path=f"/v1/operations/{_seg(operation_id)}/cancel",
            user_info=user_info
        )

    async def validate_cluster(self, data: dict, user_info: dict) -> dict:
        """클러스터 생성 사전 검증"""
        return await self.generic_post(
            path="/v1/cluster-validations",
            data=data,
            user_info=user_info
        )

    async def preview_cluster(self, data: dict, user_info: dict) -> dict:
        """클러스터 생성 미리보기"""
        return await self.generic_post(
            path="/v1/cluster-validations/preview",
            data=data,
            user_info=user_info
        )

    async def list_providers(self, user_info: dict) -> dict:
        """지원 CSP 목록 조회"""
        return await self.generic_get(
            path="/v1/providers",
            user_info=user_info
        )

    async def get_provider_regions(self, provider: str, user_info: dict) -> dict:
        """CSP 별 region 목록 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/providers/{_seg(provider)}/regions",
            user_info=user_info
        )

    async def get_provider_specs(self, provider: str, user_info: dict, **query_params) -> dict:
        """CSP 별 VM spec 목록 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/providers/{_seg(provider)}/specs",
            user_info=user_info,
            **query_params
        )

    async def get_provider_config_schema(self, provider: str, user_info: dict) -> dict:
        """CSP 별 클러스터 설정 스키마 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/providers/{_seg(provider)}/config-schema",
            user_info=user_info
        )

    async def get_provider_images(self, provider: str, user_info: dict, **query_params) -> dict:
        """CSP 별 OS 이미지 목록 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/providers/{_seg(provider)}/images",
            user_info=user_info,
            **query_params
        )

    async def list_credentials(self, user_info: dict, **query_params) -> dict:
        """CSP 자격증명 목록 조회"""
        return await self.generic_get(
            path="/v1/credentials",
            user_info=user_info,
            **query_params
        )

    async def get_credential(self, credential_id: str, user_info: dict) -> dict:
        """CSP 자격증명 단건 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/credentials/{_seg(credential_id)}",
            user_info=user_info
        )

    async def create_credential(self, data: dict, user_info: dict) -> dict:
        """CSP 자격증명 등록"""
        return await self.generic_post(
            path="/v1/credentials",
            data=data,
            user_info=user_info
        )

    async def delete_credential(self, credential_id: str, user_info: dict) -> dict:
        """CSP 자격증명 삭제"""
        return await self.generic_delete(
            path=f"/v1/credentials/{_seg(credential_id)}",
            user_info=user_info
        )

    async def list_addon_catalog(self, user_info: dict) -> dict:
        """설치 가능한 애드온 목록 조회"""
        return await self.generic_get(
            path="/v1/addons",
            user_info=user_info
        )

    async def list_cluster_addons(self, cluster_name: str, user_info: dict) -> dict:
        """클러스터에 설치된 애드온 목록 조회"""
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(cluster_name)}/addons",
            user_info=user_info
        )

    async def get_cluster_addon(self, cluster_name: str, addon_id: str, user_info: dict) -> dict:
        """애드온 단건 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{_seg(cluster_name)}/addons/{_seg(addon_id)}",
            user_info=user_info
        )

    async def install_cluster_addon(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """애드온 설치"""
        return await self.generic_post(
            path=f"/v1/clusters/{_seg(cluster_name)}/addons",
            data=data,
            user_info=user_info
        )

    async def uninstall_cluster_addon(self, cluster_name: str, addon_id: str, user_info: dict) -> dict:
        """애드온 제거"""
        return await self.generic_delete(
            path=f"/v1/clusters/{_seg(cluster_name)}/addons/{_seg(addon_id)}",
            user_info=user_info
        )

    async def retry_cluster_addon(self, cluster_name: str, addon_id: str, user_info: dict) -> dict:
        """실패한 애드온 재시도"""
        return await self.simple_post(
            path=f"/v1/clusters/{_seg(cluster_name)}/addons/{_seg(addon_id)}/retry",
            user_info=user_info
        )

    async def install_helm_release(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """Helm 릴리즈 설치"""
        return await self.generic_post(
            path=f"/v1/clusters/{_seg(cluster_name)}/helm-releases",
            data=data,
            user_info=user_info
        )

    async def get_audit_logs(self, user_info: dict, **query_params) -> dict:
        """감사 로그 조회"""
        return await self.generic_get(
            path="/v1/audit-logs",
            user_info=user_info,
            **query_params
        )

    async def get_cluster_kubeconfig(self, cluster_name: str, user_info: dict) -> str:
        """클러스터 kubeconfig 다운로드 (YAML 텍스트)"""
        headers = self._get_headers(user_info)
        headers['Accept'] = 'application/yaml'
        url = f"{self.base_url}/v1/clusters/{_seg(cluster_name)}/kubeconfig"
        try:
            response = await self.client.get(url, headers=headers)
        except httpx.TimeoutException:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail="Any Cloud service timeout")
        except httpx.ConnectError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Any Cloud service unavailable")
        if not (200 <= response.status_code < 300):
            logger.error(f"Any Cloud API error: {response.status_code} - {response.text}")
            raise HTTPException(response.status_code, detail=f"Any Cloud API request failed: {response.text}")
        return response.text

    async def get_cluster_agent_manifest(self, cluster_name: str, user_info: dict) -> str:
        """클러스터 agent 설치 manifest 다운로드 (YAML 텍스트)"""
        headers = self._get_headers(user_info)
        headers['Accept'] = 'application/yaml'
        url = f"{self.base_url}/v1/clusters/{_seg(cluster_name)}/agent-manifest.yaml"
        try:
            response = await self.client.get(url, headers=headers)
        except httpx.TimeoutException:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail="Any Cloud service timeout")
        except httpx.ConnectError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Any Cloud service unavailable")
        if not (200 <= response.status_code < 300):
            logger.error(f"Any Cloud API error: {response.status_code} - {response.text}")
            raise HTTPException(response.status_code, detail=f"Any Cloud API request failed: {response.text}")
        return response.text

    async def get_cluster_health(self, cluster_name: str, user_info: dict) -> dict:
        """클러스터 종합 health 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{_seg(cluster_name)}/health",
            user_info=user_info
        )

    async def get_agents_health(self, user_info: dict, **query_params) -> dict:
        """Fleet-wide 에이전트 health 요약"""
        return await self.generic_get(
            path="/v1/agents/health",
            user_info=user_info,
            **query_params
        )

    async def get_cluster_operations(self, cluster_name: str, user_info: dict, **query_params) -> dict:
        """클러스터별 작업 이력 조회"""
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(cluster_name)}/operations",
            user_info=user_info,
            **query_params
        )

    async def get_cluster_state_history(self, cluster_name: str, user_info: dict, **query_params) -> dict:
        """VM 클러스터 workflow state 변경 이력"""
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(cluster_name)}/state-history",
            user_info=user_info,
            **query_params
        )

    async def post_cluster_ssh_key(self, cluster_name: str, user_info: dict, data: Optional[dict] = None) -> dict:
        """VM 클러스터 SSH 키 발급/조회"""
        return await self.generic_post(
            path=f"/v1/clusters/{_seg(cluster_name)}/ssh-key",
            data=data or {},
            user_info=user_info
        )

    async def get_cluster_resource_kinds(self, cluster_name: str, user_info: dict) -> dict:
        """클러스터가 지원하는 K8s kind 목록"""
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(cluster_name)}/resource-kinds",
            user_info=user_info
        )

    # === observability ===

    async def get_observability_targets(self, cluster_name: str, user_info: dict) -> dict:
        """Prometheus scrape target 상태"""
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(cluster_name)}/observability/targets",
            user_info=user_info
        )

    async def get_observability_alerts(self, cluster_name: str, user_info: dict, **query_params) -> dict:
        """발생 중 alert 목록"""
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(cluster_name)}/observability/alerts",
            user_info=user_info,
            **query_params
        )

    async def get_observability_alert_silences(self, cluster_name: str, user_info: dict) -> dict:
        """alert silence 목록"""
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(cluster_name)}/observability/alert-silences",
            user_info=user_info
        )

    async def create_observability_alert_silence(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """alert silence 생성"""
        return await self.generic_post(
            path=f"/v1/clusters/{_seg(cluster_name)}/observability/alert-silences",
            data=data,
            user_info=user_info
        )

    async def delete_observability_alert_silence(self, cluster_name: str, silence_id: str, user_info: dict) -> dict:
        """alert silence 제거"""
        return await self.generic_delete(
            path=f"/v1/clusters/{_seg(cluster_name)}/observability/alert-silences/{_seg(silence_id)}",
            user_info=user_info
        )

    async def list_alert_rules(self, user_info: dict) -> dict:
        """alert rule 카탈로그 (전역)"""
        return await self.generic_get(
            path="/v1/observability/alert-rules",
            user_info=user_info
        )

    async def install_alert_rule(self, cluster_name: str, rule_set_id: str, user_info: dict) -> dict:
        """alert rule set 설치"""
        return await self.simple_post(
            path=f"/v1/clusters/{_seg(cluster_name)}/observability/alert-rules/{_seg(rule_set_id)}",
            user_info=user_info
        )

    async def install_all_alert_rules(self, cluster_name: str, user_info: dict) -> dict:
        """alert rule 전체 설치"""
        return await self.simple_post(
            path=f"/v1/clusters/{_seg(cluster_name)}/observability/alert-rules/install-all",
            user_info=user_info
        )

    async def delete_alert_rule(self, cluster_name: str, rule_set_id: str, user_info: dict) -> dict:
        """alert rule set 제거"""
        return await self.generic_delete(
            path=f"/v1/clusters/{_seg(cluster_name)}/observability/alert-rules/{_seg(rule_set_id)}",
            user_info=user_info
        )

    async def get_observability_dashboard(self, cluster_name: str, user_info: dict) -> dict:
        """클러스터 대시보드 메타"""
        return await self.generic_get(
            path=f"/v1/clusters/{_seg(cluster_name)}/observability/dashboard",
            user_info=user_info
        )

    async def list_standard_queries(self, user_info: dict) -> dict:
        """표준 query 카탈로그 (전역)"""
        return await self.generic_get(
            path="/v1/observability/standard-queries",
            user_info=user_info
        )

    async def get_observability_aggregate(self, user_info: dict, **query_params) -> dict:
        """다 클러스터 통합 지표"""
        return await self.generic_get(
            path="/v1/observability/aggregate",
            user_info=user_info,
            **query_params
        )

    # === standard metrics (Prometheus 표준 query — 시계열) ===

    async def get_standard_metric(
            self, cluster_name: str, metric: str, user_info: dict, **query_params
    ) -> dict:
        """표준 metric — metric 종류: node-cpu / node-memory / namespace-cpu / namespace-memory / pod-phases / top-cpu"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{_seg(cluster_name)}/metrics/standard/{_seg(metric)}",
            user_info=user_info,
            **query_params
        )

    # === workflow (RabbitMQ queues / DLQ) ===

    async def list_workflow_queues(self, user_info: dict, **query_params) -> dict:
        """워크플로우 큐 상태 조회"""
        return await self.generic_get(
            path="/v1/workflow/queues",
            user_info=user_info,
            **query_params
        )

    async def list_dead_letter_messages(self, user_info: dict, **query_params) -> dict:
        """DLQ 메시지 목록"""
        return await self.generic_get(
            path="/v1/workflow/dead-letter-messages",
            user_info=user_info,
            **query_params
        )

    async def operate_dead_letter_message(self, message_id: str, data: dict, user_info: dict) -> dict:
        """DLQ 메시지 처리 (재시도 / 폐기)"""
        return await self.generic_post(
            path=f"/v1/workflow/dead-letter-messages/{_seg(message_id)}/operations",
            data=data,
            user_info=user_info
        )

    # === admin: cleanup / drift / refresh ===

    async def admin_force_delete_cluster(self, cluster_name: str, user_info: dict) -> dict:
        """클러스터 강제 삭제 (admin)"""
        return await self.generic_delete(
            path=f"/v1/admin/clusters/{_seg(cluster_name)}/force",
            user_info=user_info
        )

    async def admin_delete_orphan_state(self, stack_name: str, user_info: dict) -> dict:
        """오펀 Pulumi state 삭제 (admin)"""
        return await self.generic_delete(
            path=f"/v1/admin/clusters/{_seg(stack_name)}/orphan-state",
            user_info=user_info
        )

    async def admin_get_cluster_drift(self, cluster_name: str, user_info: dict) -> dict:
        """클러스터 drift 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/admin/clusters/{_seg(cluster_name)}/drift",
            user_info=user_info
        )

    async def admin_refresh_cluster_state(self, cluster_name: str, user_info: dict) -> dict:
        """클러스터 state 강제 갱신"""
        return await self.simple_post(
            path=f"/v1/admin/clusters/{_seg(cluster_name)}/refresh-state",
            user_info=user_info
        )

    # === fleet upgrade ===

    async def fleet_upgrade_preview(self, user_info: dict, **query_params) -> dict:
        """fleet upgrade 미리보기"""
        return await self.generic_get(
            path="/v1/fleet/upgrade/preview",
            user_info=user_info,
            **query_params
        )

    async def fleet_upgrade_runs(self, user_info: dict, **query_params) -> dict:
        """fleet upgrade 실행 이력"""
        return await self.generic_get(
            path="/v1/fleet/upgrade/runs",
            user_info=user_info,
            **query_params
        )

    async def patch_cluster_upgrade_wave(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """클러스터 업그레이드 그룹 변경"""
        response = await self._make_request(
            "PATCH", f"/v1/clusters/{_seg(cluster_name)}/upgrade-wave", user_info=user_info, json=data
        )
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def trigger_cluster_upgrade(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """클러스터 업그레이드 실행"""
        return await self.generic_post(
            path=f"/v1/clusters/{_seg(cluster_name)}/upgrade",
            data=data,
            user_info=user_info
        )

    # === admin agent ===

    async def get_admin_agents(
            self,
            user_info: dict,
            status: Optional[str] = None,
            clusterName: Optional[str] = None,
            versionPrefix: Optional[str] = None,
            lastSeenOlderThanSec: Optional[int] = None,
            page: int = 0,
            size: int = 50,
    ) -> AnyCloudPagedResponse:
        """Admin fleet — cluster-agent 전체 목록 조회"""
        query_params: Dict[str, Any] = {"page": page, "size": size}
        if status:
            query_params["status"] = status
        if clusterName:
            query_params["clusterName"] = clusterName
        if versionPrefix:
            query_params["versionPrefix"] = versionPrefix
        if lastSeenOlderThanSec is not None:
            query_params["lastSeenOlderThanSec"] = lastSeenOlderThanSec

        response = await self.generic_get(
            path="/v1/admin/agents",
            user_info=user_info,
            **query_params,
        )
        data = response.get("data", {})
        items = data.get("items", []) if isinstance(data, dict) else []
        total = data.get("total", 0) if isinstance(data, dict) else 0
        return AnyCloudPagedResponse.create(
            data=items,
            total=total,
            page=page,
            size=size,
        )

    async def admin_agent_heartbeat_staleness(self, user_info: dict) -> dict:
        """에이전트 heartbeat 정체 상태 조회"""
        return await self.generic_get(
            path="/v1/admin/agent/heartbeat-staleness",
            user_info=user_info
        )

    async def admin_agent_heartbeat_staleness_run(self, data: dict, user_info: dict) -> dict:
        """heartbeat 정체 처리 실행"""
        return await self.generic_post(
            path="/v1/admin/agent/heartbeat-staleness",
            data=data,
            user_info=user_info
        )

    async def admin_agent_policy_preview(self, user_info: dict, **query_params) -> dict:
        """에이전트 정책 미리보기"""
        return await self.generic_get(
            path="/v1/admin/agent/policy/preview",
            user_info=user_info,
            **query_params
        )

    async def admin_agent_policy_audit(self, user_info: dict, **query_params) -> dict:
        """에이전트 정책 audit"""
        return await self.generic_get(
            path="/v1/admin/agent/policy/audit",
            user_info=user_info,
            **query_params
        )

    async def admin_put_cluster_agent_policy(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """클러스터 에이전트 정책 적용"""
        return await self.generic_put(
            path=f"/v1/admin/clusters/{_seg(cluster_name)}/agent-policy",
            data=data,
            user_info=user_info
        )

    async def admin_patch_cluster_agent_policy(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """클러스터 에이전트 정책 부분 변경"""
        response = await self._make_request(
            "PATCH", f"/v1/admin/clusters/{_seg(cluster_name)}/agent-policy", user_info=user_info, json=data
        )
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def admin_reinstall_cluster_agent(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """클러스터 에이전트 재설치"""
        return await self.generic_post(
            path=f"/v1/admin/clusters/{_seg(cluster_name)}/agent/reinstall",
            data=data,
            user_info=user_info
        )

    # === k8s pod logs (text/plain) + k8s resource 생성 ===

    async def get_pod_logs(
            self, cluster_name: str, namespace: str, pod_name: str, user_info: dict, **query_params
    ) -> str:
        """파드 로그 (text/plain)"""
        ns_path = namespace if namespace else "-"
        headers = self._get_headers(user_info)
        headers['Accept'] = 'text/plain'
        url = f"{self.base_url}/v1/clusters/{_seg(cluster_name)}/namespaces/{_seg(ns_path)}/pods/{_seg(pod_name)}/logs"
        try:
            response = await self.client.get(url, headers=headers, params=query_params)
        except httpx.TimeoutException:
            raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, detail="Any Cloud service timeout")
        except httpx.ConnectError:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Any Cloud service unavailable")
        if not (200 <= response.status_code < 300):
            logger.error(f"Any Cloud API error: {response.status_code} - {response.text}")
            raise HTTPException(response.status_code, detail=f"Any Cloud API request failed: {response.text}")
        return response.text

    async def create_kubernetes_resource(
            self, resource_type: str, clusterName: str, namespace: str, data: dict, user_info: dict
    ) -> dict:
        """쿠버네티스 리소스 생성 (apply JSON body)"""
        ns_path = namespace if namespace else "-"
        return await self.generic_post(
            path=f"/v1/clusters/{_seg(clusterName)}/namespaces/{_seg(ns_path)}/{_seg(resource_type)}",
            data=data,
            user_info=user_info
        )


# 싱글톤 인스턴스
any_cloud_service = AnyCloudService()
