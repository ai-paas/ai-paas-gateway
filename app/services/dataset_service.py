import httpx
import logging
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.config import settings
from app.schemas.dataset import (
    DatasetCreateRequest, DatasetUpdate, DatasetResponse,
    ExternalDatasetResponse
)

logger = logging.getLogger(__name__)


class DatasetService:
    """데이터셋 관련 외부 API 서비스 (인증 포함) - 사용자별 필터링 지원"""

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

    async def get_datasets(
            self,
            skip: int = 0,
            limit: int = 100,
            search: Optional[str] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> List[DatasetResponse]:
        """모든 데이터셋 목록 조회 (필터링용)"""
        try:
            url = f"{self.base_url}/datasets"
            params = {
                "skip": skip,
                "limit": limit
            }

            # 필터 파라미터 추가
            if search:
                params["search"] = search

            logger.info(f"Getting datasets from: {url}")
            logger.info(f"Parameters: {params}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                datasets_data = response.json()
                # 리스트가 아닌 경우 처리
                if isinstance(datasets_data, dict) and 'items' in datasets_data:
                    datasets_data = datasets_data['items']

                # DatasetResponse 객체 리스트로 변환
                datasets = []
                for dataset_dict in datasets_data:
                    try:
                        dataset = DatasetResponse(**dataset_dict)
                        datasets.append(dataset)
                    except Exception as e:
                        logger.warning(f"Failed to parse dataset: {e}")
                        # 파싱 실패한 데이터셋은 건너뛰고 계속
                        continue

                return datasets
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

    async def create_dataset(
            self,
            dataset_data: DatasetCreateRequest,
            file_data: Optional[bytes] = None,
            file_name: Optional[str] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> DatasetResponse:
        """데이터셋 생성"""
        try:
            url = f"{self.base_url}/datasets"

            # multipart/form-data로 전송
            files = []
            data = {
                "name": dataset_data.name,
                "description": dataset_data.description
            }

            if file_data and file_name:
                files.append(("file", (file_name, file_data, "application/octet-stream")))

            logger.info(f"Creating dataset at: {url}")
            logger.info(f"Dataset data: {data}")

            if files:
                # 파일이 있는 경우 multipart 전송
                response = await self._make_authenticated_request(
                    "POST", url, user_info=user_info, data=data, files=files
                )
            else:
                # 파일이 없는 경우 JSON 전송
                response = await self._make_authenticated_request(
                    "POST", url, user_info=user_info, json=data,
                    headers={'Content-Type': 'application/json'}
                )

            if response.status_code in [200, 201]:
                dataset_data = response.json()
                return DatasetResponse(**dataset_data)
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

    async def update_dataset(
            self,
            dataset_id: int,
            dataset_data: DatasetUpdate,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[DatasetResponse]:
        """데이터셋 수정"""
        try:
            url = f"{self.base_url}/datasets/{dataset_id}"

            # None이 아닌 필드만 전송
            update_data = dataset_data.model_dump(exclude_unset=True, exclude_none=True)

            logger.info(f"Updating dataset at: {url}")
            logger.info(f"Update data: {update_data}")

            response = await self._make_authenticated_request(
                "PUT", url, user_info=user_info, json=update_data,
                headers={'Content-Type': 'application/json'}
            )

            if response.status_code == 200:
                dataset_data = response.json()
                return DatasetResponse(**dataset_data)
            elif response.status_code == 404:
                return None
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to update dataset: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout updating dataset {dataset_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating dataset {dataset_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def delete_dataset(
            self,
            dataset_id: int,
            user_info: Optional[Dict[str, str]] = None
    ) -> bool:
        """데이터셋 삭제"""
        try:
            url = f"{self.base_url}/datasets/{dataset_id}"

            logger.info(f"Deleting dataset at: {url}")

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
                    detail=f"Failed to delete dataset: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout deleting dataset {dataset_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting dataset {dataset_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_datasets_by_ids(
            self,
            dataset_ids: List[int],
            user_info: Optional[Dict[str, str]] = None
    ) -> List[DatasetResponse]:
        """특정 ID 목록으로 데이터셋들 조회 (배치 조회 최적화)"""
        try:
            if not dataset_ids:
                return []

            # 개별 데이터셋을 병렬로 조회
            tasks = []
            for dataset_id in dataset_ids:
                task = self.get_dataset(dataset_id, user_info)
                tasks.append(task)

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

    async def get_dataset(
            self,
            dataset_id: int,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[DatasetResponse]:
        """특정 데이터셋 조회"""
        try:
            url = f"{self.base_url}/datasets/{dataset_id}"

            logger.info(f"Getting dataset from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            if response.status_code == 200:
                dataset_data = response.json()
                return DatasetResponse(**dataset_data)
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

# 싱글톤 인스턴스
dataset_service = DatasetService()