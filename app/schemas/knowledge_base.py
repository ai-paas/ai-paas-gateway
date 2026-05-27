from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class ChunkTypeSchema(BaseModel):
    """청크 타입"""

    id: int = Field(..., description="청크 타입 ID")
    name: str = Field(..., description='청크 타입 이름 (예: "RecursiveTextSplitter", "RecursiveCharacterSplitter")')
    description: Optional[str] = Field(None, description="청크 타입 설명")


class LanguageSchema(BaseModel):
    """언어"""

    id: int = Field(..., description="언어 ID")
    name: str = Field(..., description='언어 코드 (예: "KO", "EN")')
    description: Optional[str] = Field(None, description='언어 설명 (예: "한국어", "영어")')


class SearchMethodSchema(BaseModel):
    """검색 방법"""

    id: int = Field(..., description="검색 방법 ID")
    name: str = Field(..., description='검색 방법 이름 (예: "vector")')
    description: Optional[str] = Field(None, description="검색 방법 설명")


class KnowledgeBaseFileReadSchema(BaseModel):
    """지식베이스 파일 정보"""

    model_config = ConfigDict(extra="ignore")

    id: int = Field(..., description="파일 ID")
    knowledge_base_id: int = Field(..., description="Knowledge Base ID")
    name: str = Field(..., description="파일 이름")
    partition_name: str = Field(..., description="Milvus Partition 이름")
    chunk_number: Optional[int] = Field(None, description="생성된 청크 수")
    object_storage_uri: Optional[str] = Field(None, description="Object Storage URI")

    created_at: Optional[datetime] = Field(None, description="생성 시간")
    updated_at: Optional[datetime] = Field(None, description="수정 시간")
    deleted_at: Optional[datetime] = Field(None, description="삭제 시간")
    created_by: Optional[str] = Field(None, description="생성자 member_id")
    updated_by: Optional[str] = Field(None, description="수정자 member_id")
    deleted_by: Optional[str] = Field(None, description="삭제자 member_id")


class ExternalKnowledgeBaseDetailResponse(BaseModel):
    """외부 API에서 반환되는 지식베이스 상세 응답"""

    model_config = ConfigDict(extra="ignore")

    id: int
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

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None

    files: List[KnowledgeBaseFileReadSchema] = Field(default_factory=list)


class ExternalKnowledgeBaseBriefResponse(BaseModel):
    """외부 API에서 반환되는 지식베이스 목록 응답"""

    model_config = ConfigDict(extra="ignore")

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


class KnowledgeBaseCreate(BaseModel):
    """지식베이스 생성 요청 (multipart/form-data)"""

    name: str = Field(..., description="Knowledge Base 이름")
    description: Optional[str] = Field(None, description="Knowledge Base 설명")
    language_id: int = Field(..., description="언어 ID")
    embedding_model_id: int = Field(..., description="임베딩 모델 ID")
    chunk_size: int = Field(..., ge=1, description="청크 크기")
    chunk_overlap: int = Field(..., ge=0, description="청크 오버랩 크기")
    chunk_type_id: int = Field(..., description="청크 타입 ID")
    search_method_id: int = Field(..., description="검색 방법 ID")
    top_k: int = Field(..., ge=1, description="검색 시 반환할 상위 k개 결과 수")
    threshold: float = Field(..., ge=0.0, le=1.0, description="검색 임계값 (0.0 ~ 1.0)")


class KnowledgeBaseUpdate(BaseModel):
    """지식베이스 수정 요청"""

    name: Optional[str] = Field(None, description="수정할 이름")
    description: Optional[str] = Field(None, description="수정할 설명")


class KnowledgeBaseResponse(BaseModel):
    """지식베이스 응답"""

    id: int = Field(..., description="Gateway Knowledge Base ID")
    surro_knowledge_id: int = Field(..., description="외부 Knowledge Base ID")
    created_at: datetime = Field(..., description="Gateway 생성 시간")
    updated_at: datetime = Field(..., description="Gateway 수정 시간")
    created_by: str = Field(..., description="생성자 member_id")

    name: str = Field(..., description="Knowledge Base 이름")
    description: Optional[str] = Field(None, description="Knowledge Base 설명")
    collection_name: str = Field(..., description="Milvus Collection 이름")

    chunk_size: Optional[int] = Field(None, description="청크 크기")
    chunk_overlap: Optional[int] = Field(None, description="청크 오버랩 크기")
    top_k: Optional[int] = Field(None, description="검색 시 반환할 상위 k개 결과 수")
    threshold: Optional[float] = Field(None, description="검색 임계값")


class KnowledgeBaseDetailResponse(BaseModel):
    """지식베이스 상세 응답"""

    id: int = Field(..., description="Gateway Knowledge Base ID")
    surro_knowledge_id: int = Field(..., description="외부 Knowledge Base ID")
    created_at: datetime = Field(..., description="Gateway 생성 시간")
    updated_at: datetime = Field(..., description="Gateway 수정 시간")
    created_by: str = Field(..., description="생성자 member_id")

    name: str = Field(..., description="Knowledge Base 이름")
    description: Optional[str] = Field(None, description="Knowledge Base 설명")
    collection_name: str = Field(..., description="Milvus Collection 이름")
    embedding_model_id: int = Field(..., description="임베딩 모델 ID")
    language_id: int = Field(..., description="언어 ID")
    chunk_size: int = Field(..., description="청크 크기")
    chunk_overlap: int = Field(..., description="청크 오버랩 크기")
    chunk_type_id: int = Field(..., description="청크 타입 ID")
    search_method_id: int = Field(..., description="검색 방법 ID")
    top_k: int = Field(..., description="검색 시 반환할 상위 k개 결과 수")
    threshold: float = Field(..., description="검색 임계값")
    files: List[KnowledgeBaseFileReadSchema] = Field(default_factory=list, description="파일 목록")


class KnowledgeBaseListResponse(BaseModel):
    """지식베이스 목록 응답"""

    data: List[KnowledgeBaseResponse] = Field(..., description="Knowledge Base 목록")
    total: int = Field(..., description="전체 항목 수")
    page: int = Field(..., description="현재 페이지 번호")
    size: int = Field(..., description="페이지당 항목 수")


class KnowledgeBaseSearchRequest(BaseModel):
    """지식베이스 검색 요청"""

    text: str = Field(..., description="검색할 쿼리 텍스트")


class SearchResultItem(BaseModel):
    """검색 결과 항목"""

    model_config = ConfigDict(extra="ignore")

    text: str = Field(..., description="검색된 문서 텍스트")
    score: float = Field(..., description="검색 점수 (유사도)")
    chunk_id: Optional[str] = Field(None, description="청크 ID")
    partition_name: Optional[str] = Field(None, description="Milvus Partition 이름")
    file_name: Optional[str] = Field(None, description="파일 이름")
    distance: Optional[float] = Field(None, description="거리 값")


class KnowledgeBaseSearchResponse(BaseModel):
    """지식베이스 검색 응답"""

    model_config = ConfigDict(extra="ignore")

    results: List[SearchResultItem] = Field(..., description="검색 결과 목록")
    total: int = Field(..., description="검색 결과 총 개수")
    search_method: str = Field(..., description="사용된 검색 방법 (dense/sparse/hybrid)")


class KnowledgeBaseSearchRecord(BaseModel):
    """지식베이스 검색 기록"""

    model_config = ConfigDict(extra="ignore")

    id: int = Field(..., description="검색 기록 ID")
    knowledge_base_id: int = Field(..., description="Knowledge Base ID")
    source: str = Field(..., description="Collection 이름")
    text: str = Field(..., description="검색 쿼리 텍스트")
    created_at: datetime = Field(..., description="검색 기록 생성 시간")
    updated_at: Optional[datetime] = Field(None, description="검색 기록 수정 시간")
    deleted_at: Optional[datetime] = Field(None, description="검색 기록 삭제 시간")
    created_by: Optional[str] = Field(None, description="생성자 member_id")
    updated_by: Optional[str] = Field(None, description="수정자 member_id")
    deleted_by: Optional[str] = Field(None, description="삭제자 member_id")


class ChunkTypeListResponse(BaseModel):
    """청크 타입 목록 응답"""

    data: List[ChunkTypeSchema] = Field(..., description="청크 타입 목록")
    total: int = Field(..., description="전체 항목 수")
    page: int = Field(..., description="현재 페이지 번호")
    size: int = Field(..., description="페이지당 항목 수")


class LanguageListResponse(BaseModel):
    """언어 목록 응답"""

    data: List[LanguageSchema] = Field(..., description="언어 목록")
    total: int = Field(..., description="전체 항목 수")
    page: int = Field(..., description="현재 페이지 번호")
    size: int = Field(..., description="페이지당 항목 수")


class SearchMethodListResponse(BaseModel):
    """검색 방법 목록 응답"""

    data: List[SearchMethodSchema] = Field(..., description="검색 방법 목록")
    total: int = Field(..., description="전체 항목 수")
    page: int = Field(..., description="현재 페이지 번호")
    size: int = Field(..., description="페이지당 항목 수")
