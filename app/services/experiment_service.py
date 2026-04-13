import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)


class ExperimentService:
    """학습 실험 관련 외부 API 서비스 (ModelService 패턴)"""

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

    async def list_experiments(self, skip: int = 0, limit: int = 100,
                               user_info: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """실험 목록 조회"""
        try:
            url = f"{self.base_url}/experiments"
            # 프론트 skip/limit → MLOps page/page_size 변환
            page = (skip // limit) + 1 if limit > 0 else 1
            params = {"page": page, "page_size": limit}

            logger.info(f"Listing experiments from: {url}, params={params}")

            response = await self._make_authenticated_request("GET", url, user_info=user_info, params=params)

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return data
                elif isinstance(data, dict) and 'items' in data:
                    return data['items']
                return data if isinstance(data, list) else [data]
            else:
                raise HTTPException(status_code=response.status_code,
                                    detail=f"Failed to list experiments: {response.text}")
        except httpx.TimeoutException:
            raise HTTPException(status_code=status.HTTP_504_GATEWAY_TIMEOUT, detail="Experiment service timeout")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error listing experiments: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")

    async def get_experiment(self, experiment_id: int,
                             user_info: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """실험 상세 조회"""
        try:
            url = f"{self.base_url}/experiments/{experiment_id}"
            logger.info(f"Getting experiment from: {url}")

            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Experiment not found")
            else:
                raise HTTPException(status_code=response.status_code,
                                    detail=f"Failed to get experiment: {response.text}")
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting experiment {experiment_id}: {str(e)}")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Internal error: {str(e)}")


experiment_service = ExperimentService()
