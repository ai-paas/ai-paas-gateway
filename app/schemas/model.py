from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Any, TYPE_CHECKING

from pydantic import AnyHttpUrl, AwareDatetime, BaseModel, Field, ConfigDict, model_validator

# 타입 체킹할 때만 import (순환 참조 방지)
if TYPE_CHECKING:
    pass

ACCESS_TOKEN_EXPIRE_MINUTES = 30


class PredefinedModelKey(str, Enum):
    """MLOps가 지원하는 사전 정의 모델 키."""

    YOLOS_TINY = "hustvl/yolos-tiny"
    YOLOS_SMALL = "hustvl/yolos-small"
    DETR_RESNET_50 = "facebook/detr-resnet-50"
    DETR_RESNET_101 = "facebook/detr-resnet-101"
    RF_DETR_LARGE = "Roboflow/rf-detr-large"
    RF_DETR_MEDIUM = "Roboflow/rf-detr-medium"
    MEDLLAMA3 = "ahmgam/medllama3-v20:latest"
    BGE_M3 = "bge-m3"
    ESM2_8M = "facebook/esm2_t6_8M_UR50D"
    RNAFM = "multimolecule/rnafm"
    MOLFORMER = "ibm-research/MoLFormer-XL-both-10pct"
    ESMC_300M = "biohub/ESMC-300M"
    ESMC_6B = "biohub/ESMC-6B"
    ESMFOLD2 = "biohub/ESMFold2"
    YOLOX_S = "yolox_s"
    YOLOX_M = "yolox_m"
    QWQ_32B = "qwq:32b"
    GPT_OSS_20B = "gpt-oss:20b"
    DEEPSEEK_R1_32B = "deepseek-r1:32b"
    GRANITE_4_1_30B = "granite4.1:30b"
    LFM2_24B = "lfm2:24b"
    GEMMA4_27B = "gemma4:27b"
    QWEN3_6_27B = "qwen3.6:27b"
    NEMOTRON3_33B = "nemotron3:33b"


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
    run_id: Optional[str] = None
    reference_model_id: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
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
    """API 요청용 모델 생성 스키마 (업데이트된 API 스펙)"""
    model_config = ConfigDict(protected_namespaces=())

    name: str = Field(..., description="모델 이름")
    description: Optional[str] = Field(None, description="모델 설명")
    repo_id: Optional[str] = Field(None, description="모델 저장소 ID")
    provider_id: int = Field(..., description="프로바이더 ID")
    type_id: int = Field(..., description="모델 타입 ID")
    format_id: int = Field(..., description="모델 포맷 ID")
    parent_model_id: Optional[int] = Field(None, description="부모 모델 ID (내부 시스템 전용)")
    task: Optional[str] = Field(
        None,
        max_length=500,
        description=(
            "모델 태스크: embedding | text-generation | object-detection | fill-mask | "
            "protein-classification | protein-structure-prediction | vqa"
        ),
    )
    parameter: Optional[str] = Field(None, max_length=100, description="모델 파라미터")
    sample_code: Optional[str] = Field(None, description="샘플 코드")
    model_registry_schema: Optional[str] = Field(None, description="모델 레지스트리 스키마 (내부 시스템 전용)")


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
    """모델 응답 (Surro API 형식) - 기존 데이터와 호환"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int  # Surro API의 모델 ID
    name: str
    description: Optional[str] = None  # Optional로 변경 (기존 데이터 호환)
    repo_id: Optional[str] = None  # 새 필드 추가 (기존 데이터 호환)
    provider_info: Optional[ProviderInfo] = None
    type_info: Optional[TypeInfo] = None
    format_info: Optional[FormatInfo] = None
    parent_model_id: Optional[int] = None
    task: Optional[str] = Field(
        None,
        description=(
            "모델 태스크: embedding | text-generation | object-detection | fill-mask | "
            "protein-classification | protein-structure-prediction | vqa"
        ),
    )
    parameter: Optional[str] = None  # 새 필드 추가
    sample_code: Optional[str] = None  # 새 필드 추가
    registry: Optional[ModelRegistry] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None
    learning_enable_yn: Optional[bool] = None
    opt_enable_yn: Optional[bool] = None
    visibility: Optional[str] = None
    recommended_hparams: Dict[str, str] = Field(default_factory=dict)
    parent_model: Optional[Dict[str, Any]] = None
    child_models: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class ModelCreateResponse(BaseModel):
    """모델 생성 응답 (새로운 API 스펙) - repo_id 필수"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int
    name: str
    description: Optional[str] = None
    repo_id: Optional[str] = None
    provider_info: Optional[ProviderInfo] = None
    type_info: Optional[TypeInfo] = None
    format_info: Optional[FormatInfo] = None
    parent_model_id: Optional[int] = None
    task: Optional[str] = Field(
        None,
        description=(
            "모델 태스크: embedding | text-generation | object-detection | fill-mask | "
            "protein-classification | protein-structure-prediction | vqa"
        ),
    )
    parameter: Optional[str] = None
    sample_code: Optional[str] = None
    registry: Optional[ModelRegistry] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None
    learning_enable_yn: Optional[bool] = None
    opt_enable_yn: Optional[bool] = None
    visibility: Optional[str] = None
    recommended_hparams: Dict[str, str] = Field(default_factory=dict)


class ModelFileStorageType(str, Enum):
    """MLOps 모델 파일 저장 유형."""

    MLFLOW = "MLFLOW"
    OLLAMA = "OLLAMA"
    NONE = "NONE"


class ModelFileEntry(BaseModel):
    """모델 아티팩트의 파일 항목."""

    name: str = Field(..., description="모델 저장 위치 기준 상대 경로")
    size_bytes: int = Field(..., ge=0, description="파일 크기(바이트)")
    last_modified: AwareDatetime = Field(..., description="UTC 기준 마지막 수정 시각")
    download_url: str = Field(
        ...,
        description="실제 다운로드 URL을 발급받는 Gateway API 상대 경로",
    )


class ModelFileListResponse(BaseModel):
    """MLOps 모델 파일 목록 응답."""

    model_id: int = Field(..., description="MLOps 모델 ID")
    model_name: str = Field(..., description="모델 표시 이름")
    storage_type: ModelFileStorageType = Field(..., description="모델 파일 저장 유형")
    location: Optional[str] = Field(
        None,
        description="MLflow 오브젝트 prefix 또는 Ollama 볼륨 이름",
    )
    files: List[ModelFileEntry] = Field(
        default_factory=list,
        description="파일 목록. 파일이 없으면 빈 배열",
    )
    next_cursor: Optional[str] = Field(
        None,
        description="다음 목록 요청에 그대로 전달할 불투명 cursor",
    )
    message: Optional[str] = Field(
        None,
        description="파일 목록이 비어 있을 때 사용자에게 표시할 안내 문구",
    )

    @model_validator(mode="after")
    def validate_file_state(self):
        if self.files:
            if self.storage_type != ModelFileStorageType.MLFLOW or self.message is not None:
                raise ValueError("files are only valid for MLFLOW responses without a message")
        else:
            if self.next_cursor is not None:
                raise ValueError("an empty file list cannot have a next_cursor")
        if self.storage_type == ModelFileStorageType.NONE and self.location is not None:
            raise ValueError("NONE storage must not expose a location")
        return self


class ModelFileListWrapper(BaseModel):
    """Gateway 공개 모델 파일 목록 응답."""

    data: List[ModelFileEntry] = Field(..., description="현재 페이지의 파일 목록")
    total: int = Field(..., ge=0, description="전체 파일 수")
    page: int = Field(..., ge=1, description="현재 페이지 번호")
    size: int = Field(..., ge=1, le=100, description="페이지당 항목 수")


class ModelFileDownloadUrlResponse(BaseModel):
    """모델 파일의 단기 서명 다운로드 URL 응답."""

    model_id: int = Field(..., description="MLOps 모델 ID")
    name: str = Field(..., description="모델 저장 위치 기준 상대 경로")
    size_bytes: int = Field(..., ge=0, description="파일 크기(바이트)")
    download_url: AnyHttpUrl = Field(
        ...,
        description="5분 동안 유효한 실제 스토리지 서명 URL",
    )
    expires_at: AwareDatetime = Field(..., description="서명 URL 만료 시각(UTC)")


class ModelBaseDeploymentStatusRequest(BaseModel):
    """내부 모델 기본 배포 상태 업데이트 요청."""

    service_name: str
    service_hostname: str
    status: str
    internal_url: Optional[str] = None
    error_message: Optional[str] = None


class InnoUserInfo(BaseModel):
    """사용자 정보"""
    member_id: str
    role: str
    name: str


class ModelWithMemberInfo(ModelResponse):
    member_info: InnoUserInfo


class ModelListWrapper(BaseModel):
    data: List[ModelResponse]
    total: int
    page: int
    size: int


class ModelProviderListWrapper(BaseModel):
    data: List[ProviderInfo]
    total: int
    page: int
    size: int


class ModelTypeListWrapper(BaseModel):
    data: List[TypeInfo]
    total: int
    page: int
    size: int


class ModelFormatListWrapper(BaseModel):
    data: List[FormatInfo]
    total: int
    page: int
    size: int


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


class InnoModelMapping(BaseModel):
    """Inno DB 모델 매핑 정보 (간소화된 버전)"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: int = Field(..., description="Inno DB 내부 ID")
    surro_model_id: int = Field(..., description="Surro API 모델 ID")
    name: Optional[str] = Field(None, description="모델 이름 (캐시용)")
    created_by: str = Field(..., description="생성자 member_id")
    created_at: datetime = Field(..., description="생성 시간")
    updated_at: datetime = Field(..., description="수정 시간")
    deleted_at: Optional[datetime] = Field(None, description="삭제 시간")
    is_active: bool = Field(True, description="활성화 상태")


class EnhancedModelResponse(BaseModel):
    """Surro API + Inno API 통합 응답"""
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    # Surro API 응답 (기존 ModelResponse)
    surro_data: ModelResponse = Field(..., description="외부 Surro API 응답")

    # Inno API 응답 (사용자 정보)
    inno_data: InnoUserInfo = Field(..., description="Inno Gateway 사용자 정보")

    # 추가 메타데이터 (선택적)
    ownership_verified: bool = Field(True, description="소유권 검증 완료 여부")


class EnhancedModelListResponse(BaseModel):
    """모델 목록 통합 응답"""
    models: List[EnhancedModelResponse]
    total: int
    page: int
    size: int
    # Inno API 정보도 포함
    inno_data: InnoUserInfo


class UserModelSummary(BaseModel):
    """사용자 모델 요약 정보"""
    member_id: str = Field(..., description="사용자 ID")
    total_models: int = Field(..., description="총 모델 수")
    active_models: int = Field(..., description="활성 모델 수")
    recent_models: List[int] = Field(..., description="최근 모델 ID 목록")
    created_at_range: Optional[Dict[str, datetime]] = Field(None, description="생성 시간 범위")


class ModelOwnershipRequest(BaseModel):
    """모델 소유권 확인 요청"""
    model_id: int = Field(..., description="확인할 모델 ID (Surro)")
    member_id: str = Field(..., description="확인할 사용자 ID")


class ModelOwnershipResponse(BaseModel):
    """모델 소유권 확인 응답"""
    model_id: int
    member_id: str
    is_owner: bool = Field(..., description="소유자 여부")
    mapping_exists: bool = Field(..., description="매핑 존재 여부")
    created_at: Optional[datetime] = Field(None, description="매핑 생성 시간")


class BatchModelRequest(BaseModel):
    """배치 모델 처리 요청"""
    model_ids: List[int] = Field(..., description="처리할 모델 ID 목록")
    operation: str = Field(..., description="수행할 작업 (get, delete, etc.)")
    parameters: Optional[Dict[str, Any]] = Field(None, description="추가 파라미터")


class BatchModelResponse(BaseModel):
    """배치 모델 처리 응답"""
    total_requested: int = Field(..., description="요청된 총 모델 수")
    successful: int = Field(..., description="성공한 모델 수")
    failed: int = Field(..., description="실패한 모델 수")
    results: List[Dict[str, Any]] = Field(..., description="개별 결과")
    errors: List[Dict[str, Any]] = Field(default_factory=list, description="오류 목록")


class ModelFilterRequest(BaseModel):
    """모델 필터링 요청"""
    model_config = ConfigDict(protected_namespaces=())

    member_id: Optional[str] = Field(None, description="특정 사용자 모델만 조회")
    provider_id: Optional[int] = Field(None, description="프로바이더 ID로 필터링")
    type_id: Optional[int] = Field(None, description="타입 ID로 필터링")
    format_id: Optional[int] = Field(None, description="포맷 ID로 필터링")
    search: Optional[str] = Field(None, description="이름 또는 설명 검색")
    is_active: Optional[bool] = Field(True, description="활성화 상태 필터")
    created_after: Optional[datetime] = Field(None, description="생성 시간 이후 필터")
    created_before: Optional[datetime] = Field(None, description="생성 시간 이전 필터")
    limit: int = Field(100, ge=1, le=1000, description="반환할 최대 항목 수")
    skip: int = Field(0, ge=0, description="건너뛸 항목 수")


class ModelStatistics(BaseModel):
    """모델 통계 정보"""
    total_models: int = Field(..., description="전체 모델 수")
    models_by_provider: Dict[str, int] = Field(..., description="프로바이더별 모델 수")
    models_by_type: Dict[str, int] = Field(..., description="타입별 모델 수")
    models_by_format: Dict[str, int] = Field(..., description="포맷별 모델 수")
    models_by_user: Dict[str, int] = Field(..., description="사용자별 모델 수")
    active_models: int = Field(..., description="활성 모델 수")
    inactive_models: int = Field(..., description="비활성 모델 수")
    recent_activity: Dict[str, int] = Field(..., description="최근 활동 통계")


class ModelSyncRequest(BaseModel):
    """모델 동기화 요청"""
    member_id: str = Field(..., description="동기화할 사용자 ID")
    force_sync: bool = Field(False, description="강제 동기화 여부")
    sync_deleted: bool = Field(False, description="삭제된 모델도 동기화")


class ModelSyncResponse(BaseModel):
    """모델 동기화 응답"""
    member_id: str
    synced_models: int = Field(..., description="동기화된 모델 수")
    new_mappings: int = Field(..., description="새로 생성된 매핑 수")
    updated_mappings: int = Field(..., description="업데이트된 매핑 수")
    removed_mappings: int = Field(..., description="제거된 매핑 수")
    errors: List[str] = Field(default_factory=list, description="동기화 오류 목록")
    sync_completed_at: datetime = Field(..., description="동기화 완료 시간")
