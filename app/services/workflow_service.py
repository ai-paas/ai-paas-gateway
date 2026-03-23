import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status, UploadFile
from app.config import settings
from app.schemas.workflow import (
    ExternalWorkflowDetailResponse,
    ExternalWorkflowBriefResponse,
    WorkflowDefinition,
    WorkflowExecuteResponse,
    WorkflowTestResponse
)

logger = logging.getLogger(__name__)


class WorkflowService:
    """워크플로우 관련 외부 API 서비스"""

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

    # ===== Workflow CRUD =====

    async def create_workflow(
            self, name: str, description: Optional[str] = None, category: Optional[str] = None,
            service_id: Optional[str] = None, workflow_definition: Optional[Dict] = None,
            user_info: Optional[Dict] = None
    ) -> ExternalWorkflowDetailResponse:
        """워크플로우 생성"""
        try:
            url = f"{self.base_url}/workflows"

            payload = {
                'name': name
            }
            if description:
                payload['description'] = description
            if category:
                payload['category'] = category
            if service_id:
                payload['service_id'] = service_id
            if workflow_definition:
                payload['workflow_definition'] = workflow_definition

            logger.info(f"Creating workflow: {name}")

            response = await self._make_authenticated_request("POST", url, user_info=user_info, json=payload)

            if response.status_code in [200, 201]:
                workflow_data = response.json()
                return ExternalWorkflowDetailResponse(**workflow_data)
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating workflow: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_workflows(
            self, page: Optional[int] = None, page_size: Optional[int] = None,
            creator_id: Optional[int] = None, service_id: Optional[int] = None,
            status: Optional[str] = None, user_info: Optional[Dict] = None
    ) -> List[ExternalWorkflowBriefResponse]:
        """워크플로우 목록 조회"""
        try:
            url = f"{self.base_url}/workflows"
            params = {}
            if page is not None and page_size is not None:
                params["page"] = page
                params["page_size"] = page_size
            if creator_id is not None:
                params["creator_id"] = creator_id
            if service_id is not None:
                params["service_id"] = service_id
            if status:
                params["status"] = status

            response = await self._make_authenticated_request("GET", url, user_info=user_info, params=params)

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, dict) and 'items' in data:
                    return [ExternalWorkflowBriefResponse(**item) for item in data['items']]
                elif isinstance(data, list):
                    return [ExternalWorkflowBriefResponse(**item) for item in data]
                return []
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting workflows: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_workflow(
            self, workflow_id: str, user_info: Optional[Dict] = None
    ) -> Optional[ExternalWorkflowDetailResponse]:
        """워크플로우 상세 조회"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                return ExternalWorkflowDetailResponse(**response.json())
            elif response.status_code == 404:
                return None
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting workflow: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def update_workflow(
            self, workflow_id: str, name: Optional[str] = None, description: Optional[str] = None,
            category: Optional[str] = None, status: Optional[str] = None,
            service_id: Optional[str] = None, workflow_definition: Optional[Dict] = None,
            user_info: Optional[Dict] = None
    ) -> Optional[ExternalWorkflowDetailResponse]:
        """워크플로우 수정"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}"
            payload = {}
            if name:
                payload['name'] = name
            if description is not None:
                payload['description'] = description
            if category:
                payload['category'] = category
            if status:
                payload['status'] = status
            if service_id is not None:
                payload['service_id'] = service_id
            if workflow_definition:
                payload['workflow_definition'] = workflow_definition

            response = await self._make_authenticated_request("PUT", url, user_info=user_info, json=payload)

            if response.status_code == 200:
                return ExternalWorkflowDetailResponse(**response.json())
            elif response.status_code == 404:
                return None
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating workflow: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_workflow(
            self, workflow_id: str, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우 삭제 시작 (2단계 프로세스)"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}"
            response = await self._make_authenticated_request("DELETE", url, user_info=user_info)

            if response.status_code in [200, 202]:
                return response.json()
            elif response.status_code == 404:
                raise HTTPException(status_code=404, detail="Workflow not found")
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting workflow: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def finalize_deletion(
            self, workflow_id: str, run_id: str, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우 삭제 완료 처리"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}/finalize-deletion"
            params = {"run_id": run_id}
            response = await self._make_authenticated_request("POST", url, user_info=user_info, params=params)

            if response.status_code == 200:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error finalizing deletion: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Workflow 실행 =====

    async def execute_workflow(
            self, workflow_id: str, parameters: Optional[Dict[str, Any]] = None,
            user_info: Optional[Dict] = None
    ) -> WorkflowExecuteResponse:
        """워크플로우 실행"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}/execute"
            payload = {}
            if parameters:
                payload['parameters'] = parameters

            response = await self._make_authenticated_request("POST", url, user_info=user_info, json=payload)

            if response.status_code == 200:
                return WorkflowExecuteResponse(**response.json())
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error executing workflow: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Workflow 상태 및 모델 조회 =====

    async def get_workflow_status(
            self, workflow_id: str, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우 실행 상태 조회"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}/status"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting workflow status: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_workflow_models(
            self, workflow_id: str, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우에 배포된 모델 목록 조회"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}/models"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting workflow models: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Workflow 정리 =====

    async def cleanup_workflow(
            self, workflow_id: str, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우 리소스 정리 시작"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}/cleanup"
            response = await self._make_authenticated_request("POST", url, user_info=user_info)

            if response.status_code in [200, 202]:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error starting workflow cleanup: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def finalize_cleanup(
            self, workflow_id: str, run_id: str, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우 정리 완료 처리"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}/finalize-cleanup"
            params = {"run_id": run_id}
            response = await self._make_authenticated_request("POST", url, user_info=user_info, params=params)

            if response.status_code == 200:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error finalizing cleanup: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Workflow 테스트 =====

    async def test_rag_workflow(
            self, workflow_id: str, text: str, user_info: Optional[Dict] = None
    ) -> WorkflowTestResponse:
        """RAG 워크플로우 테스트"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}/test/rag"
            data = {"text": text}

            response = await self._make_authenticated_request("POST", url, user_info=user_info, data=data)

            if response.status_code == 200:
                return WorkflowTestResponse(**response.json())
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error testing RAG workflow: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def test_ml_workflow(
            self, workflow_id: str, image: UploadFile, user_info: Optional[Dict] = None
    ) -> WorkflowTestResponse:
        """ML 워크플로우 테스트"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}/test/ml"
            files = {'image': (image.filename, await image.read(), image.content_type)}

            response = await self._make_authenticated_request("POST", url, user_info=user_info, files=files)

            if response.status_code == 200:
                return WorkflowTestResponse(**response.json())
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error testing ML workflow: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Template 관련 =====

    async def get_templates(
            self, page: Optional[int] = None, page_size: Optional[int] = None,
            category: Optional[str] = None, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우 템플릿 목록 조회"""
        try:
            url = f"{self.base_url}/workflows/templates"
            params = {}
            if page is not None and page_size is not None:
                params["page"] = page
                params["page_size"] = page_size
            if category:
                params["category"] = category

            response = await self._make_authenticated_request("GET", url, user_info=user_info, params=params)

            if response.status_code == 200:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting templates: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_template(
            self, template_id: str, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우 템플릿 상세 조회"""
        try:
            url = f"{self.base_url}/workflows/templates/{template_id}"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                return None
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting template: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def create_template(
            self, name: str, description: Optional[str] = None, category: Optional[str] = None,
            workflow_definition: Optional[Dict] = None, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우 템플릿 생성"""
        try:
            url = f"{self.base_url}/workflows/templates"
            payload = {"name": name}
            if description:
                payload["description"] = description
            if category:
                payload["category"] = category
            if workflow_definition:
                payload["workflow_definition"] = workflow_definition

            response = await self._make_authenticated_request("POST", url, user_info=user_info, json=payload)

            if response.status_code in [200, 201]:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating template: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def update_template(
            self, template_id: str, name: Optional[str] = None, description: Optional[str] = None,
            category: Optional[str] = None, status: Optional[str] = None,
            workflow_definition: Optional[Dict] = None, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """워크플로우 템플릿 수정"""
        try:
            url = f"{self.base_url}/workflows/templates/{template_id}"
            payload = {}
            if name:
                payload["name"] = name
            if description is not None:
                payload["description"] = description
            if category:
                payload["category"] = category
            if status:
                payload["status"] = status
            if workflow_definition:
                payload["workflow_definition"] = workflow_definition

            response = await self._make_authenticated_request("PUT", url, user_info=user_info, json=payload)

            if response.status_code == 200:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating template: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_template(
            self, template_id: str, user_info: Optional[Dict] = None
    ) -> bool:
        """워크플로우 템플릿 삭제"""
        try:
            url = f"{self.base_url}/workflows/templates/{template_id}"
            response = await self._make_authenticated_request("DELETE", url, user_info=user_info)

            if response.status_code in [200, 204]:
                return True
            elif response.status_code == 404:
                return False
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting template: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def clone_template(
            self, template_id: str, workflow_name: str, service_id: Optional[int] = None,
            user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """템플릿으로부터 워크플로우 생성"""
        try:
            url = f"{self.base_url}/workflows/templates/{template_id}/clone"
            params = {"workflow_name": workflow_name}
            if service_id is not None:
                params["service_id"] = service_id

            response = await self._make_authenticated_request("POST", url, user_info=user_info, params=params)

            if response.status_code in [200, 201]:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error cloning template: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Component Types =====

    async def get_component_types(
            self, user_info: Optional[Dict] = None
    ) -> List[Dict[str, Any]]:
        """사용 가능한 컴포넌트 타입 조회"""
        try:
            url = f"{self.base_url}/workflows/component-types"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting component types: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Component Deployment Status (내부 API) =====

    async def update_component_deployment_status(
            self, workflow_id: str, component_id: str,
            service_name: str, service_hostname: str, model_name: str,
            status: str, internal_url: Optional[str] = None,
            error_message: Optional[str] = None, user_info: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """컴포넌트 KServe 배포 상태 업데이트 (내부 API - Pipeline에서만 호출)"""
        try:
            url = f"{self.base_url}/workflows/{workflow_id}/components/{component_id}/deployment-status"
            payload = {
                "service_name": service_name,
                "service_hostname": service_hostname,
                "model_name": model_name,
                "status": status
            }
            if internal_url:
                payload["internal_url"] = internal_url
            if error_message:
                payload["error_message"] = error_message

            response = await self._make_authenticated_request("POST", url, user_info=user_info, json=payload)

            if response.status_code == 200:
                return response.json()
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating component deployment status: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))


workflow_service = WorkflowService()