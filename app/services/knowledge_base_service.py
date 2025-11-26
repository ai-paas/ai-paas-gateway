import httpx
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import HTTPException, status, UploadFile
from app.config import settings
from app.schemas.knowledge_base import (
    ExternalKnowledgeBaseDetailResponse,
    ExternalKnowledgeBaseBriefResponse,
    ChunkTypeSchema,
    LanguageSchema,
    SearchMethodSchema,
    KnowledgeBaseSearchResponse,
    KnowledgeBaseSearchRecord
)

logger = logging.getLogger(__name__)


class KnowledgeBaseService:
    """지식베이스 관련 외부 API 서비스"""

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

    # ===== 메타데이터 조회 API =====

    async def get_chunk_types(self, user_info: Optional[Dict] = None) -> List[ChunkTypeSchema]:
        """청크 타입 목록 조회"""
        try:
            url = f"{self.base_url}/knowledge-bases/chunk-types"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                data = response.json()
                return [ChunkTypeSchema(**item) for item in data]
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting chunk types: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_languages(self, user_info: Optional[Dict] = None) -> List[LanguageSchema]:
        """언어 목록 조회"""
        try:
            url = f"{self.base_url}/knowledge-bases/languages"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                data = response.json()
                return [LanguageSchema(**item) for item in data]
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting languages: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_search_methods(self, user_info: Optional[Dict] = None) -> List[SearchMethodSchema]:
        """검색 방법 목록 조회"""
        try:
            url = f"{self.base_url}/knowledge-bases/search-methods"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                data = response.json()
                return [SearchMethodSchema(**item) for item in data]
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting search methods: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== Knowledge Base CRUD =====

    async def create_knowledge_base(
            self, name: str, file: UploadFile, language_id: int, embedding_model_id: int,
            chunk_size: int, chunk_overlap: int, chunk_type_id: int, search_method_id: int,
            top_k: int, threshold: float, description: Optional[str] = None,
            user_info: Optional[Dict] = None
    ) -> ExternalKnowledgeBaseDetailResponse:
        """지식베이스 생성 (파일 업로드)"""
        try:
            url = f"{self.base_url}/knowledge-bases"

            # multipart/form-data 구성
            files = {'file': (file.filename, await file.read(), file.content_type)}
            data = {
                'name': name,
                'language_id': language_id,
                'embedding_model_id': embedding_model_id,
                'chunk_size': chunk_size,
                'chunk_overlap': chunk_overlap,
                'chunk_type_id': chunk_type_id,
                'search_method_id': search_method_id,
                'top_k': top_k,
                'threshold': threshold
            }
            if description:
                data['description'] = description

            logger.info(f"Creating knowledge base: {name}")

            response = await self._make_authenticated_request("POST", url, user_info=user_info, files=files, data=data)

            if response.status_code in [200, 201]:
                kb_data = response.json()
                return ExternalKnowledgeBaseDetailResponse(**kb_data)
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error creating knowledge base: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_knowledge_bases(
            self, page: Optional[int] = None, page_size: Optional[int] = None, user_info: Optional[Dict] = None
    ) -> List[ExternalKnowledgeBaseBriefResponse]:
        """지식베이스 목록 조회"""
        try:
            url = f"{self.base_url}/knowledge-bases"
            params = {}
            if page is not None and page_size is not None:
                params = {"page": page, "page_size": page_size}

            response = await self._make_authenticated_request("GET", url, user_info=user_info, params=params)

            if response.status_code == 200:
                data = response.json()
                if isinstance(data, list):
                    return [ExternalKnowledgeBaseBriefResponse(**item) for item in data]
                return [ExternalKnowledgeBaseBriefResponse(**data)]
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting knowledge bases: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_knowledge_base(
            self, knowledge_base_id: int, user_info: Optional[Dict] = None
    ) -> Optional[ExternalKnowledgeBaseDetailResponse]:
        """지식베이스 상세 조회"""
        try:
            url = f"{self.base_url}/knowledge-bases/{knowledge_base_id}"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                return ExternalKnowledgeBaseDetailResponse(**response.json())
            elif response.status_code == 404:
                return None
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting knowledge base: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def update_knowledge_base(
            self, knowledge_base_id: int, name: Optional[str] = None, description: Optional[str] = None,
            user_info: Optional[Dict] = None
    ) -> Optional[ExternalKnowledgeBaseDetailResponse]:
        """지식베이스 수정 (이름, 설명만)"""
        try:
            url = f"{self.base_url}/knowledge-bases/{knowledge_base_id}"
            payload = {}
            if name:
                payload['name'] = name
            if description is not None:
                payload['description'] = description

            response = await self._make_authenticated_request("PUT", url, user_info=user_info, json=payload)

            if response.status_code == 200:
                return ExternalKnowledgeBaseDetailResponse(**response.json())
            elif response.status_code == 404:
                return None
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error updating knowledge base: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_knowledge_base(
            self, knowledge_base_id: int, user_info: Optional[Dict] = None
    ) -> bool:
        """지식베이스 삭제"""
        try:
            url = f"{self.base_url}/knowledge-bases/{knowledge_base_id}"
            response = await self._make_authenticated_request("DELETE", url, user_info=user_info)

            if response.status_code in [200, 204]:
                return True
            elif response.status_code == 404:
                return False
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting knowledge base: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== 파일 관리 =====

    async def add_file(
            self, knowledge_base_id: int, file: UploadFile, user_info: Optional[Dict] = None
    ) -> ExternalKnowledgeBaseDetailResponse:
        """지식베이스에 파일 추가"""
        try:
            url = f"{self.base_url}/knowledge-bases/{knowledge_base_id}/files"
            files = {'file': (file.filename, await file.read(), file.content_type)}

            response = await self._make_authenticated_request("POST", url, user_info=user_info, files=files)

            if response.status_code in [200, 201]:
                return ExternalKnowledgeBaseDetailResponse(**response.json())
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error adding file: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def delete_file(
            self, knowledge_base_id: int, file_id: int, user_info: Optional[Dict] = None
    ) -> ExternalKnowledgeBaseDetailResponse:
        """지식베이스에서 파일 삭제"""
        try:
            url = f"{self.base_url}/knowledge-bases/{knowledge_base_id}/files/{file_id}"
            response = await self._make_authenticated_request("DELETE", url, user_info=user_info)

            if response.status_code == 200:
                return ExternalKnowledgeBaseDetailResponse(**response.json())
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error deleting file: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    # ===== 검색 =====

    async def search_knowledge_base(
            self, knowledge_base_id: int, text: str, user_info: Optional[Dict] = None
    ) -> KnowledgeBaseSearchResponse:
        """지식베이스 검색"""
        try:
            url = f"{self.base_url}/knowledge-bases/{knowledge_base_id}/search"
            response = await self._make_authenticated_request("POST", url, user_info=user_info, json={"text": text})

            if response.status_code == 200:
                return KnowledgeBaseSearchResponse(**response.json())
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error searching knowledge base: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    async def get_search_records(
            self, knowledge_base_id: int, user_info: Optional[Dict] = None
    ) -> List[KnowledgeBaseSearchRecord]:
        """검색 기록 조회"""
        try:
            url = f"{self.base_url}/knowledge-bases/{knowledge_base_id}/search-records"
            response = await self._make_authenticated_request("GET", url, user_info=user_info)

            if response.status_code == 200:
                data = response.json()
                return [KnowledgeBaseSearchRecord(**item) for item in data]
            raise HTTPException(status_code=response.status_code, detail=response.text)
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error getting search records: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))


knowledge_base_service = KnowledgeBaseService()