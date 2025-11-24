import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status, UploadFile
from app.config import settings
from app.schemas.dataset import (
    DatasetCreateRequest, DatasetReadSchema, DatasetListResponse,
    DatasetValidationResponse
)

logger = logging.getLogger(__name__)


class DatasetService:
    """데이터셋 관련 외부 API 서비스 (인증 포함)"""

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
                expires_in = token_data.get("expires_in", 1800)

                if access_token:
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
            if (not self.access_token or
                    not self.token_expires_at or
                    datetime.now() >= self.token_expires_at):
                logger.info("Token expired or missing, refreshing...")
                self.access_token = await self._authenticate()

            return self.access_token

    def _get_headers(self, user_info: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """요청 헤더 생성"""
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'AIPaaS-Gateway/1.0'
        }

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
        token = await self._get_valid_token()

        headers = self._get_headers(user_info)
        headers['Authorization'] = f"Bearer {token}"

        if 'headers' in kwargs:
            kwargs['headers'].update(headers)
        else:
            kwargs['headers'] = headers

        response = await getattr(self.client, method.lower())(url, **kwargs)

        # 토큰 만료 시 재시도
        if response.status_code == 401:
            logger.warning("Token expired during request, retrying with new token")
            self.access_token = None
            token = await self._get_valid_token()
            kwargs['headers']['Authorization'] = f"Bearer {token}"
            response = await getattr(self.client, method.lower())(url, **kwargs)

        return response

    async def get_datasets(
            self,
            page: Optional[int] = None,
            page_size: Optional[int] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> DatasetListResponse:
        """데이터셋 목록 조회"""
        try:
            url = f"{self.base_url}/datasets"
            params = {}

            # 페이지네이션 파라미터 추가 (둘 다 있거나 둘 다 없어야 함)
            if page is not None and page_size is not None:
                params["page"] = page
                params["page_size"] = page_size

            logger.info(f"Getting datasets from: {url}")
            logger.info(f"Parameters: {params}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                data = response.json()

                # 응답이 {"data": [...]} 형식인지 확인
                if isinstance(data, dict) and 'data' in data:
                    return DatasetListResponse(**data)
                else:
                    # 레거시 형식 지원
                    return DatasetListResponse(data=data if isinstance(data, list) else [])
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get datasets: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting datasets: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting datasets: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="External service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting datasets: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_dataset(
            self,
            dataset_id: int,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[DatasetReadSchema]:
        """특정 데이터셋 조회"""
        try:
            url = f"{self.base_url}/datasets/{dataset_id}"

            logger.info(f"Getting dataset from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            if response.status_code == 200:
                dataset_data = response.json()
                return DatasetReadSchema(**dataset_data)
            elif response.status_code == 404:
                return None
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get dataset: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting dataset {dataset_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting dataset {dataset_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def validate_dataset(
            self,
            file: UploadFile,
            user_info: Optional[Dict[str, str]] = None
    ) -> DatasetValidationResponse:
        """데이터셋 파일 유효성 검증"""
        try:
            url = f"{self.base_url}/datasets/validate"

            # 파일 데이터 읽기
            file_data = await file.read()

            # 파일 포인터 리셋 (이후 재사용을 위해)
            await file.seek(0)

            files = {
                "file": (file.filename, file_data, file.content_type or "application/zip")
            }

            logger.info(f"Validating dataset file at: {url}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, files=files
            )

            if response.status_code == 200:
                validation_data = response.json()
                return DatasetValidationResponse(**validation_data)
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to validate dataset: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout validating dataset: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error validating dataset: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def create_dataset(
            self,
            dataset_data: DatasetCreateRequest,
            file: UploadFile,
            user_info: Optional[Dict[str, str]] = None
    ) -> DatasetReadSchema:
        """데이터셋 생성"""
        try:
            url = f"{self.base_url}/datasets"

            # 파일 데이터 읽기
            file_data = await file.read()

            # multipart/form-data로 전송
            files = {
                "file": (file.filename, file_data, file.content_type or "application/zip")
            }

            data = {
                "name": dataset_data.name,
                "description": dataset_data.description
            }

            logger.info(f"Creating dataset at: {url}")
            logger.info(f"Dataset data: {data}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, data=data, files=files
            )

            if response.status_code in [200, 201]:
                dataset_response = response.json()
                return DatasetReadSchema(**dataset_response)
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to create dataset: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout creating dataset: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating dataset: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_datasets_by_ids(
            self,
            dataset_ids: List[int],
            user_info: Optional[Dict[str, str]] = None
    ) -> List[DatasetReadSchema]:
        """특정 ID 목록으로 데이터셋들 조회 (병렬 조회)"""
        try:
            if not dataset_ids:
                return []

            # 개별 데이터셋을 병렬로 조회
            tasks = [
                self.get_dataset(dataset_id, user_info)
                for dataset_id in dataset_ids
            ]

            # 병렬 실행
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 성공한 결과만 필터링
            datasets = []
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.warning(f"Failed to get dataset {dataset_ids[i]}: {result}")
                    continue
                if result is not None:
                    datasets.append(result)

            return datasets

        except Exception as e:
            logger.error(f"Error getting datasets by IDs {dataset_ids}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )


# 싱글톤 인스턴스
dataset_service = DatasetService()