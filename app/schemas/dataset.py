from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional, Dict, Any
from datetime import datetime


class DatasetBase(BaseModel):
    """데이터셋 기본 정보"""
    name: str = Field(..., description="데이터셋 이름")
    description: str = Field(..., description="데이터셋 설명")


class DatasetCreate(DatasetBase):
    """데이터셋 생성 요청"""
    file: Optional[bytes] = Field(None, description="데이터셋 파일 (바이너리)")


class DatasetCreateRequest(BaseModel):
    """API 요청용 데이터셋 생성 스키마"""
    name: str = Field(..., description="데이터셋 이름")
    description: str = Field(..., description="데이터셋 설명")


class DatasetUpdate(BaseModel):
    """데이터셋 수정 요청"""
    name: Optional[str] = Field(None, description="데이터셋 이름")
    description: Optional[str] = Field(None, description="데이터셋 설명")

class DatasetRegistry(BaseModel):
    """데이터셋 레지스트리 정보"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    artifact_path: str
    uri: str
    dataset_id: int
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None

class DatasetResponse(BaseModel):
    """데이터셋 응답 (Surro API 형식)"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    name: str
    description: Optional[str] = None
    version: int
    subversion: int
    train_ratio: float
    validation_ratio: float
    test_ratio: float
    dataset_registry: DatasetRegistry

    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None


class DatasetDetailResponse(DatasetResponse):
    """상세 데이터셋 응답 (추후 확장용)"""
    pass


class DatasetListResponse(BaseModel):
    """데이터셋 목록 응답"""
    datasets: List[DatasetResponse]
    total: int
    page: int
    size: int


class ExternalDatasetResponse(BaseModel):
    """외부 API 데이터셋 응답 포맷"""
    id: int
    name: str
    description: Optional[str] = None
    created_at: str
    updated_at: str
    deleted_at: Optional[str] = None
    created_by: str = ""
    updated_by: str = ""
    deleted_by: str = ""


class InnoUserInfo(BaseModel):
    """Inno Gateway 사용자 정보"""
    member_id: str = Field(..., description="사용자 ID")
    role: str = Field(..., description="사용자 역할")
    name: str = Field(..., description="사용자 이름")

class DatasetWithMemberInfo(DatasetResponse):
    member_info: InnoUserInfo

class DatasetListWrapper(BaseModel):
    data: List[DatasetWithMemberInfo]


class InnoDatasetMapping(BaseModel):
    """Inno DB 데이터셋 매핑 정보"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int = Field(..., description="Inno DB 내부 ID")
    surro_dataset_id: int = Field(..., description="Surro API 데이터셋 ID")
    name: Optional[str] = Field(None, description="데이터셋 이름 (캐시용)")
    created_by: str = Field(..., description="생성자 member_id")
    created_at: datetime = Field(..., description="생성 시간")
    updated_at: datetime = Field(..., description="수정 시간")
    deleted_at: Optional[datetime] = Field(None, description="삭제 시간")
    is_active: bool = Field(True, description="활성화 상태")


class EnhancedDatasetResponse(BaseModel):
    """Surro API + Inno API 통합 응답"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    # Surro API 응답 (기존 DatasetResponse)
    surro_data: DatasetResponse = Field(..., description="외부 Surro API 응답")

    # Inno API 응답 (사용자 정보)
    inno_data: InnoUserInfo = Field(..., description="Inno Gateway 사용자 정보")

    # 추가 메타데이터 (선택적)
    ownership_verified: bool = Field(True, description="소유권 검증 완료 여부")


class EnhancedDatasetListResponse(BaseModel):
    """데이터셋 목록 통합 응답"""
    datasets: List[EnhancedDatasetResponse]
    total: int
    page: int
    size: int
    # Inno API 정보도 포함
    inno_data: InnoUserInfo


class UserDatasetSummary(BaseModel):
    """사용자 데이터셋 요약 정보"""
    member_id: str = Field(..., description="사용자 ID")
    total_datasets: int = Field(..., description="총 데이터셋 수")
    active_datasets: int = Field(..., description="활성 데이터셋 수")
    recent_datasets: List[int] = Field(..., description="최근 데이터셋 ID 목록")
    created_at_range: Optional[Dict[str, datetime]] = Field(None, description="생성 시간 범위")


class DatasetOwnershipRequest(BaseModel):
    """데이터셋 소유권 확인 요청"""
    dataset_id: int = Field(..., description="확인할 데이터셋 ID (Surro)")
    member_id: str = Field(..., description="확인할 사용자 ID")


class DatasetOwnershipResponse(BaseModel):
    """데이터셋 소유권 확인 응답"""
    dataset_id: int
    member_id: str
    is_owner: bool = Field(..., description="소유자 여부")
    mapping_exists: bool = Field(..., description="매핑 존재 여부")
    created_at: Optional[datetime] = Field(None, description="매핑 생성 시간")


class BatchDatasetRequest(BaseModel):
    """배치 데이터셋 처리 요청"""
    dataset_ids: List[int] = Field(..., description="처리할 데이터셋 ID 목록")
    operation: str = Field(..., description="수행할 작업 (get, delete, etc.)")
    parameters: Optional[Dict[str, Any]] = Field(None, description="추가 파라미터")


class BatchDatasetResponse(BaseModel):
    """배치 데이터셋 처리 응답"""
    total_requested: int = Field(..., description="요청된 총 데이터셋 수")
    successful: int = Field(..., description="성공한 데이터셋 수")
    failed: int = Field(..., description="실패한 데이터셋 수")
    results: List[Dict[str, Any]] = Field(..., description="개별 결과")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="오류 목록")


class DatasetFilterRequest(BaseModel):
    """데이터셋 필터링 요청"""
    member_id: Optional[str] = Field(None, description="특정 사용자 데이터셋만 조회")
    search: Optional[str] = Field(None, description="이름 또는 설명 검색")
    is_active: Optional[bool] = Field(True, description="활성화 상태 필터")
    created_after: Optional[datetime] = Field(None, description="생성 시간 이후 필터")
    created_before: Optional[datetime] = Field(None, description="생성 시간 이전 필터")
    limit: int = Field(100, ge=1, le=1000, description="반환할 최대 항목 수")
    skip: int = Field(0, ge=0, description="건너뛸 항목 수")


class DatasetStatistics(BaseModel):
    """데이터셋 통계 정보"""
    total_datasets: int = Field(..., description="전체 데이터셋 수")
    datasets_by_user: Dict[str, int] = Field(..., description="사용자별 데이터셋 수")
    active_datasets: int = Field(..., description="활성 데이터셋 수")
    inactive_datasets: int = Field(..., description="비활성 데이터셋 수")
    recent_activity: Dict[str, int] = Field(..., description="최근 활동 통계")


class DatasetSyncRequest(BaseModel):
    """데이터셋 동기화 요청"""
    member_id: str = Field(..., description="동기화할 사용자 ID")
    force_sync: bool = Field(False, description="강제 동기화 여부")
    sync_deleted: bool = Field(False, description="삭제된 데이터셋도 동기화")


class DatasetSyncResponse(BaseModel):
    """데이터셋 동기화 응답"""
    member_id: str
    synced_datasets: int = Field(..., description="동기화된 데이터셋 수")
    new_mappings: int = Field(..., description="새로 생성된 매핑 수")
    updated_mappings: int = Field(..., description="업데이트된 매핑 수")
    removed_mappings: int = Field(..., description="제거된 매핑 수")
    errors: List[str] = Field(default_factory=list, description="동기화 오류 목록")
    sync_completed_at: datetime = Field(..., description="동기화 완료 시간")