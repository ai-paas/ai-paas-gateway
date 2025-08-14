import httpx
import logging
from typing import Dict, Any, Optional
from fastapi import HTTPException, status
from app.config import settings
from app.schemas.workflow import ExternalWorkflowResponse

logger = logging.getLogger(__name__)


class ExternalWorkflowService:
    """외부 워크플로우 API 연동 서비스"""

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

    async def create_workflow(
            self,
            parameters: Dict[str, Any],
            user_info: Optional[Dict[str, str]] = None
    ) -> ExternalWorkflowResponse:
        """
        S업체에 워크플로우 생성 요청

        Args:
            parameters: 워크플로우 생성에 필요한 파라미터
            user_info: 사용자 정보 (member_id, name, role 등)

        Returns:
            ExternalWorkflowResponse: S업체에서 반환된 워크플로우 정보
        """
        if not settings.PROXY_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="External workflow service is disabled"
            )

        # API 엔드포인트 설정 (S업체의 실제 워크플로우 생성 엔드포인트로 변경 필요)
        workflow_create_url = f"{settings.PROXY_TARGET_BASE_URL}{settings.PROXY_TARGET_PATH_PREFIX}/workflows"

        # 요청 헤더에 사용자 정보 추가
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

        try:
            logger.info(f"[EXTERNAL_API] === Creating workflow ===")
            logger.info(f"[EXTERNAL_API] Parameters: {parameters}")
            logger.info(f"[EXTERNAL_API] User info: {user_info}")
            logger.info(f"[EXTERNAL_API] Target URL: {workflow_create_url}")
            logger.info(f"[EXTERNAL_API] Headers: {headers}")

            response = await self.client.post(
                workflow_create_url,
                json=parameters,
                headers=headers
            )

            logger.info(f"[EXTERNAL_API] Response status: {response.status_code}")
            logger.info(f"[EXTERNAL_API] Response headers: {dict(response.headers)}")
            logger.info(f"[EXTERNAL_API] Response body: {response.text}")

            if response.status_code == 201 or response.status_code == 200:
                response_data = response.json()

                # S업체 응답 형태에 따라 조정 필요
                # 예시 응답 구조를 가정:
                # {
                #   "workflow_id": "wf_12345",
                #   "status": "created",
                #   "message": "Workflow created successfully",
                #   "created_at": "2024-01-01T00:00:00Z"
                # }

                return ExternalWorkflowResponse(
                    workflow_id=response_data.get('workflow_id') or response_data.get('id'),
                    status=response_data.get('status', 'created'),
                    message=response_data.get('message'),
                    created_at=response_data.get('created_at')
                )
            else:
                logger.error(f"External API error: {response.status_code} - {response.text}")
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"External workflow creation failed: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"External API timeout: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External workflow service timeout"
            )
        except httpx.ConnectError as e:
            logger.error(f"External API connection error: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Cannot connect to external workflow service"
            )
        except Exception as e:
            logger.error(f"Unexpected error calling external API: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"External workflow service error: {str(e)}"
            )

    async def get_workflow(self, external_workflow_id: str) -> Optional[Dict[str, Any]]:
        """
        S업체에서 워크플로우 정보 조회

        Args:
            external_workflow_id: S업체의 워크플로우 ID

        Returns:
            Dict: 워크플로우 정보 또는 None
        """
        if not settings.PROXY_ENABLED:
            return None

        try:
            workflow_get_url = f"{settings.PROXY_TARGET_BASE_URL}{settings.PROXY_TARGET_PATH_PREFIX}/workflows/{external_workflow_id}"

            logger.info(f"[EXTERNAL_API] === Getting workflow ===")
            logger.info(f"[EXTERNAL_API] External workflow ID: {external_workflow_id}")
            logger.info(f"[EXTERNAL_API] Target URL: {workflow_get_url}")

            response = await self.client.get(workflow_get_url)

            logger.info(f"[EXTERNAL_API] Response status: {response.status_code}")
            logger.info(f"[EXTERNAL_API] Response headers: {dict(response.headers)}")
            logger.info(f"[EXTERNAL_API] Response body: {response.text}")

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            else:
                logger.error(f"Error getting workflow {external_workflow_id}: {response.status_code}")
                return None

        except Exception as e:
            logger.error(f"Error getting workflow {external_workflow_id}: {str(e)}")
            return None

    async def update_workflow(
            self,
            external_workflow_id: str,
            parameters: Dict[str, Any],
            user_info: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        S업체 워크플로우 업데이트

        Args:
            external_workflow_id: S업체의 워크플로우 ID
            parameters: 업데이트할 파라미터
            user_info: 사용자 정보

        Returns:
            bool: 업데이트 성공 여부
        """
        if not settings.PROXY_ENABLED:
            return True  # 외부 서비스가 비활성화된 경우 성공으로 처리

        try:
            workflow_update_url = f"{settings.PROXY_TARGET_BASE_URL}{settings.PROXY_TARGET_PATH_PREFIX}/workflows/{external_workflow_id}"

            # 사용자 정보를 헤더에 추가
            headers = {}
            if user_info:
                if user_info.get('member_id'):
                    headers['X-User-ID'] = str(user_info['member_id'])
                if user_info.get('role'):
                    headers['X-User-Role'] = str(user_info['role'])

            logger.info(f"[EXTERNAL_API] === Updating workflow ===")
            logger.info(f"[EXTERNAL_API] External workflow ID: {external_workflow_id}")
            logger.info(f"[EXTERNAL_API] Parameters: {parameters}")
            logger.info(f"[EXTERNAL_API] User info: {user_info}")
            logger.info(f"[EXTERNAL_API] Target URL: {workflow_update_url}")
            logger.info(f"[EXTERNAL_API] Headers: {headers}")

            response = await self.client.put(
                workflow_update_url,
                json=parameters,
                headers=headers
            )

            logger.info(f"[EXTERNAL_API] Response status: {response.status_code}")
            logger.info(f"[EXTERNAL_API] Response headers: {dict(response.headers)}")
            logger.info(f"[EXTERNAL_API] Response body: {response.text}")

            return response.status_code in [200, 204]

        except Exception as e:
            logger.error(f"Error updating external workflow {external_workflow_id}: {str(e)}")
            return False

    async def delete_workflow(
            self,
            external_workflow_id: str,
            user_info: Optional[Dict[str, str]] = None
    ) -> bool:
        """
        S업체 워크플로우 삭제

        Args:
            external_workflow_id: S업체의 워크플로우 ID
            user_info: 사용자 정보

        Returns:
            bool: 삭제 성공 여부
        """
        if not settings.PROXY_ENABLED:
            return True  # 외부 서비스가 비활성화된 경우 성공으로 처리

        try:
            workflow_delete_url = f"{settings.PROXY_TARGET_BASE_URL}{settings.PROXY_TARGET_PATH_PREFIX}/workflows/{external_workflow_id}"

            # 사용자 정보를 헤더에 추가
            headers = {}
            if user_info:
                if user_info.get('member_id'):
                    headers['X-User-ID'] = str(user_info['member_id'])
                if user_info.get('role'):
                    headers['X-User-Role'] = str(user_info['role'])

            logger.info(f"[EXTERNAL_API] === Deleting workflow ===")
            logger.info(f"[EXTERNAL_API] External workflow ID: {external_workflow_id}")
            logger.info(f"[EXTERNAL_API] User info: {user_info}")
            logger.info(f"[EXTERNAL_API] Target URL: {workflow_delete_url}")
            logger.info(f"[EXTERNAL_API] Headers: {headers}")

            response = await self.client.delete(
                workflow_delete_url,
                headers=headers
            )

            logger.info(f"[EXTERNAL_API] Response status: {response.status_code}")
            logger.info(f"[EXTERNAL_API] Response headers: {dict(response.headers)}")
            logger.info(f"[EXTERNAL_API] Response body: {response.text}")

            return response.status_code in [200, 204, 404]  # 404도 성공으로 처리 (이미 삭제됨)

        except Exception as e:
            logger.error(f"Error deleting external workflow {external_workflow_id}: {str(e)}")
            return False

    async def test_task_endpoint(
            self,
            path: Optional[str] = None,
            parameters: Optional[Dict[str, Any]] = None,
            user_info: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        테스트용 task 엔드포인트 호출

        Args:
            path: 추가 경로 (예: "tasks", "tasks/list" 등)
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

            logger.info(f"Testing task endpoint - Target URL: {target_url}")
            logger.info(f"Testing task endpoint - Parameters: {parameters}")

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

            logger.info(f"Testing task endpoint - Headers: {headers}")

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
            base_url = settings.PROXY_TARGET_BASE_URL

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
external_workflow_service = ExternalWorkflowService()