import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.config import settings

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

    async def get_clusters(self, user_info: dict) -> dict:
        """
        클러스터 목록 조회 전용 메소드
        """
        return await self.generic_get(
            path="/system/clusters",  # 고정된 경로
            user_info=user_info
        )

    async def check_cluster_exists(self, cluster_id: str, user_info: dict) -> dict:
        """
        클러스터 존재 여부 확인 전용 메소드
        """
        return await self.generic_get(
            path="/system/cluster/exists",  # 고정된 경로
            user_info=user_info,
            _clusterId=cluster_id  # 쿼리 파라미터로 전달
        )

    async def get_cluster_detail(self, cluster_id: str, user_info: dict) -> dict:
        """
        클러스터 상세 조회 전용 메소드
        """
        return await self.generic_get_unwrapped(
            path=f"/system/cluster/{cluster_id}",  # 클러스터 ID가 포함된 경로
            user_info=user_info
        )

    async def get_helm_repos(self, user_info: dict) -> dict:
        """
        헬름 저장소 목록 조회 전용 메소드
        """
        return await self.generic_get(
            path="/helm-repos",  # 고정된 경로
            user_info=user_info
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

    async def generic_put(
            self,
            path: str,
            data: Dict[str, Any],
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """범용 PUT 요청"""
        return await self._make_request(
            "PUT", path, user_info=user_info, json=data, params=query_params
        )

    async def generic_delete(
            self,
            path: str,
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """범용 DELETE 요청"""
        return await self._make_request(
            "DELETE", path, user_info=user_info, params=query_params
        )

    async def generic_post(
            self,
            path: str,
            data: Dict[str, Any],
            user_info: Optional[Dict[str, str]] = None,
            **query_params
    ) -> Dict[str, Any]:
        """범용 POST 요청 (동적 엔드포인트 지원)"""
        return await self._make_request(
            "POST", path, user_info=user_info, json=data, params=query_params
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


# 싱글톤 인스턴스
any_cloud_service = AnyCloudService()