import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from fastapi import HTTPException, status
from app.config import settings
from app.schemas.pipeline import (
    TrainingPipelineResponse,
    ModelRegistrationResponse,
    TrainingStatusResponse
)

logger = logging.getLogger(__name__)


class PipelineService:
    """파이프라인 관련 외부 API 서비스"""

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

    async def _make_authenticated_request(self, method: str, url: str, user_info: Optional[Dict] = None,
                                          **kwargs) -> httpx.Response:
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

    # ===== 학습 파이프라인 =====

    async def create_training_pipeline(
            self,
            model_id: int,
            dataset_id: int,
            training_params: Dict[str, Any],
            user_info: Optional[Dict] = None
    ) -> TrainingPipelineResponse:
        """학습 파이프라인 생성 및 실행"""
        try:
            url = f"{self.base_url}/pipeline/training"
            params = {
                "model_id": model_id,
                "dataset_id": dataset_id
            }

            logger.info(f"Creating training pipeline at: {url}")
            logger.info(f"Params: {params}")
            logger.info(f"Body: {training_params}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, params=params, json=training_params
            )

            if response.status_code in [200, 201]:
                data = response.json()
                return TrainingPipelineResponse(**data)
            else:
                logger.error(f"Training pipeline creation failed: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to create training pipeline: {response.text}"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating training pipeline: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def register_model(
            self,
            model_name: str,
            description: str,
            experiment_id: int,
            user_info: Optional[Dict] = None
    ) -> ModelRegistrationResponse:
        """학습 완료된 모델 등록"""
        try:
            url = f"{self.base_url}/pipeline/model/registration"
            params = {
                "model_name": model_name,
                "description": description,
                "experiment_id": experiment_id
            }

            logger.info(f"Registering model at: {url}")
            logger.info(f"Params: {params}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, params=params
            )

            if response.status_code in [200, 201]:
                data = response.json()
                return ModelRegistrationResponse(**data)
            else:
                logger.error(f"Model registration failed: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to register model: {response.text}"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error registering model: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_training_status(
            self,
            experiment_id: int,
            user_info: Optional[Dict] = None
    ) -> TrainingStatusResponse:
        """학습 상태 조회"""
        try:
            url = f"{self.base_url}/pipeline/training/{experiment_id}/status"

            logger.info(f"Getting training status from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            if response.status_code == 200:
                data = response.json()
                return TrainingStatusResponse(**data)
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Training status not found")
            else:
                logger.error(f"Failed to get training status: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get training status: {response.text}"
                )

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting training status: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))


pipeline_service = PipelineService()