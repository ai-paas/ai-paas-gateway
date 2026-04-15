import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)


class ModelImprovementService:
    """모델 최적화/경량화 외부 API 서비스 (ModelService 패턴)"""

    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                timeout=settings.PROXY_TIMEOUT,
                connect=settings.PROXY_CONNECT_TIMEOUT
            ),
            limits=httpx.Limits(
                max_keepalive_connections=settings.PROXY_MAX_KEEPALIVE_CONNECTIONS,
                max_connections=settings.PROXY_MAX_CONNECTIONS
            ),
            follow_redirects=True
        )
        self.base_url = f"{settings.PROXY_TARGET_BASE_URL}{settings.PROXY_TARGET_PATH_PREFIX}"

        self.auth_username = settings.EXTERNAL_API_USERNAME
        self.auth_password = settings.EXTERNAL_API_PASSWORD
        self.access_token = None
        self.token_expires_at = None
        self._auth_lock = asyncio.Lock()

    async def close(self):
        await self.client.aclose()

    async def _authenticate(self) -> str:
        try:
            auth_url = f"{settings.PROXY_TARGET_BASE_URL}/api/v1/authentications/token"
            auth_data = {"username": self.auth_username, "password": self.auth_password}
            headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
            response = await self.client.post(auth_url, data=auth_data, headers=headers)
            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 1800)
                if access_token:
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
                    return access_token
                raise ValueError("No access_token in response")
            raise HTTPException(status_code=response.status_code, detail=f"Authentication failed: {response.text}")
        except httpx.TimeoutException:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Authentication service timeout")
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Authentication failed: {str(e)}")

    async def _get_valid_token(self) -> str:
        async with self._auth_lock:
            if not self.access_token or not self.token_expires_at or datetime.now() >= self.token_expires_at:
                self.access_token = await self._authenticate()
            return self.access_token

    def _get_headers(self, user_info: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {'Accept': 'application/json', 'User-Agent': 'AIPaaS-Gateway/1.0'}
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

    async def _make_authenticated_request(self, method: str, url: str,
                                          user_info: Optional[Dict[str, str]] = None, **kwargs) -> httpx.Response:
        token = await self._get_valid_token()
        headers = self._get_headers(user_info)
        headers['Authorization'] = f"Bearer {token}"
        if 'headers' in kwargs:
            kwargs['headers'].update(headers)
        else:
            kwargs['headers'] = headers
        response = await getattr(self.client, method.lower())(url, **kwargs)
        if response.status_code == 401:
            self.access_token = None
            token = await self._get_valid_token()
            kwargs['headers']['Authorization'] = f"Bearer {token}"
            response = await getattr(self.client, method.lower())(url, **kwargs)
        return response

    async def submit_improvement(self, data: Dict[str, Any],
                                 user_info: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """모델 최적화/경량화 task 생성"""
        try:
            url = f"{self.base_url}/model-improvements"
            logger.info(f"Submitting model improvement to: {url}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, json=data
            )

            if response.status_code in [200, 201, 202]:
                return response.json()
            else:
                raise HTTPException(status_code=response.status_code,
                                    detail=f"Failed to submit improvement: {response.text}")
        except httpx.TimeoutException:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Improvement service timeout")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error submitting improvement: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")

    async def get_status(self, task_id: str,
                         user_info: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """task 상태 조회"""
        try:
            url = f"{self.base_url}/model-improvements/status"
            params = {"task_id": task_id}
            logger.info(f"Getting improvement status from: {url}, task_id={task_id}")

            response = await self._make_authenticated_request("GET", url, user_info=user_info, params=params)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
            else:
                raise HTTPException(status_code=response.status_code,
                                    detail=f"Failed to get status: {response.text}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting improvement status: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")

    async def get_task_types(self, category: Optional[str] = None,
                             user_info: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """task type 목록 조회"""
        try:
            url = f"{self.base_url}/model-improvements/task-types"
            params = {}
            if category:
                params["category"] = category
            logger.info(f"Getting task types from: {url}")

            response = await self._make_authenticated_request("GET", url, user_info=user_info, params=params)

            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(status_code=response.status_code,
                                    detail=f"Failed to get task types: {response.text}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting task types: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")


model_improvement_service = ModelImprovementService()
