from http.client import responses

import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.config import settings
from app.schemas.any_cloud import AnyCloudPagedResponse

logger = logging.getLogger(__name__)


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
                path=f"/v1/clusters/{cluster_id}",
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
            path=f"/v1/clusters/{cluster_id}",
            user_info=user_info
        )

    async def get_cluster_test_connection(self, cluster_id: str, user_info: dict) -> dict:
        """클러스터 연결 상태 확인"""
        return await self.simple_post(
            path=f"/v1/clusters/{cluster_id}/connectivity-checks",
            user_info=user_info
        )

    async def cluster_refresh(self, cluster_id: str, user_info: dict) -> dict:
        """클러스터 상태 강제 갱신"""
        return await self.generic_post(
            path=f"/v1/clusters/{cluster_id}/operations",
            data={"type": "refreshStatus"},
            user_info=user_info
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
                path=f"/v1/helm-repos/{helm_repo_name}",
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
            path=f"/v1/helm-repos/{helm_repo_name}",
            user_info=user_info
        )

    async def get_prometheus_query(
            self,
            cluster_name: str,
            query_params: dict,
            user_info: dict
    ) -> dict:
        """Prometheus instant query"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{cluster_name}/metrics/query",
            user_info=user_info,
            **query_params
        )

    async def get_prometheus_query_range(
            self,
            cluster_name: str,
            query_params: dict,
            user_info: dict
    ) -> dict:
        """Prometheus range query"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{cluster_name}/metrics/query_range",
            user_info=user_info,
            **query_params
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
            path=f"/v1/clusters/{clusterName}/namespaces/{ns_path}/{resource_type}",
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
            path=f"/v1/clusters/{clusterName}/namespaces/{ns_path}/{resource_type}/{resource_name}",
            user_info=user_info
        )

    async def delete_kubernetes_resource(self, resource_type: str, resource_name: str, clusterName: str, namespace: str, user_info: dict) -> dict:
        """쿠버네티스 리소스 삭제"""
        ns_path = namespace if namespace else "-"
        return await self.generic_delete(
            path=f"/v1/clusters/{clusterName}/namespaces/{ns_path}/{resource_type}/{resource_name}",
            user_info=user_info
        )

    async def get_kubernetes_test(self, clusterName: str, user_info: dict) -> dict:
        """클러스터 연결 상태 확인"""
        return await self.simple_post(
            path=f"/v1/clusters/{clusterName}/connectivity-checks",
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
            "PATCH", f"/v1/clusters/{cluster_id}", user_info=user_info, json=data
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
            path=f"/v1/clusters/{cluster_id}",
            user_info=user_info
        )

    async def delete_helm_repo(self, helm_repo_name: str, user_info: dict) -> dict:
        """헬름 저장소 삭제"""
        return await self.generic_delete(
            path=f"/v1/helm-repos/{helm_repo_name}",
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
        response = await self.generic_get(
            path=f"/v1/clusters/{clusterId}/helm-releases",
            namespace=namespace,
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
            path=f"/v1/helm-repos/{repoName}/charts",
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
            path=f"/v1/helm-repos/{repoName}/charts/{chartName}",
            user_info=user_info,
            **params
        )

    async def get_catalog_readme(self, repoName: str, chartName: str, version: Optional[str], user_info: dict) -> dict:
        """차트 README 조회"""
        params: Dict[str, Any] = {}
        if version:
            params["version"] = version
        return await self.generic_get_unwrapped(
            path=f"/v1/helm-repos/{repoName}/charts/{chartName}/readme",
            user_info=user_info,
            **params
        )

    async def get_catalog_status(self, repoName: str, chartName: str, releaseName: str, clusterId: str, namespace: str, user_info: dict) -> dict:
        """릴리즈 상태 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{clusterId}/helm-releases/{releaseName}",
            namespace=namespace,
            user_info=user_info
        )

    async def get_catalog_values(self, repoName: str, chartName: str, version: Optional[str], user_info: dict) -> dict:
        """차트 values 조회"""
        params: Dict[str, Any] = {}
        if version:
            params["version"] = version
        return await self.generic_get_unwrapped(
            path=f"/v1/helm-repos/{repoName}/charts/{chartName}/values",
            user_info=user_info,
            **params
        )

    async def get_catalog_resources(self, clusterId: str, namespace: str, releaseName: str, user_info: dict) -> dict:
        """릴리즈 리소스 목록 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{clusterId}/helm-releases/{releaseName}/resources",
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
            path=f"/v1/clusters/{clusterId}/helm-releases",
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
            path=f"/v1/operations/{operation_id}",
            user_info=user_info
        )

    async def cancel_operation(self, operation_id: str, user_info: dict) -> dict:
        """진행 중 작업 취소"""
        return await self.simple_post(
            path=f"/v1/operations/{operation_id}/cancel",
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
            path=f"/v1/providers/{provider}/regions",
            user_info=user_info
        )

    async def get_provider_specs(self, provider: str, user_info: dict, **query_params) -> dict:
        """CSP 별 VM spec 목록 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/providers/{provider}/specs",
            user_info=user_info,
            **query_params
        )

    async def get_provider_config_schema(self, provider: str, user_info: dict) -> dict:
        """CSP 별 클러스터 설정 스키마 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/providers/{provider}/config-schema",
            user_info=user_info
        )

    async def get_provider_images(self, provider: str, user_info: dict, **query_params) -> dict:
        """CSP 별 OS 이미지 목록 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/providers/{provider}/images",
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
            path=f"/v1/credentials/{credential_id}",
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
            path=f"/v1/credentials/{credential_id}",
            user_info=user_info
        )

    async def import_kubeconfig(
            self,
            file_content: bytes,
            file_name: str,
            cluster_name: str,
            provider: str,
            user_info: dict,
            cluster_type: Optional[str] = None,
            description: Optional[str] = None,
            validate: bool = True,
            strict: bool = False
    ) -> dict:
        """kubeconfig 파일 업로드로 클러스터 등록"""
        form_data: Dict[str, Any] = {
            "clusterName": cluster_name,
            "provider": provider,
            "validate": str(validate).lower(),
            "strict": str(strict).lower()
        }
        if cluster_type:
            form_data["clusterType"] = cluster_type
        if description:
            form_data["description"] = description

        headers = self._get_headers(user_info)
        # Content-Type 은 httpx 가 boundary 와 함께 자동 설정
        headers.pop('Content-Type', None)

        url = f"{self.base_url}/v1/clusters/importKubeconfig"
        files = {"kubeconfigFile": (file_name, file_content, "application/yaml")}

        try:
            response = await self.client.post(url, headers=headers, data=form_data, files=files)
        except httpx.TimeoutException:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Any Cloud service timeout"
            )
        except httpx.ConnectError:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Any Cloud service unavailable"
            )

        if not (200 <= response.status_code < 300):
            logger.error(f"Any Cloud API error: {response.status_code} - {response.text}")
            raise HTTPException(
                status_code=response.status_code,
                detail=f"Any Cloud API request failed: {response.text}"
            )

        if response.status_code == 204 or not response.content:
            return None
        body = response.json()
        if isinstance(body, dict) and "data" in body and "success" in body:
            return body["data"]
        return body

    async def list_addon_catalog(self, user_info: dict) -> dict:
        """설치 가능한 애드온 목록 조회"""
        return await self.generic_get(
            path="/v1/addons",
            user_info=user_info
        )

    async def list_cluster_addons(self, cluster_name: str, user_info: dict) -> dict:
        """클러스터에 설치된 애드온 목록 조회"""
        return await self.generic_get(
            path=f"/v1/clusters/{cluster_name}/addons",
            user_info=user_info
        )

    async def get_cluster_addon(self, cluster_name: str, addon_id: str, user_info: dict) -> dict:
        """애드온 단건 조회"""
        return await self.generic_get_unwrapped(
            path=f"/v1/clusters/{cluster_name}/addons/{addon_id}",
            user_info=user_info
        )

    async def install_cluster_addon(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """애드온 설치"""
        return await self.generic_post(
            path=f"/v1/clusters/{cluster_name}/addons",
            data=data,
            user_info=user_info
        )

    async def uninstall_cluster_addon(self, cluster_name: str, addon_id: str, user_info: dict) -> dict:
        """애드온 제거"""
        return await self.generic_delete(
            path=f"/v1/clusters/{cluster_name}/addons/{addon_id}",
            user_info=user_info
        )

    async def retry_cluster_addon(self, cluster_name: str, addon_id: str, user_info: dict) -> dict:
        """실패한 애드온 재시도"""
        return await self.simple_post(
            path=f"/v1/clusters/{cluster_name}/addons/{addon_id}/retry",
            user_info=user_info
        )

    async def install_helm_release(self, cluster_name: str, data: dict, user_info: dict) -> dict:
        """Helm 릴리즈 설치"""
        return await self.generic_post(
            path=f"/v1/clusters/{cluster_name}/helm-releases",
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


# 싱글톤 인스턴스
any_cloud_service = AnyCloudService()
