import httpx
import logging
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.config import settings
from app.schemas.model import (
    ModelCreateRequest, ModelUpdate, ModelResponse,
    ExternalModelResponse, ModelCreateResponse
)

logger = logging.getLogger(__name__)


class ModelService:
    """모델 관련 외부 API 서비스 (인증 포함) - 사용자별 필터링 지원"""

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

        # 인증 관련 설정
        self.auth_username = settings.EXTERNAL_API_USERNAME
        self.auth_password = settings.EXTERNAL_API_PASSWORD
        self.access_token = None
        self.token_expires_at = None
        self._auth_lock = asyncio.Lock()

    async def close(self):
        """HTTP 클라이언트 종료"""
        await self.client.aclose()

    async def _authenticate(self) -> str:
        """외부 API 인증 토큰 획득"""
        try:
            auth_url = f"{settings.PROXY_TARGET_BASE_URL}/api/v1/authentications/token"

            # OAuth2 password flow를 위한 form data
            auth_data = {
                "username": self.auth_username,
                "password": self.auth_password
            }

            headers = {
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json"
            }

            logger.info(f"Authenticating with external API at: {auth_url}")

            response = await self.client.post(
                auth_url,
                data=auth_data,
                headers=headers
            )

            if response.status_code == 200:
                token_data = response.json()
                access_token = token_data.get("access_token")
                expires_in = token_data.get("expires_in", 1800)  # 기본 30분

                if access_token:
                    # 토큰 만료 시간 설정 (여유 시간 5분 차감)
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
                    logger.info("Successfully authenticated with external API")
                    return access_token
                else:
                    raise ValueError("No access_token in response")
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Authentication failed: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout during authentication: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Authentication service timeout"
            )
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Authentication failed: {str(e)}"
            )

    async def _get_valid_token(self) -> str:
        """유효한 인증 토큰 반환 (필요시 갱신)"""
        async with self._auth_lock:
            # 토큰이 없거나 만료된 경우 새로 발급
            if (not self.access_token or
                    not self.token_expires_at or
                    datetime.now() >= self.token_expires_at):
                logger.info("Token expired or missing, refreshing...")
                self.access_token = await self._authenticate()

            return self.access_token

    def _get_headers(self, user_info: Optional[Dict[str, str]] = None, include_auth: bool = True) -> Dict[str, str]:
        """요청 헤더 생성"""
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'AIPaaS-Gateway/1.0'
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

    async def _make_authenticated_request(
            self,
            method: str,
            url: str,
            user_info: Optional[Dict[str, str]] = None,
            **kwargs
    ) -> httpx.Response:
        """인증된 요청 실행"""
        # 유효한 토큰 획득
        token = await self._get_valid_token()

        # 헤더 설정
        headers = self._get_headers(user_info)
        headers['Authorization'] = f"Bearer {token}"

        # 기존 헤더와 병합
        if 'headers' in kwargs:
            kwargs['headers'].update(headers)
        else:
            kwargs['headers'] = headers

        # 요청 실행
        response = await getattr(self.client, method.lower())(url, **kwargs)

        # 토큰이 만료된 경우 재시도
        if response.status_code == 401:
            logger.warning("Token expired during request, retrying with new token")
            # 토큰 강제 갱신
            self.access_token = None
            token = await self._get_valid_token()
            kwargs['headers']['Authorization'] = f"Bearer {token}"
            response = await getattr(self.client, method.lower())(url, **kwargs)

        return response

    async def get_models(
            self,
            skip: int = 0,
            limit: int = 100,
            provider_id: Optional[int] = None,
            type_id: Optional[int] = None,
            format_id: Optional[int] = None,
            search: Optional[str] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> List[ModelResponse]:
        """모든 모델 목록 조회 (필터링용)"""
        try:
            url = f"{self.base_url}/models"
            params = {
                "skip": skip,
                "limit": limit
            }

            # 필터 파라미터 추가
            if provider_id:
                params["provider_id"] = provider_id
            if type_id:
                params["type_id"] = type_id
            if format_id:
                params["format_id"] = format_id
            if search:
                params["search"] = search

            logger.info(f"Getting models from: {url}")
            logger.info(f"Parameters: {params}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                models_data = response.json()
                # 리스트가 아닌 경우 처리
                if isinstance(models_data, dict) and 'items' in models_data:
                    models_data = models_data['items']

                # ModelResponse 객체 리스트로 변환
                models = []
                for model_dict in models_data:
                    try:
                        model = ModelResponse(**model_dict)
                        models.append(model)
                    except Exception as e:
                        logger.warning(f"Failed to parse model: {e}")
                        # 파싱 실패한 모델은 건너뛰고 계속
                        continue

                return models
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get models: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting models: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting models: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="External service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting models: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_models_by_ids(
            self,
            model_ids: List[int],
            user_info: Optional[Dict[str, str]] = None
    ) -> List[ModelResponse]:
        """특정 ID 목록으로 모델들 조회 (배치 조회 최적화)"""
        try:
            if not model_ids:
                return []

            # 개별 모델을 병렬로 조회
            tasks = []
            for model_id in model_ids:
                task = self.get_model(model_id, user_info)
                tasks.append(task)

            # 병렬 실행
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 성공한 결과만 필터링
            models = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to get model {model_ids[i]}: {result}")
                    continue
                if result is not None:
                    models.append(result)

            return models

        except Exception as e:
            logger.error(f"Error getting models by IDs {model_ids}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_model(
            self,
            model_id: int,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[ModelResponse]:
        """특정 모델 조회"""
        try:
            url = f"{self.base_url}/models/{model_id}"

            logger.info(f"Getting model from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            if response.status_code == 200:
                model_data = response.json()
                return ModelResponse(**model_data)
            elif response.status_code == 404:
                return None
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get model: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def create_model(
            self,
            model_data: ModelCreateRequest,
            file_data: Optional[bytes] = None,
            file_name: Optional[str] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> ModelCreateResponse:
        """모델 생성"""
        try:
            url = f"{self.base_url}/models"

            # multipart/form-data로 전송할 데이터 준비
            data = {
                "name": model_data.name,
                "repo_id": model_data.repo_id,
                "provider_id": str(model_data.provider_id),
                "type_id": str(model_data.type_id),
                "format_id": str(model_data.format_id)
            }

            # Optional 필드 추가
            if model_data.description:
                data["description"] = model_data.description
            if model_data.parent_model_id:
                data["parent_model_id"] = str(model_data.parent_model_id)
            if model_data.task:
                data["task"] = model_data.task
            if model_data.parameter:
                data["parameter"] = model_data.parameter
            if model_data.sample_code:
                data["sample_code"] = model_data.sample_code
            if model_data.model_registry_schema:
                data["model_registry_schema"] = model_data.model_registry_schema

            files = []
            if file_data and file_name:
                files.append(("file", (file_name, file_data, "application/octet-stream")))

            logger.info(f"Creating model at: {url}")
            logger.info(f"Model data: {data}")

            if files:
                # 파일이 있는 경우 multipart 전송
                response = await self._make_authenticated_request(
                    "POST", url, user_info=user_info, data=data, files=files
                )
            else:
                # 파일이 없는 경우에도 multipart로 전송 (API 스펙에 따라)
                response = await self._make_authenticated_request(
                    "POST", url, user_info=user_info, data=data
                )

            if response.status_code in [200, 201]:
                model_data = response.json()
                return ModelCreateResponse(**model_data)
            else:
                error_detail = response.text
                logger.error(f"Model creation failed: {error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to create model: {error_detail}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout creating model: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating model: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def update_model(
            self,
            model_id: int,
            model_data: ModelUpdate,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[ModelResponse]:
        """모델 수정"""
        try:
            url = f"{self.base_url}/models/{model_id}"

            # None이 아닌 필드만 전송
            update_data = model_data.model_dump(exclude_unset=True, exclude_none=True)

            logger.info(f"Updating model at: {url}")
            logger.info(f"Update data: {update_data}")

            response = await self._make_authenticated_request(
                "PUT", url, user_info=user_info, json=update_data,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200:
                model_data = response.json()
                return ModelResponse(**model_data)
            elif response.status_code == 404:
                return None
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to update model: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout updating model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def delete_model(
            self,
            model_id: int,
            user_info: Optional[Dict[str, str]] = None
    ) -> bool:
        """모델 삭제"""
        try:
            url = f"{self.base_url}/models/{model_id}"

            logger.info(f"Deleting model at: {url}")

            response = await self._make_authenticated_request(
                "DELETE", url, user_info=user_info
            )

            if response.status_code in [200, 204]:
                return True
            elif response.status_code == 404:
                return False
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to delete model: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout deleting model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def test_model(
            self,
            model_id: int,
            input_data: Dict[str, Any],
            parameters: Optional[Dict[str, Any]] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """모델 테스트 실행"""
        try:
            url = f"{self.base_url}/models/{model_id}/test"

            test_data = {
                "model_id": model_id,
                "input_data": input_data
            }
            if parameters:
                test_data["parameters"] = parameters

            logger.info(f"Testing model at: {url}")
            logger.info(f"Test data: {test_data}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, json=test_data,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200:
                return response.json()
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to test model: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout testing model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error testing model {model_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_model_types(
            self,
            user_info: Optional[Dict[str, str]] = None,
            type_name: Optional[str] = None
    ):
        """모델 타입 목록 조회"""
        try:
            url = f"{self.base_url}/models/types"
            params = {}

            if type_name:
                params["type_name"] = type_name

            logger.info(f"Getting model types from: {url}")
            logger.info(f"Parameters: {params}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404 and type_name:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Model type '{type_name}' not found"
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get model types: {response.text}"
                )

        except HTTPException:
            raise
        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting model types: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except Exception as e:
            logger.error(f"Error getting model types: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_model_providers(
            self,
            user_info: Optional[Dict[str, str]] = None,
            provider_name: Optional[str] = None
    ):
        """모델 제공자 목록 조회"""
        try:
            url = f"{self.base_url}/models/providers"
            params = {}

            if provider_name:
                params["provider_name"] = provider_name

            logger.info(f"Getting model providers from: {url}")
            logger.info(f"Parameters: {params}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404 and provider_name:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Model provider '{provider_name}' not found"
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get model providers: {response.text}"
                )

        except HTTPException:
            raise
        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting model providers: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except Exception as e:
            logger.error(f"Error getting model providers: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_model_formats(
            self,
            user_info: Optional[Dict[str, str]] = None,
            format_name: Optional[str] = None
    ):
        """모델 포맷 목록 조회"""
        try:
            url = f"{self.base_url}/models/formats"
            params = {}

            if format_name:
                params["format_name"] = format_name

            logger.info(f"Getting model formats from: {url}")
            logger.info(f"Parameters: {params}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404 and format_name:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Model format '{format_name}' not found"
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get model formats: {response.text}"
                )

        except HTTPException:
            raise
        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting model formats: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except Exception as e:
            logger.error(f"Error getting model formats: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )


# 싱글톤 인스턴스
model_service = ModelService()