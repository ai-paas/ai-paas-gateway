import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List

import httpx
from fastapi import HTTPException, status

from app.config import settings
from app.schemas.service import (
    ExternalServiceResponse,
    ExternalServiceDetailResponse,
    KnowledgeBaseSummary,
    ModelSummary,
    PromptSummary,
    WorkflowRefSchema,
)
from app.services.workflow_service import workflow_service
from app.services.knowledge_base_service import knowledge_base_service
from app.services.model_service import model_service
from app.services.prompt_service import prompt_service
from app.cruds.knowledge_base import knowledge_base_crud
from app.cruds.model import model_crud
from app.cruds.prompt import prompt_crud
from app.models.model import Model

logger = logging.getLogger(__name__)


def _name_of(obj: Any, attr: str) -> Optional[str]:
    """Nested 객체(예: provider_info)의 name 속성을 안전하게 추출."""
    nested = getattr(obj, attr, None)
    if nested is None:
        return None
    return getattr(nested, "name", None)


def _build_model_summary(
    model_id: int,
    refs: List[WorkflowRefSchema],
    inline_obj: Any = None,
    fetched_obj: Any = None,
) -> Optional[ModelSummary]:
    """inline ModelDetailSchema 또는 단건 호출 결과(ModelResponse)에서 ModelSummary 빌드."""
    src = inline_obj if inline_obj is not None else fetched_obj
    if src is None:
        return None
    return ModelSummary(
        id=model_id,
        name=getattr(src, "name", None) or f"model-{model_id}",
        description=getattr(src, "description", None),
        provider=_name_of(src, "provider_info"),
        model_type=_name_of(src, "type_info"),
        format=_name_of(src, "format_info"),
        task=getattr(src, "task", None),
        visibility=getattr(src, "visibility", None),
        created_at=getattr(src, "created_at", None),
        workflow_refs=refs,
    )


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

    async def get_resource_usages(
            self,
            service_id: str,
            user_info: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """서비스 리소스 사용량 조회"""
        try:
            url = f"{self.base_url}/services/{service_id}/resource-usages"

            logger.info(f"Getting resource usages from: {url}")

            response = await self._make_authenticated_request(
                "GET", url, user_info=user_info
            )

            if response.status_code == 200:
                return response.json()
            elif response.status_code == 404:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Service not found"
                )
            else:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=f"Failed to get resource usages: {response.text}"
                )

        except httpx.TimeoutException as e:
            logger.error(f"Timeout getting resource usages for {service_id}: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="External service timeout"
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting resource usages for {service_id}: {str(e)}")
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

    async def enrich_service_detail(
        self,
        external_data: ExternalServiceDetailResponse,
        db: Any,
        current_user: Any,
    ) -> Dict[str, Any]:
        """서비스 detail 응답에 워크플로우 컴포넌트 기반 KB/모델/프롬프트 평탄 리스트를 채워 반환.

        흐름: 워크플로우 detail 병렬 조회 → 컴포넌트의 ID 수집 → gateway DB 매핑/권한 검증
        → 단건 조회(병렬) → Summary 매핑 → id ASC 정렬.

        Best-effort: 워크플로우/단건 호출 실패나 권한 거부는 해당 항목만 누락, 메인 응답은 200.
        """
        empty: Dict[str, Any] = {"knowledge_bases": [], "models": [], "prompts": []}

        try:
            workflows = list(getattr(external_data, "workflows", []) or [])
            if not workflows:
                return empty

            user_info = {
                "member_id": current_user.member_id,
                "role": current_user.role,
                "name": current_user.name,
            }
            is_admin = current_user.role == "admin"

            # 1) workflow detail 병렬 조회 (동시성 상한 8)
            sem = asyncio.Semaphore(8)

            async def _fetch_workflow(wf_id: str):
                async with sem:
                    return await workflow_service.get_workflow(wf_id, user_info)

            wf_results = await asyncio.gather(
                *[_fetch_workflow(wf.id) for wf in workflows],
                return_exceptions=True,
            )

            # 2) 컴포넌트의 ID 수집 + workflow_refs 누적 + inline 모델 캐시
            kb_workflows: Dict[int, List[WorkflowRefSchema]] = {}
            model_workflows: Dict[int, List[WorkflowRefSchema]] = {}
            prompt_workflows: Dict[int, List[WorkflowRefSchema]] = {}
            model_inline: Dict[int, Any] = {}

            for wf, result in zip(workflows, wf_results):
                if isinstance(result, Exception):
                    logger.warning(
                        f"enrich: skip workflow detail {wf.id}: {result}"
                    )
                    continue
                if result is None:
                    continue
                ref = WorkflowRefSchema(id=result.id, name=result.name)
                seen_kb: set = set()
                seen_model: set = set()
                seen_prompt: set = set()
                for comp in (result.components or []):
                    kb_id = getattr(comp, "knowledge_base_id", None)
                    if kb_id is not None and kb_id not in seen_kb:
                        seen_kb.add(kb_id)
                        kb_workflows.setdefault(kb_id, []).append(ref)
                    m_id = getattr(comp, "model_id", None)
                    if m_id is not None and m_id not in seen_model:
                        seen_model.add(m_id)
                        model_workflows.setdefault(m_id, []).append(ref)
                        if getattr(comp, "model", None) is not None:
                            model_inline.setdefault(m_id, comp.model)
                    p_id = getattr(comp, "prompt_id", None)
                    if p_id is not None and p_id not in seen_prompt:
                        seen_prompt.add(p_id)
                        prompt_workflows.setdefault(p_id, []).append(ref)

            # 3) 권한/매핑 검증 — 동기 DB 쿼리
            allowed_kb_db: Dict[int, Any] = {}
            for kb_id in kb_workflows:
                db_kb = knowledge_base_crud.get_active_knowledge_base_by_surro_id(
                    db, surro_knowledge_id=kb_id
                )
                if not db_kb:
                    logger.info(f"enrich: skip kb {kb_id} (no gateway mapping)")
                    continue
                if not is_admin and db_kb.created_by != current_user.member_id:
                    logger.info(
                        f"enrich: skip kb {kb_id} (permission denied for {current_user.member_id})"
                    )
                    continue
                allowed_kb_db[kb_id] = db_kb

            allowed_model_ids: List[int] = []
            for m_id in model_workflows:
                is_owner = model_crud.check_model_ownership(
                    db, m_id, current_user.member_id
                )
                if not is_owner:
                    catalog_model = (
                        db.query(Model)
                        .filter(
                            Model.is_catalog == True,  # noqa: E712
                            Model.deleted_at.is_(None),
                            Model.surro_model_id == m_id,
                        )
                        .first()
                    )
                    if not catalog_model:
                        logger.info(
                            f"enrich: skip model {m_id} (no ownership and not catalog)"
                        )
                        continue
                allowed_model_ids.append(m_id)

            allowed_prompt_db: Dict[int, Any] = {}
            for p_id in prompt_workflows:
                db_prompt = prompt_crud.get_prompt_by_surro_id(
                    db, surro_prompt_id=p_id
                )
                if not db_prompt:
                    logger.info(f"enrich: skip prompt {p_id} (no gateway mapping)")
                    continue
                if not is_admin and db_prompt.created_by != current_user.member_id:
                    logger.info(
                        f"enrich: skip prompt {p_id} (permission denied for {current_user.member_id})"
                    )
                    continue
                allowed_prompt_db[p_id] = db_prompt

            # 4) 단건 조회 병렬 (권한 통과 ID만, inline 있는 모델은 호출 생략)
            allowed_kb_ids = list(allowed_kb_db.keys())
            allowed_prompt_ids = list(allowed_prompt_db.keys())
            model_ids_to_fetch = [
                m_id for m_id in allowed_model_ids if m_id not in model_inline
            ]

            kb_results, prompt_results, model_results = await asyncio.gather(
                asyncio.gather(
                    *[
                        knowledge_base_service.get_knowledge_base(kb_id, user_info)
                        for kb_id in allowed_kb_ids
                    ],
                    return_exceptions=True,
                ),
                asyncio.gather(
                    *[
                        prompt_service.get_prompt(p_id, user_info)
                        for p_id in allowed_prompt_ids
                    ],
                    return_exceptions=True,
                ),
                asyncio.gather(
                    *[
                        model_service.get_model(m_id, user_info)
                        for m_id in model_ids_to_fetch
                    ],
                    return_exceptions=True,
                ),
            )

            # 5) Summary 매핑
            kb_list: List[KnowledgeBaseSummary] = []
            for kb_id, ext in zip(allowed_kb_ids, kb_results):
                db_kb = allowed_kb_db[kb_id]
                if isinstance(ext, Exception):
                    logger.warning(f"enrich: skip kb {kb_id}: {ext}")
                    continue
                if ext is None:
                    logger.warning(f"enrich: skip kb {kb_id} (upstream 404)")
                    continue
                kb_list.append(
                    KnowledgeBaseSummary(
                        id=kb_id,
                        name=ext.name,
                        description=ext.description,
                        type="RAG",
                        collection_name=getattr(ext, "collection_name", None),
                        embedding_model_id=getattr(ext, "embedding_model_id", None),
                        search_method_id=getattr(ext, "search_method_id", None),
                        created_by=db_kb.created_by,
                        created_at=db_kb.created_at,
                        workflow_refs=kb_workflows[kb_id],
                    )
                )

            prompt_list: List[PromptSummary] = []
            for p_id, ext in zip(allowed_prompt_ids, prompt_results):
                db_prompt = allowed_prompt_db[p_id]
                if isinstance(ext, Exception):
                    logger.warning(f"enrich: skip prompt {p_id}: {ext}")
                    continue
                if ext is None:
                    logger.warning(f"enrich: skip prompt {p_id} (upstream 404)")
                    continue
                variables: List[str] = []
                raw_vars = getattr(ext, "prompt_variable", None) or []
                for v in raw_vars:
                    v_name = getattr(v, "name", None)
                    if v_name:
                        variables.append(v_name)
                prompt_list.append(
                    PromptSummary(
                        id=p_id,
                        name=ext.name,
                        description=ext.description,
                        content=getattr(ext, "content", None),
                        variables=variables,
                        created_at=db_prompt.created_at,
                        created_by=db_prompt.created_by,
                        workflow_refs=prompt_workflows[p_id],
                    )
                )

            model_list: List[ModelSummary] = []
            fetched_by_id: Dict[int, Any] = {}
            for m_id, ext in zip(model_ids_to_fetch, model_results):
                if isinstance(ext, Exception):
                    logger.warning(f"enrich: skip model {m_id}: {ext}")
                    continue
                if ext is None:
                    logger.warning(f"enrich: skip model {m_id} (upstream 404)")
                    continue
                fetched_by_id[m_id] = ext
            for m_id in allowed_model_ids:
                refs = model_workflows[m_id]
                summary = _build_model_summary(
                    model_id=m_id,
                    refs=refs,
                    inline_obj=model_inline.get(m_id),
                    fetched_obj=fetched_by_id.get(m_id),
                )
                if summary is not None:
                    model_list.append(summary)

            # 6) id ASC 안정 정렬
            kb_list.sort(key=lambda x: x.id)
            model_list.sort(key=lambda x: x.id)
            prompt_list.sort(key=lambda x: x.id)

            return {
                "knowledge_bases": kb_list,
                "models": model_list,
                "prompts": prompt_list,
            }

        except Exception:
            logger.exception("enrich_service_detail failed; returning empty enrichment")
            return empty


# 싱글톤 인스턴스
service_service = ServiceService()