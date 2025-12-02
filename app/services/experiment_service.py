import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import HTTPException, status
from app.config import settings
from app.schemas.experiment import ExperimentReadSchema

logger = logging.getLogger(__name__)


class ExperimentService:
    """실험 관련 외부 API 서비스"""

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
        """인증 토큰 획득"""
        try:
            auth_url = f"{settings.PROXY_TARGET_BASE_URL}/api/v1/authentications/token"
            response = await self.client.post(
                auth_url,
                data={"username": self.auth_username, "password": self.auth_password},
                headers={"Content-Type": "application/x-www-form-urlencoded"}
            )

            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 1800)
                if access_token:
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
                    return access_token
            raise HTTPException(status_code=response.status_code, detail="Authentication failed")
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            raise HTTPException(status_code=500, detail=f"Authentication failed: {str(e)}")

    async def _get_valid_token(self) -> str:
        async with self._auth_lock:
            if not self.access_token or not self.token_expires_at or datetime.now() >= self.token_expires_at:
                self.access_token = await self._authenticate()
            return self.access_token

    def _get_headers(self, user_info: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {'Accept': 'application/json'}
        if user_info:
            if user_info.get('member_id'):
                headers['X-User-ID'] = str(user_info['member_id'])
            if user_info.get('role'):
                headers['X-User-Role'] = str(user_info['role'])
            if user_info.get('name'):
                import base64
                headers['X-User-Name-B64'] = base64.b64encode(str(user_info['name']).encode()).decode()
        return headers

    async def _make_authenticated_request(
            self,
            method: str,
            url: str,
            user_info: Optional[Dict] = None,
            **kwargs
    ) -> httpx.Response:
        """인증된 요청 수행"""
        token = await self._get_valid_token()
        headers = self._get_headers(user_info)
        headers['Authorization'] = f"Bearer {token}"

        if 'headers' in kwargs:
            kwargs['headers'].update(headers)
        else:
            kwargs['headers'] = headers

        response = await getattr(self.client, method.lower())(url, **kwargs)

        # 401 에러 시 토큰 재발급 후 재시도
        if response.status_code == 401:
            self.access_token = None
            token = await self._get_valid_token()
            kwargs['headers']['Authorization'] = f"Bearer {token}"
            response = await getattr(self.client, method.lower())(url, **kwargs)

        return response

    # ===== 실험 API =====

    async def get_experiment(
            self,
            experiment_id: int,
            user_info: Optional[Dict] = None
    ) -> ExperimentReadSchema:
        """실험 상세정보 조회"""
        try:
            url = f"{self.base_url}/experiments/{experiment_id}"

            logger.info(f"Getting experiment from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            if response.status_code == 200:
                data = response.json()
                return ExperimentReadSchema(**data)
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Experiment {experiment_id} not found"
                )
            else:
                logger.error(f"Failed to get experiment: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get experiment: {response.text}"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting experiment: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def update_experiment(
            self,
            experiment_id: int,
            name: Optional[str] = None,
            description: Optional[str] = None,
            user_info: Optional[Dict] = None
    ) -> ExperimentReadSchema:
        """실험 정보 수정"""
        try:
            url = f"{self.base_url}/experiments/{experiment_id}"

            update_data = {}
            if name is not None:
                update_data["name"] = name
            if description is not None:
                update_data["description"] = description

            logger.info(f"Updating experiment at: {url}")
            logger.info(f"Update data: {update_data}")

            response = await self._make_authenticated_request(
                "PATCH", url, user_info=user_info, json=update_data
            )

            if response.status_code == 200:
                data = response.json()
                return ExperimentReadSchema(**data)
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Experiment {experiment_id} not found"
                )
            else:
                logger.error(f"Failed to update experiment: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to update experiment: {response.text}"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating experiment: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def update_experiment_internal(
            self,
            experiment_id: int,
            status: Optional[str] = None,
            mlflow_run_id: Optional[str] = None,
            kubeflow_run_id: Optional[str] = None,
            user_info: Optional[Dict] = None
    ) -> ExperimentReadSchema:
        """실험 내부 정보 수정"""
        try:
            url = f"{self.base_url}/experiments/{experiment_id}/internal-access"

            update_data = {}
            if status is not None:
                update_data["status"] = status
            if mlflow_run_id is not None:
                update_data["mlflow_run_id"] = mlflow_run_id
            if kubeflow_run_id is not None:
                update_data["kubeflow_run_id"] = kubeflow_run_id

            logger.info(f"Updating experiment (internal) at: {url}")
            logger.info(f"Update data: {update_data}")

            response = await self._make_authenticated_request(
                "PATCH", url, user_info=user_info, json=update_data
            )

            if response.status_code == 200:
                data = response.json()
                return ExperimentReadSchema(**data)
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Experiment {experiment_id} not found"
                )
            else:
                logger.error(f"Failed to update experiment (internal): {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to update experiment: {response.text}"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating experiment (internal): {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_experiment(
            self,
            experiment_id: int,
            user_info: Optional[Dict] = None
    ) -> Dict[str, str]:
        """실험 삭제"""
        try:
            url = f"{self.base_url}/experiments/{experiment_id}"

            logger.info(f"Deleting experiment at: {url}")

            response = await self._make_authenticated_request(
                "DELETE", url, user_info=user_info
            )

            if response.status_code in [200, 204]:
                return {"message": f"Experiment {experiment_id} successfully deleted"}
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=404,
                    detail=f"Experiment {experiment_id} not found"
                )
            else:
                logger.error(f"Failed to delete experiment: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to delete experiment: {response.text}"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting experiment: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))


# 전역 서비스 인스턴스
experiment_service = ExperimentService()