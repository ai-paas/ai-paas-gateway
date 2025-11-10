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
        # 검색 처리
        filtered_data = data
        if search and search_fields:
            search_lower = search.lower()
            filtered_data = [
                item for item in data
                if any(
                    search_lower in str(item.get(field, '')).lower()
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

            if response.status_code == 200:
                response_data = response.json()
                # 응답을 data로 래핑
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
        """범용 GET 요청 (data 래핑 제거) - 단일 조회용"""
        response = await self._make_request(
            "GET", path, user_info=user_info, params=query_params
        )

        # data 필드가 있으면 data 내용만 반환, 없으면 전체 응답 반환
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def generic_get(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """범용 GET 요청 (동적 엔드포인트 지원) - 전체 조회용"""
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
        """범용 PUT 요청"""
        response = await self._make_request(
            "PUT", path, user_info=user_info, json=data, params=query_params
        )

        # data 필드가 있으면 data 내용만 반환, 없으면 전체 응답 반환
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def generic_delete(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """범용 DELETE 요청"""
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
        """범용 POST 요청 (동적 엔드포인트 지원)"""
        response = await self._make_request(
            "POST", path, user_info=user_info, json=data, params=query_params
        )
        # data 필드가 있으면 data 내용만 반환, 없으면 전체 응답 반환
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    async def simple_post(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """데이터 없는 단순 POST 요청 (트리거/액션용)"""
        response = await self._make_request(
            "POST", path, user_info=user_info, params=query_params
        )
        # data 필드가 있으면 data 내용만 반환, 없으면 전체 응답 반환
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
        """범용 POST 요청 (파일 업로드 지원)"""

        # 파일이 있으면 multipart/form-data로 전송
        if files or any(key == "valuesFile" for key in data.keys()):
            response = await self._make_multipart_request(
                "POST", path, data=data, files=files, user_info=user_info, params=query_params
            )
        else:
            response = await self._make_request(
                "POST", path, user_info=user_info, json=data, params=query_params
            )

        # data 필드가 있으면 data 내용만 반환, 없으면 전체 응답 반환
        if isinstance(response, dict) and "data" in response:
            return response["data"]
        return response

    # _make_multipart_request 메소드 추가 (없다면)
    async def _make_multipart_request(
            self,
            method: str,
            path: str,
            data: Optional[Dict[str, Any]] = None,
            files: Optional[Dict[str, Any]] = None,
            user_info: Optional[Dict[str, str]] = None,
            params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """멀티파트 요청을 위한 메소드"""

        headers = self._get_headers(user_info)
        # multipart 요청시 Content-Type 헤더 제거 (httpx가 자동 설정)
        headers.pop('Content-Type', None)

        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

        # form data와 files 구성
        form_data = {}
        file_data = {}

        if data:
            for key, value in data.items():
                if key == "valuesFile" and isinstance(value, str):
                    # base64 디코딩해서 파일로 전송
                    import base64
                    file_content = base64.b64decode(value)
                    file_data["valuesFile"] = ("values.yaml", file_content, "application/x-yaml")
                else:
                    form_data[key] = value

        if files:
            file_data.update(files)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(
                method=method,
                url=url,
                headers=headers,
                data=form_data,
                files=file_data,
                params=params
            )

            return self._handle_response(response)

    async def get_clusters(
            self,
            user_info: dict,
            page: int = 1,
            size: int = 20,
            search: Optional[str] = None
    ) -> AnyCloudPagedResponse:
        """클러스터 목록 조회 (페이징 적용)"""
        response = await self.generic_get(
            path="/system/clusters",
            user_info=user_info
        )

        # 응답에서 data 추출
        data = response.get("data", [])
        if isinstance(data, dict):
            data = data.get("clusters", [])

        # 클라이언트 사이드 페이징 적용
        return self._apply_client_side_pagination(
            data=data,
            page=page,
            size=size,
            search=search,
            search_fields=["clusterName", "clusterId", "clusterProvider", "clusterType"]
        )

    async def check_cluster_exists(self, cluster_id: str, user_info: dict) -> dict:
        """
        클러스터 존재 여부 확인 전용 메소드
        """
        return await self.generic_get(
            path="/system/cluster/exists",  # 고정된 경로
            user_info=user_info,
            clusterId=cluster_id  # 쿼리 파라미터로 전달
        )

    async def get_cluster_detail(self, cluster_id: str, user_info: dict) -> dict:
        """
        클러스터 상세 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/system/cluster/{cluster_id}",  # 클러스터 ID가 포함된 경로
            user_info=user_info
        )

    async def get_cluster_test_connection(self, cluster_id: str, user_info: dict) -> dict:
        """
        클러스터 연결 테스트 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/system/cluster/{cluster_id}/test-connection",  # 클러스터 ID가 포함된 경로
            user_info=user_info
        )

    async def cluster_refresh(self, cluster_id: str, user_info: dict) -> dict:
        """
        클러스터 상태 강제 업데이트 메소드
        """
        return await self.simple_post(
            path=f"/system/cluster/{cluster_id}/refresh",  # 클러스터 ID가 포함된 경로
            user_info=user_info
        )

    async def get_helm_repos(
            self,
            user_info: dict,
            page: int = 1,
            size: int = 20,
            search: Optional[str] = None
    ) -> AnyCloudPagedResponse:
        """헬름 저장소 목록 조회 (페이징 적용)"""
        response = await self.generic_get(
            path="/helm-repos",
            user_info=user_info
        )

        data = response.get("data", [])
        if isinstance(data, dict):
            data = data.get("repositories", [])

        return self._apply_client_side_pagination(
            data=data,
            page=page,
            size=size,
            search=search,
            search_fields=["name", "url"]
        )

    async def check_helm_repos_exists(self, helm_repo_name: str, user_info: dict) -> dict:
        """
        헬름 저장소 존재 여부 확인 전용 메소드
        """
        return await self.generic_get(
            path=f"/helm-repos/{helm_repo_name}/exists",  # 고정된 경로
            user_info=user_info
        )

    async def get_helm_repos_detail(self, helm_repo_name: str, user_info: dict) -> dict:
        """
        헬름 저장소 상세 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/helm-repos/{helm_repo_name}",  # 클러스터 ID가 포함된 경로
            user_info=user_info
        )

    async def get_monitoring_node(self, cluster_name: str, user_info: dict) -> dict:
        """
        클러스터 내 노드별 상태 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/monit/nodeStatus/{cluster_name}",
            user_info=user_info
        )

    async def get_monitoring_metric(self, cluster_name: str, type: str, key: str, filter: dict, user_info: dict) -> dict:
        """
        모니터링 메트릭 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/monit/resourceMonit/{cluster_name}/{type}/{key}",
            user_info=user_info,
            **filter  # filter dict를 **kwargs로 전개하여 쿼리 파라미터로 전달
        )

    async def get_kubernetes_resource(
            self,
            resource_type: str,
            clusterName: str,
            namespace: str,
            user_info: dict,
            page: int = 1,
            size: int = 20,
            search: Optional[str] = None
    ) -> AnyCloudPagedResponse:
        """쿠버네티스 특정 리소스 조회 (페이징 적용)"""
        response = await self.generic_get(
            path=f"/kubernetes/{resource_type}",
            clusterName=clusterName,
            namespace=namespace,
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
            search_fields=["name", "metadata.name"]
        )

    async def get_kubernetes_resource_name(self, resource_type: str, resource_name: str, clusterName: str, namespace: str, user_info: dict) -> dict:
        """
        쿠버네티스 특정 리소스 조회 전용 메소드
        """
        return await self.generic_get(
            path=f"/kubernetes/{resource_type}/{resource_name}",  # 고정된 경로
            clusterName=clusterName,
            namespace=namespace,
            user_info=user_info
        )

    async def delete_kubernetes_resource(self, resource_type: str, resource_name: str, clusterName: str, namespace: str, user_info: dict) -> dict:
        """
        쿠버네티스 특정 리소스 삭제 전용 메소드
        """
        return await self.generic_delete(
            path=f"/kubernetes/{resource_type}/{resource_name}",  # 고정된 경로
            clusterName=clusterName,
            namespace=namespace,
            user_info=user_info
        )

    async def get_kubernetes_test(self, clusterName: str, user_info: dict) -> dict:
        """
        클러스터 연결 상태를 테스트합니다.
        """
        return await self.generic_get(
            path="/kubernetes/test-connection",  # 고정된 경로
            clusterName=clusterName,
            user_info=user_info
        )

    async def create_cluster(self, data: dict, user_info: dict) -> dict:
        """
        클러스터 생성 전용 메소드
        """
        return await self.generic_post(
            path="/system/cluster",  # 고정된 경로
            data=data,
            user_info=user_info
        )

    async def update_cluster(self, data: dict, cluster_id: str, user_info: dict) -> dict:
        """
        클러스터 생성 전용 메소드
        """
        logger.info(f"Sending data to Any Cloud: {data}")  # 로그 추가
        return await self.generic_put(
            path=f"/system/cluster/{cluster_id}",  # 고정된 경로
            data=data,
            user_info=user_info
        )

    async def create_helm_repo(self, data: dict, user_info: dict) -> dict:
        """
        헬름 저장소 생성 전용 메소드
        """
        return await self.generic_post(
            path="/helm-repos",  # 고정된 경로

            data=data,
            user_info=user_info
        )

    async def delete_cluster(self, cluster_id: str, user_info: dict) -> dict:
        """
        클러스터 삭제 전용 메소드
        """
        return await self.generic_delete(
            path=f"/system/cluster/{cluster_id}",  # 클러스터 ID가 포함된 경로
            user_info=user_info
        )
    
    async def delete_helm_repo(self, helm_repo_name: str, user_info: dict) -> dict:
        """
        헬름 저장소 삭제 전용 메소드
        """
        return await self.generic_delete(
            path=f"/helm-repos/{helm_repo_name}",
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
        """Helm Release 목록 조회 (페이징 적용)"""
        response = await self.generic_get(
            path="/charts/releases",
            clusterId=clusterId,
            namespace=namespace,
            user_info=user_info
        )

        # 중첩된 data 구조 처리: {'data': {'data': {'releases': [...]}}}
        data = response.get("data", {})
        if isinstance(data, dict) and "data" in data:
            data = data.get("data", {})

        # releases 필드 추출
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
        """Helm 차트 목록 조회 (페이징 적용)"""
        response = await self.generic_get(
            path=f"/charts/{repoName}",
            repoName=repoName,
            user_info=user_info
        )

        # 중첩된 data 구조 처리: {'data': {'data': {'charts': [...]}}}
        data = response.get("data", {})
        if isinstance(data, dict) and "data" in data:
            data = data.get("data", {})

        # charts 필드 추출
        if isinstance(data, dict):
            data = data.get("charts", [])

        return self._apply_client_side_pagination(
            data=data,
            page=page,
            size=size,
            search=search,
            search_fields=["name", "description", "version", "appVersion"]
        )

    async def get_catalog_chart(self, repoName: str, chartName: str, version:str, user_info: dict) -> dict:
        """
        차트 상세 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/charts/{repoName}/{chartName}/detail",  # 고정된 경로
            repoName=repoName,
            chartName=chartName,
            version=version,
            user_info=user_info
        )

    async def get_catalog_readme(self, repoName: str, chartName: str, version: str, user_info: dict) -> dict:
        """
        차트 README.md 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/charts/{repoName}/{chartName}/readme",  # 고정된 경로
            repoName=repoName,
            chartName=chartName,
            version=version,
            user_info=user_info
        )

    async def get_catalog_status(self, repoName: str, chartName: str, releaseName: str, clusterId: str, namespace: str, user_info: dict) -> dict:
        """
        차트 status 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/charts/{repoName}/{chartName}/status",  # 고정된 경로
            repoName=repoName,
            chartName=chartName,
            releaseName=releaseName,
            clusterId=clusterId,
            namespace=namespace,
            user_info= user_info
        )

    async def get_catalog_values(self, repoName: str, chartName: str, version: str, user_info: dict) -> dict:
        """
        차트 values 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/charts/{repoName}/{chartName}/values",  # 고정된 경로
            repoName=repoName,
            chartName=chartName,
            version=version,
            user_info=user_info
        )

    async def get_catalog_resources(self, clusterId: str, namespace: str, releaseName: str, user_info: dict) -> dict:
        """
        releases resources 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/charts/releases/{releaseName}/resources",  # 고정된 경로
            clusterId=clusterId,
            namespace=namespace,
            releaseName=releaseName,
            user_info=user_info
        )

    # service.py - 서비스 메소드 수정
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
        """
        차트 배포 메소드
        """
        # 요청 데이터 구성
        deploy_data = {
            "releaseName": releaseName,
            "clusterId": clusterId,
            "namespace": namespace
        }

        # 선택적 필드 추가
        if version:
            deploy_data["version"] = version

        # valuesFile 처리 - 파일이 있으면 base64 인코딩 또는 텍스트로 전송
        if valuesFile:
            import base64
            deploy_data["valuesFile"] = base64.b64encode(valuesFile).decode('utf-8')

        return await self.generic_post_file(
            path=f"/charts/{repoName}/{chartName}/deploy",
            data=deploy_data,
            user_info=user_info
        )

# 싱글톤 인스턴스
any_cloud_service = AnyCloudService()