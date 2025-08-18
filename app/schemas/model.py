from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from datetime import datetime

# 타입 체킹할 때만 import (순환 참조 방지)
if TYPE_CHECKING:
    pass

ACCESS_TOKEN_EXPIRE_MINUTES = 30


class ProviderInfo(BaseModel):
    """프로바이더 정보"""
    id: int
    name: str
    description: Optional[str] = None


class TypeInfo(BaseModel):
    """모델 타입 정보"""
    id: int
    name: str
    description: Optional[str] = None


class FormatInfo(BaseModel):
    """모델 포맷 정보"""
    id: int
    name: str
    description: Optional[str] = None


class ModelRegistry(BaseModel):
    """모델 레지스트리 정보"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    artifact_path: str
    uri: str
    reference_model_id: int
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str] = None
    updated_by: Optional[str] = None


class ModelBase(BaseModel):
    """모델 기본 정보"""
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(..., description="모델 이름")
    description: str = Field(..., description="모델 설명")
    provider_id: int = Field(..., description="프로바이더 ID")
    type_id: int = Field(..., description="모델 타입 ID")
    format_id: int = Field(..., description="모델 포맷 ID")
    parent_model_id: Optional[int] = Field(None, description="부모 모델 ID")


class ModelCreate(ModelBase):
    """모델 생성 요청"""
    registry_schema: Optional[str] = Field(None, description="모델 레지스트리 스키마")
    file: Optional[bytes] = Field(None, description="모델 파일 (바이너리)")


class ModelCreateRequest(BaseModel):
    """API 요청용 모델 생성 스키마"""
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(..., description="모델 이름")
    description: str = Field(..., description="모델 설명")
    provider_id: int = Field(..., description="프로바이더 ID")
    type_id: int = Field(..., description="모델 타입 ID")
    format_id: int = Field(..., description="모델 포맷 ID")
    parent_model_id: Optional[int] = Field(None, description="부모 모델 ID")
    registry_schema: Optional[str] = Field(None, description="모델 레지스트리 스키마")


class ModelUpdate(BaseModel):
    """모델 수정 요청"""
    model_config = ConfigDict(protected_namespaces=())

    name: Optional[str] = Field(None, description="모델 이름")
    description: Optional[str] = Field(None, description="모델 설명")
    provider_id: Optional[int] = Field(None, description="프로바이더 ID")
    type_id: Optional[int] = Field(None, description="모델 타입 ID")
    format_id: Optional[int] = Field(None, description="모델 포맷 ID")
    parent_model_id: Optional[int] = Field(None, description="부모 모델 ID")
    registry_schema: Optional[str] = Field(None, description="모델 레지스트리 스키마")


class ModelResponse(BaseModel):
    """모델 응답"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    name: str
    description: str
    provider_info: Optional[ProviderInfo] = None
    type_info: Optional[TypeInfo] = None
    format_info: Optional[FormatInfo] = None
    parent_model_id: Optional[int] = None
    registry: Optional[ModelRegistry] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None


class ModelDetailResponse(ModelResponse):
    """상세 모델 응답 (추후 확장용)"""
    pass


class ModelListResponse(BaseModel):
    """모델 목록 응답"""
    models: List[ModelResponse]
    total: int
    page: int
    size: int


class ExternalModelResponse(BaseModel):
    """외부 API 모델 응답 포맷"""
    model_config = ConfigDict(protected_namespaces=())

    id: int
    name: str
    description: str
    provider_info: ProviderInfo
    type_info: TypeInfo
    format_info: FormatInfo
    parent_model_id: Optional[int] = None
    registry: Optional[ModelRegistry] = None
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None
    created_by: str = ""
    updated_by: str = ""
    deleted_by: str = ""


class ModelTestRequest(BaseModel):
    """모델 테스트 요청"""
    model_config = ConfigDict(protected_namespaces=())

    target_id: int = Field(..., description="테스트할 모델 ID")
    input_data: Dict[str, Any] = Field(..., description="테스트 입력 데이터")
    parameters: Optional[Dict[str, Any]] = Field(None, description="추가 파라미터")


class ModelTestResponse(BaseModel):
    """모델 테스트 응답"""
    model_config = ConfigDict(protected_namespaces=())

    target_id: int
    status: str
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None