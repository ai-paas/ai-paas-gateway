import httpx
import logging
import json
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.config import settings
from app.schemas.service import (
    ExternalServiceResponse,
    ExternalServiceDetailResponse
)

logger = logging.getLogger(__name__)


class ServiceService:
    """서비스 관련 외부 API 서비스 (인증 포함)"""

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

    async def create_service(
            self,
            name: str,
            description: Optional[str] = None,
            tags: Optional[List[str]] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> ExternalServiceResponse:
        """서비스 생성"""
        try:
            url = f"{self.base_url}/services"

            payload = {
                "name": name
            }
            if description:
                payload["description"] = description
            if tags:
                payload["tags"] = tags

            logger.info(f"Creating service at: {url}")
            logger.info(f"Payload: {payload}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, json=payload
            )

            if response.status_code in [200, 201]:
                service_data = response.json()
                return ExternalServiceResponse(**service_data)
            else:
                error_detail = response.text
                logger.error(f"Service creation failed: {error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to create service: {error_detail}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout creating service: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating service: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_services(
            self,
            page: Optional[int] = None,
            page_size: Optional[int] = None,
            creator_id: Optional[int] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """서비스 목록 조회"""
        try:
            url = f"{self.base_url}/services"
            params = {}

            if page is not None:
                params["page"] = page
            if page_size is not None:
                params["page_size"] = page_size
            if creator_id is not None:
                params["creator_id"] = creator_id

            logger.info(f"Getting services from: {url}")
            logger.info(f"Parameters: {params}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                data = response.json()
                return data
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get services: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting services: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"Connection error getting services: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="External service unavailable"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting services: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_service(
            self,
            service_id: str,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[ExternalServiceDetailResponse]:
        """서비스 상세 조회"""
        try:
            url = f"{self.base_url}/services/{service_id}"

            logger.info(f"Getting service from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text[:500]}")  # 처음 500자만

            if response.status_code == 200:
                service_data = response.json()
                return ExternalServiceDetailResponse(**service_data)
            elif response.status_code == 404:
                logger.warning(f"Service {service_id} not found in external API")
                return None
            else:
                logger.error(f"Unexpected status code: {response.status_code}, body: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get service: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting service {service_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting service {service_id}: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def update_service(
            self,
            service_id: str,
            name: Optional[str] = None,
            description: Optional[str] = None,
            tags: Optional[List[str]] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[ExternalServiceResponse]:
        """서비스 수정"""
        try:
            url = f"{self.base_url}/services/{service_id}"

            payload = {}
            if name is not None:
                payload["name"] = name
            if description is not None:
                payload["description"] = description
            if tags is not None:
                payload["tags"] = tags

            logger.info(f"Updating service at: {url}")
            logger.info(f"Update data: {payload}")

            response = await self._make_authenticated_request(
                "PUT", url, user_info=user_info, json=payload
            )

            if response.status_code == 200:
                service_data = response.json()
                return ExternalServiceResponse(**service_data)
            elif response.status_code == 404:
                return None
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to update service: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout updating service {service_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating service {service_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def delete_service(
            self,
            service_id: str,
            user_info: Optional[Dict[str, str]] = None
    ) -> bool:
        """서비스 삭제"""
        try:
            url = f"{self.base_url}/services/{service_id}"

            logger.info(f"Deleting service at: {url}")

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
                    detail=f"Failed to delete service: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout deleting service {service_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting service {service_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )


# 싱글톤 인스턴스
service_service = ServiceService()