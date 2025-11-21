from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


# ===== 공통 스키마 =====

class ChunkTypeSchema(BaseModel):
    """청크 타입"""
    id: int
    name: str
    description: Optional[str] = None


class LanguageSchema(BaseModel):
    """언어"""
    id: int
    name: str
    description: Optional[str] = None


class SearchMethodSchema(BaseModel):
    """검색 방법"""
    id: int
    name: str
    description: Optional[str] = None


# ===== Knowledge Base 파일 관련 =====

class KnowledgeBaseFileReadSchema(BaseModel):
    """지식베이스 파일 정보"""
    id: int
    knowledge_base_id: int
    file_name: str
    file_size: Optional[int] = None
    file_path: Optional[str] = None
    partition_name: Optional[str] = None
    created_at: Optional[datetime] = None


# ===== 외부 API 응답 스키마 =====

class ExternalKnowledgeBaseDetailResponse(BaseModel):
    """외부 API에서 반환되는 지식베이스 상세 응답"""
    id: int
    name: str
    description: Optional[str] = None
    collection_name: str

    # 설정 정보
    embedding_model_id: int
    language_id: int
    chunk_size: int
    chunk_overlap: int
    chunk_type_id: int
    search_method_id: int
    top_k: int
    threshold: float

    # 메타 정보
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None

    # 파일 목록
    files: List[KnowledgeBaseFileReadSchema] = []


class ExternalKnowledgeBaseBriefResponse(BaseModel):
    """외부 API에서 반환되는 지식베이스 간략 응답 (목록용)"""
    id: int
    name: str
    description: Optional[str] = None
    collection_name: str
    chunk_size: int
    chunk_overlap: int
    top_k: int
    threshold: float

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None


# ===== 지식베이스 생성/수정 요청 =====

class KnowledgeBaseCreate(BaseModel):
    """지식베이스 생성 요청 (multipart/form-data)"""
    name: str = Field(..., description="지식베이스 이름")
    description: Optional[str] = Field(None, description="지식베이스 설명")
    language_id: int = Field(..., description="언어 ID")
    embedding_model_id: int = Field(..., description="임베딩 모델 ID")
    chunk_size: int = Field(..., ge=1, description="청크 크기")
    chunk_overlap: int = Field(..., ge=0, description="청크 오버랩 크기")
    chunk_type_id: int = Field(..., description="청크 타입 ID")
    search_method_id: int = Field(..., description="검색 방법 ID")
    top_k: int = Field(..., ge=1, description="검색 시 반환할 상위 k개 결과 수")
    threshold: float = Field(..., ge=0.0, le=1.0, description="검색 임계값")
    # file은 FastAPI의 UploadFile로 별도 처리


class KnowledgeBaseUpdate(BaseModel):
    """지식베이스 수정 요청 (이름, 설명만 수정 가능)"""
    name: Optional[str] = Field(None, description="수정할 이름")
    description: Optional[str] = Field(None, description="수정할 설명")


# ===== 우리 DB 응답 스키마 =====

class KnowledgeBaseResponse(BaseModel):
    """우리 DB 지식베이스 응답 (메타정보 + 외부 API 핵심 데이터)"""
    # DB 메타 정보
    id: int  # 우리 DB의 PK
    surro_knowledge_id: int  # 외부 API의 ID
    created_at: datetime
    updated_at: datetime
    created_by: str

    # 외부 API 핵심 데이터
    name: str
    description: Optional[str] = None
    collection_name: str

    # 설정 정보 (선택적으로 포함)
    chunk_size: Optional[int] = None
    chunk_overlap: Optional[int] = None
    top_k: Optional[int] = None
    threshold: Optional[float] = None


class KnowledgeBaseDetailResponse(BaseModel):
    """지식베이스 상세 응답 (전체 정보)"""
    # DB 메타 정보
    id: int
    surro_knowledge_id: int
    created_at: datetime
    updated_at: datetime
    created_by: str

    # 외부 API 전체 데이터
    name: str
    description: Optional[str] = None
    collection_name: str
    embedding_model_id: int
    language_id: int
    chunk_size: int
    chunk_overlap: int
    chunk_type_id: int
    search_method_id: int
    top_k: int
    threshold: float
    files: List[KnowledgeBaseFileReadSchema] = []


class KnowledgeBaseListResponse(BaseModel):
    """지식베이스 목록 응답"""
    data: List[KnowledgeBaseResponse]
    total: int
    page: Optional[int] = None
    size: Optional[int] = None


# ===== 검색 관련 스키마 =====

class KnowledgeBaseSearchRequest(BaseModel):
    """지식베이스 검색 요청"""
    text: str = Field(..., description="검색할 쿼리 텍스트")


class SearchResultItem(BaseModel):
    """검색 결과 항목"""
    text: str
    score: float
    chunk_id: Optional[str] = None
    partition_name: Optional[str] = None
    file_name: Optional[str] = None


class KnowledgeBaseSearchResponse(BaseModel):
    """지식베이스 검색 응답"""
    results: List[SearchResultItem]
    total: int
    search_method: str


class KnowledgeBaseSearchRecord(BaseModel):
    """지식베이스 검색 기록"""
    id: int
    knowledge_base_id: int
    source: str
    text: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None


# ===== 리스트 응답 스키마 =====

class ChunkTypeListResponse(BaseModel):
    """청크 타입 목록 응답"""
    data: List[ChunkTypeSchema]


class LanguageListResponse(BaseModel):
    """언어 목록 응답"""
    data: List[LanguageSchema]


class SearchMethodListResponse(BaseModel):
    """검색 방법 목록 응답"""
    data: List[SearchMethodSchema]