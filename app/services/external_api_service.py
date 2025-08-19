import httpx
import logging
from typing import Dict, Any, Optional
from fastapi import HTTPException, status
from app.config import settings
from app.schemas.workflow import ExternalWorkflowResponse

logger = logging.getLogger(__name__)


class ExternalAPIService:
    """Surro API 호출 테스트 지원 서비스"""

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
            follow_redirects=True,
            headers={
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'User-Agent': 'AIPaaS-Gateway/1.0'
            }
        )

    async def close(self):
        """HTTP 클라이언트 종료"""
        await self.client.aclose()

    async def test_api_endpoint(
            self,
            path: Optional[str] = None,
            parameters: Optional[Dict[str, Any]] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        테스트용 API 엔드포인트 호출

        Args:
            path: 추가 경로 (예: "workflows", "models", "prompt" ...)
            parameters: 요청 파라미터
            user_info: 사용자 정보

        Returns:
            Dict: API 응답 정보
        """
        if not settings.PROXY_ENABLED:
            return {
                "status": "disabled",
                "message": "External service is disabled"
            }

        try:
            # URL 구성
            target_path = f"{settings.PROXY_TARGET_PATH_PREFIX}/{path}" if path else settings.PROXY_TARGET_PATH_PREFIX
            target_url = f"{settings.PROXY_TARGET_BASE_URL}{target_path}"

            logger.info(f"Testing API endpoint - Target URL: {target_url}")
            logger.info(f"Testing API endpoint - Parameters: {parameters}")

            # 헤더 설정
            headers = {}
            if user_info:
                if user_info.get('member_id'):
                    headers['X-User-ID'] = str(user_info['member_id'])
                if user_info.get('role'):
                    headers['X-User-Role'] = str(user_info['role'])
                if user_info.get('name'):
                    import base64
                    name_b64 = base64.b64encode(str(user_info['name']).encode('utf-8')).decode('ascii')
                    headers['X-User-Name-B64'] = name_b64

            logger.info(f"Testing API endpoint - Headers: {headers}")

            # GET 요청 테스트
            if not parameters:
                response = await self.client.get(target_url, headers=headers)
            else:
                # POST 요청 테스트
                response = await self.client.post(
                    target_url,
                    json=parameters,
                    headers=headers
                )

            logger.info(f"Test response status: {response.status_code}")
            logger.info(f"Test response headers: {dict(response.headers)}")
            logger.info(f"Test response body: {response.text}")

            return {
                "target_url": target_url,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "response_text": response.text[:1000],  # 첫 1000자만
                "success": response.status_code < 400
            }

        except httpx.TimeoutException as e:
            logger.error(f"Test API timeout: {str(e)}")
            return {
                "target_url": target_url,
                "status": "timeout",
                "error": str(e),
                "success": False
            }
        except httpx.ConnectError as e:
            logger.error(f"Test API connection error: {str(e)}")
            return {
                "target_url": target_url,
                "status": "connection_error",
                "error": str(e),
                "success": False
            }
        except Exception as e:
            logger.error(f"Test API error: {str(e)}")
            return {
                "target_url": target_url,
                "status": "error",
                "error": str(e),
                "success": False
            }

    async def debug_connection(self) -> Dict[str, Any]:
        """
        외부 서비스 연결 테스트

        Returns:
            Dict: 연결 상태 정보
        """
        if not settings.PROXY_ENABLED:
            return {
                "status": "disabled",
                "message": "External service is disabled"
            }

        try:
            # 기본 URL로 연결 테스트
            # base_url = settings.PROXY_TARGET_BASE_URL + settings.PROXY_TARGET_PATH_PREFIX
            base_url = settings.PROXY_TARGET_BASE_URL + "/docs"

            logger.info(f"[EXTERNAL_API] === Testing connection ===")
            logger.info(f"[EXTERNAL_API] Base URL: {base_url}")

            response = await self.client.get(base_url)

            logger.info(f"[EXTERNAL_API] Connection response status: {response.status_code}")
            logger.info(f"[EXTERNAL_API] Connection response headers: {dict(response.headers)}")
            logger.info(f"[EXTERNAL_API] Connection response body: {response.text[:500]}")

            return {
                "base_url": base_url,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "response_text": response.text[:500],  # 첫 500자만
                "connection_success": True
            }

        except httpx.TimeoutException as e:
            logger.error(f"Connection timeout: {str(e)}")
            return {
                "base_url": base_url,
                "status": "timeout",
                "error": str(e),
                "connection_success": False
            }
        except httpx.ConnectError as e:
            logger.error(f"Connection error: {str(e)}")
            return {
                "base_url": base_url,
                "status": "connection_error",
                "error": str(e),
                "connection_success": False
            }
        except Exception as e:
            logger.error(f"Debug connection error: {str(e)}")
            return {
                "base_url": base_url,
                "status": "error",
                "error": str(e),
                "connection_success": False
            }


# 전역 외부 워크플로우 서비스 인스턴스
external_api_service = ExternalAPIService()