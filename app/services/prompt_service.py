import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status
from app.config import settings
from app.schemas.prompt import (
    ExternalPromptResponse,
    PromptVariableTypeListSchema
)

logger = logging.getLogger(__name__)


class PromptService:
    """프롬프트 관련 외부 API 서비스 (인증 포함)"""

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

    async def get_variable_types(
            self,
            user_info: Optional[Dict[str, str]] = None
    ) -> PromptVariableTypeListSchema:
        """프롬프트 변수 가능한 타입 목록 조회"""
        try:
            url = f"{self.base_url}/prompts/variable-types"

            logger.info(f"Getting prompt variable types from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            if response.status_code == 200:
                data = response.json()
                return PromptVariableTypeListSchema(**data)
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get variable types: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting variable types: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting variable types: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def create_prompt(
            self,
            name: str,
            content: str,
            description: Optional[str] = None,
            prompt_variable: Optional[List[str]] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> ExternalPromptResponse:
        """프롬프트 생성"""
        try:
            url = f"{self.base_url}/prompts"

            payload = {
                "prompt": {
                    "name": name,
                    "content": content
                }
            }

            if description:
                payload["prompt"]["description"] = description
            if prompt_variable:
                payload["prompt_variable"] = prompt_variable

            logger.info(f"Creating prompt at: {url}")
            logger.info(f"Payload: {payload}")

            response = await self._make_authenticated_request(
                "POST", url, user_info=user_info, json=payload
            )

            if response.status_code in [200, 201]:
                prompt_data = response.json()
                return ExternalPromptResponse(**prompt_data)
            else:
                error_detail = response.text
                logger.error(f"Prompt creation failed: {error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to create prompt: {error_detail}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout creating prompt: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating prompt: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_prompts(
            self,
            page: Optional[int] = None,
            page_size: Optional[int] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> List[ExternalPromptResponse]:
        """프롬프트 목록 조회"""
        try:
            url = f"{self.base_url}/prompts"
            params = {}

            # page와 page_size 모두 있을 때만 페이지네이션 적용
            if page is not None and page_size is not None:
                params["page"] = page
                params["page_size"] = page_size

            logger.info(f"Getting prompts from: {url}")
            logger.info(f"Parameters: {params}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info, params=params
            )

            if response.status_code == 200:
                data = response.json()
                # 응답이 리스트인 경우
                if isinstance(data, list):
                    return [ExternalPromptResponse(**item) for item in data]
                # 응답이 딕셔너리인 경우 (data 키 확인)
                elif isinstance(data, dict) and 'data' in data:
                    return [ExternalPromptResponse(**item) for item in data['data']]
                else:
                    return [ExternalPromptResponse(**data)]
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get prompts: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting prompts: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting prompts: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def get_prompt(
            self,
            prompt_id: int,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[ExternalPromptResponse]:
        """프롬프트 상세 조회"""
        try:
            url = f"{self.base_url}/prompts/{prompt_id}"

            logger.info(f"Getting prompt from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            logger.info(f"Response status: {response.status_code}")
            logger.info(f"Response body: {response.text[:500]}")

            if response.status_code == 200:
                prompt_data = response.json()
                return ExternalPromptResponse(**prompt_data)
            elif response.status_code == 404:
                logger.warning(f"Prompt {prompt_id} not found in external API")
                return None
            else:
                logger.error(f"Unexpected status code: {response.status_code}, body: {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get prompt: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting prompt {prompt_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting prompt {prompt_id}: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def update_prompt(
            self,
            prompt_id: int,
            name: Optional[str] = None,
            description: Optional[str] = None,
            content: Optional[str] = None,
            prompt_variable: Optional[List[str]] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> Optional[ExternalPromptResponse]:
        """프롬프트 수정"""
        try:
            url = f"{self.base_url}/prompts/{prompt_id}"

            # 먼저 현재 프롬프트 조회
            logger.info(f"Fetching current prompt {prompt_id} before update")
            current_response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            if current_response.status_code == 200:
                current_data = current_response.json()
                logger.info(f"Current prompt data: {current_data}")
            else:
                logger.warning(f"Could not fetch current prompt: {current_response.status_code}")

            # payload 구조 - 외부 API 스웨거 문서에 따라 직접 필드 전송
            payload = {}

            if name is not None:
                payload["name"] = name
            if description is not None:
                payload["description"] = description
            if content is not None:
                payload["content"] = content
            if prompt_variable is not None:
                payload["prompt_variable"] = prompt_variable

            logger.info(f"Updating prompt at: {url}")
            logger.info(f"Update payload: {payload}")

            response = await self._make_authenticated_request(
                "PUT", url, user_info=user_info, json=payload
            )

            logger.info(f"Update response status: {response.status_code}")
            logger.info(f"Update response body: {response.text}")

            if response.status_code == 200:
                updated_data = response.json()
                logger.info(f"Updated prompt data: {updated_data}")

                # 업데이트 전후 비교
                if current_response.status_code == 200:
                    if current_data.get('name') == updated_data.get('name'):
                        logger.warning("⚠️  Name was NOT updated!")
                    else:
                        logger.info(f"✓ Name updated: {current_data.get('name')} -> {updated_data.get('name')}")

                    if current_data.get('content') == updated_data.get('content'):
                        logger.warning("⚠️  Content was NOT updated!")
                    else:
                        logger.info(
                            f"✓ Content updated (length: {len(current_data.get('content', ''))} -> {len(updated_data.get('content', ''))})")

                return ExternalPromptResponse(**updated_data)
            elif response.status_code == 404:
                logger.warning(f"Prompt {prompt_id} not found in external API")
                return None
            else:
                error_detail = response.text
                logger.error(f"Failed to update prompt: status={response.status_code}, body={error_detail}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to update prompt: {error_detail}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout updating prompt {prompt_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating prompt {prompt_id}: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

    async def delete_prompt(
            self,
            prompt_id: int,
            user_info: Optional[Dict[str, str]] = None
    ) -> bool:
        """프롬프트 삭제"""
        try:
            url = f"{self.base_url}/prompts/{prompt_id}"

            logger.info(f"Deleting prompt at: {url}")

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
                    detail=f"Failed to delete prompt: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout deleting prompt {prompt_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting prompt {prompt_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Internal error: {str(e)}"
            )

# 싱글톤 인스턴스
prompt_service = PromptService()