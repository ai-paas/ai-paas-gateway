import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import httpx
from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)


class PipelineService:
    """파이프라인 관련 외부 API 서비스 (ModelService 패턴)"""

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

    async def submit_training(self, data: Dict[str, Any],
                              user_info: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """학습 파이프라인 제출"""
        try:
            url = f"{self.base_url}/pipeline/training"
            logger.info(f"Submitting training pipeline to: {url}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, json=data
            )

            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(status_code=response.status_code,
                                    detail=f"Failed to submit training: {response.text}")
        except httpx.TimeoutException:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Training service timeout")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error submitting training: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")

    async def register_model(self, data: Dict[str, Any],
                             user_info: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """모델 등록 파이프라인 제출"""
        try:
            url = f"{self.base_url}/pipeline/model/registration"
            logger.info(f"Submitting model registration to: {url}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, json=data
            )

            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(status_code=response.status_code,
                                    detail=f"Failed to register model: {response.text}")
        except httpx.TimeoutException:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Registration service timeout")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error registering model: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")

    async def get_training_status(self, experiment_id: int,
                                  user_info: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """학습 상태 조회 (deprecated - experiments API 사용 권장)"""
        try:
            url = f"{self.base_url}/pipeline/training/{experiment_id}/status"
            logger.info(f"Getting training status from: {url}")

            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
            else:
                raise HTTPException(status_code=response.status_code,
                                    detail=f"Failed to get training status: {response.text}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting training status: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")


pipeline_service = PipelineService()
