from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime


class DatasetBase(BaseModel):
    """데이터셋 기본 정보"""
    name: str = Field(..., description="데이터셋 이름")
    description: str = Field(..., description="데이터셋 설명")


class DatasetCreateRequest(BaseModel):
    """API 요청용 데이터셋 생성 스키마"""
    name: str = Field(..., description="데이터셋 이름")
    description: str = Field(..., description="데이터셋 설명")


class DatasetRegistryReadSchema(BaseModel):
    """데이터셋 레지스트리 정보"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    artifact_path: str
    uri: str
    dataset_id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    created_by: str = ""
    updated_by: str = ""
    deleted_by: str = ""


class DatasetReadSchema(BaseModel):
    """데이터셋 응답 (외부 API 형식)"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    name: str
    dataset_registry: DatasetRegistryReadSchema
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    created_by: str = ""
    updated_by: str = ""
    deleted_by: str = ""


class DatasetListResponse(BaseModel):
    """데이터셋 목록 응답"""
    data: List[DatasetReadSchema] = Field(..., description="데이터셋 목록")


class DatasetValidationResponse(BaseModel):
    """데이터셋 파일 검증 응답"""
    is_valid: bool = Field(..., description="검증 성공 여부")
    message: str = Field(..., description="검증 결과 메시지")
    details: Optional[Dict[str, Any]] = Field(None, description="상세 오류 정보")


class InnoUserInfo(BaseModel):
    """Inno Gateway 사용자 정보"""
    member_id: str = Field(..., description="사용자 ID")
    role: str = Field(..., description="사용자 역할")
    name: str = Field(..., description="사용자 이름")


class DatasetWithMemberInfo(DatasetReadSchema):
    """사용자 정보가 포함된 데이터셋"""
    member_info: InnoUserInfo


class DatasetListWrapper(BaseModel):
    """페이지네이션 정보가 포함된 데이터셋 목록"""
    data: List[DatasetWithMemberInfo]
    total: int
    page: int
    size: int


class InnoDatasetMapping(BaseModel):
    """Inno DB 데이터셋 매핑 정보"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int = Field(..., description="Inno DB 내부 ID")
    surro_dataset_id: int = Field(..., description="외부 API 데이터셋 ID")
    name: Optional[str] = Field(None, description="데이터셋 이름 (캐시용)")
    created_by: str = Field(..., description="생성자 member_id")
    created_at: datetime = Field(..., description="생성 시간")
    updated_at: datetime = Field(..., description="수정 시간")
    deleted_at: Optional[datetime] = Field(None, description="삭제 시간")
    is_active: bool = Field(True, description="활성화 상태")


class EnhancedDatasetResponse(BaseModel):
    """외부 API + Inno API 통합 응답"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    # 외부 API 응답
    surro_data: DatasetReadSchema = Field(..., description="외부 API 응답")

    # Inno API 응답 (사용자 정보)
    inno_data: InnoUserInfo = Field(..., description="Inno Gateway 사용자 정보")

    # 추가 메타데이터
    ownership_verified: bool = Field(True, description="소유권 검증 완료 여부")