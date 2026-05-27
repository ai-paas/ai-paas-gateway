from datetime import datetime
from typing import List, Optional, Dict, Any, Union

from pydantic import BaseModel, Field, ConfigDict, model_validator, field_validator


class ModelListParams(BaseModel):
    """모델 목록 조회 파라미터"""
    market: Optional[str] = Field("huggingface", description="모델 마켓")
    sort: Optional[str] = Field("downloads", description="정렬 방식 (downloads, created, relevance)")
    page: Optional[int] = Field(1, ge=1, description="페이지 번호")
    limit: Optional[int] = Field(30, ge=1, le=100, description="페이지 당 항목 수")
    search: Optional[str] = Field(None, description="검색 키워드")
    num_parameters_min: Optional[str] = Field(None, description="Minimum parameters (e.g., '3B', '7B', '24B')")
    num_parameters_max: Optional[str] = Field(None, description="Maximum parameters (e.g., '128B', '256B')")

    # 추가 필터 파라미터들
    task: Optional[str] = Field(None, description="Filter by task (single selection, mapped to pipeline_tag in external API)")
    library: Optional[List[str]] = Field(None, description="Filter by library (multiple allowed, e.g., transformers, peft)")
    language: Optional[List[str]] = Field(None, description="Filter by language (multiple allowed, e.g., en, ru, multilingual)")
    license: Optional[str] = Field(None, description="Filter by license (single selection, e.g., license:apache-2.0)")
    apps: Optional[List[str]] = Field(None, description="Filter by apps (multiple allowed, e.g., llama.cpp, lmstudio)")
    inference_provider: Optional[List[str]] = Field(None, description="Filter by inference provider (multiple allowed, e.g., novita, nebius)")
    other: Optional[List[str]] = Field(None, description="Other filters (multiple allowed, e.g., endpoints_compatible, 4-bit)")


class HubModelResponse(BaseModel):
    """허브 모델 응답 (단순화된 구조)"""
    # 기본 식별 정보
    mongo_id: Optional[str] = Field(None, alias="_id", description="MongoDB ObjectID")
    id: str = Field(..., description="모델 ID")
    modelId: Optional[str] = Field(None, description="모델 ID (id와 동일)")
    author: Optional[str] = Field(None, description="모델 작성자")

    # 시간 정보
    createdAt: Optional[Union[str, datetime]] = Field(None, description="생성 시간")
    lastModified: Optional[Union[str, datetime]] = Field(None, description="마지막 수정 시간")

    # 통계 정보
    downloads: Optional[int] = Field(None, description="다운로드 수")
    likes: Optional[int] = Field(None, description="좋아요 수")

    # 메타데이터
    tags: Optional[List[str]] = Field(default_factory=list, description="모델 태그")
    pipeline_tag: Optional[str] = Field(None, description="파이프라인 태그")
    task: Optional[str] = Field(None, description="태스크 (pipeline_tag와 동일)")
    library_name: Optional[str] = Field(None, description="라이브러리 이름")

    # 파라미터 정보
    numParameters: Optional[int] = Field(None, description="파라미터 수")
    parameterDisplay: Optional[str] = Field(None, description="파라미터 표시 (예: 22.7M)")
    parameterRange: Optional[str] = Field(None, description="파라미터 범위 (예: small)")

    # 상태 정보
    private: Optional[bool] = Field(False, description="비공개 여부")
    gated: Optional[Union[bool, str]] = Field(None, description="게이트 여부")
    sha: Optional[str] = Field(None, description="SHA 해시")

    model_config = ConfigDict(populate_by_name=True)

    @field_validator('modelId', mode='before')
    @classmethod
    def set_model_id_from_id(cls, v, info):
        """modelId가 없으면 id 값으로 설정"""
        if v is None and 'id' in info.data:
            return info.data.get('id')
        return v

    @field_validator('gated', mode='before')
    @classmethod
    def normalize_gated(cls, v):
        """gated 필드를 정규화"""
        if v is None:
            return None
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            return v.lower() == "true"
        return bool(v)

    @field_validator('task', mode='before')
    @classmethod
    def set_task_from_pipeline_tag(cls, v, info):
        """task가 없으면 pipeline_tag 값으로 설정"""
        if v is None and 'pipeline_tag' in info.data:
            return info.data.get('pipeline_tag')
        return v


class ModelListResponse(BaseModel):
    """모델 목록 응답"""
    data: List[HubModelResponse] = Field(..., description="모델 목록")
    total: Optional[int] = Field(None, description="총 모델 수")
    page: int = Field(1, description="현재 페이지")
    limit: int = Field(30, description="페이지 당 항목 수")
    has_more: Optional[bool] = Field(None, description="다음 페이지 존재 가능성 (Kaggle 등 하한값 total을 쓰는 마켓에서 의미 있음)")
    total_is_exact: Optional[bool] = Field(None, description="total이 정확한 전체 수인지 여부 (HF=true, Kaggle=false)")
    applied_filters: Optional[Dict[str, Any]] = Field(None, description="실제 업스트림에 적용된 필터 정보 (일부 마켓에서만 제공)")


class ModelFileInfo(BaseModel):
    """모델 파일 정보"""
    name: str = Field(..., description="파일명")
    size: Optional[str] = Field(None, description="파일 크기")
    blob_id: Optional[str] = Field(None, description="")


class ModelFilesResponse(BaseModel):
    """모델 파일 목록 응답"""
    data: List[ModelFileInfo] = Field(..., description="파일 목록")

class HubUserInfo(BaseModel):
    """허브 연결 사용자 정보"""
    member_id: str = Field(..., description="사용자 ID")
    role: str = Field(..., description="사용자 역할")
    name: str = Field(..., description="사용자 이름")

class ModelListPagination(BaseModel):
    """허브 모델 목록 페이지네이션 정보"""
    total: Optional[int] = Field(None, description="전체 모델 수 또는 하한값 (total_is_exact=false일 때 '최소 이만큼')")
    page: int = Field(1, description="현재 페이지")
    limit: int = Field(30, description="페이지당 항목 수")
    has_more: Optional[bool] = Field(None, description="다음 페이지 존재 가능성")
    total_is_exact: Optional[bool] = Field(None, description="total이 정확한 전체 수인지 여부 (HuggingFace=true, Kaggle=false)")
    applied_filters: Optional[Dict[str, Any]] = Field(None, description="실제 업스트림에 적용된 필터 정보 (일부 마켓에서만 제공)")


class HubModelListWrapper(BaseModel):
    """허브 모델 목록 래퍼"""
    data: List[HubModelResponse] = Field(..., description="모델 목록")
    pagination: Optional[ModelListPagination] = Field(None, description="페이지네이션 정보")


class HubModelFilesWrapper(BaseModel):
    """허브 모델 파일 목록 래퍼"""
    data: List[ModelFileInfo] = Field(..., description="파일 목록")


class ModelDownloadResponse(BaseModel):
    """모델 파일 다운로드 결과 응답"""
    download_type: str = Field(..., description="다운로드 처리 방식")
    file_path: str = Field(..., description="서버에 저장된 파일 경로")
    file_size: int = Field(..., description="저장된 파일 크기(byte)")
    filename: str = Field(..., description="다운로드한 파일명")
    model_id: str = Field(..., description="대상 모델 ID")

class ExtendedHubModelResponse(BaseModel):
    # 외부 API 필드들
    id: str = Field(..., description="모델 ID")
    downloads: Optional[int] = Field(None, description="다운로드 수")
    likes: Optional[int] = Field(None, description="좋아요 수")
    lastModified: Optional[Union[str, datetime]] = Field(None, description="마지막 수정 시간")
    pipeline_tag: Optional[str] = Field(None, description="파이프라인 태그")
    tags: Optional[List[str]] = Field(default_factory=list, description="모델 태그")
    base_model: Optional[str] = Field(None, description="베이스 모델")
    language: Optional[Union[str, List[str]]] = Field(default_factory=list, description="지원 언어")
    datasets: Optional[List[str]] = Field(default_factory=list, description="학습/사용 데이터셋 목록")
    library_name: Optional[str] = Field(None, description="라이브러리 이름")
    license: Optional[str] = Field(None, description="라이선스")
    license_link: Optional[str] = Field(None, description="라이선스 링크")
    card_html: Optional[str] = Field(None, description="모델 카드 HTML 내용")
    variation_resolved: Optional[bool] = Field(
        None,
        description="(Kaggle 전용) 요청 핸들의 framework/variation 메타가 exact match로 해결되었는지 여부. false면 모델 레벨 정보로 폴백."
    )

    # 업스트림 마켓 카드 메타데이터의 추가 필드를 그대로 pass-through (HF/Kaggle 공통 확장 포인트)
    model_config = ConfigDict(extra="allow")

    def dict(self, *args, **kwargs):
        data = super().dict(*args, **kwargs)
        if isinstance(data.get("language"), str):
            data["language"] = [data["language"]]
        return data


class TagItem(BaseModel):
    """태그 아이템"""
    id: str = Field(..., description="태그 ID")
    label: str = Field(..., description="태그 라벨")
    type: str = Field(..., description="태그 타입")


class TagListParams(BaseModel):
    """동적 태그 리스트 파라미터"""
    model_config = ConfigDict(extra="allow")  # 추가 필드 허용

    @model_validator(mode="before")
    def validate_all_fields(cls, values):
        """모든 필드가 TagItem 리스트 형태인지 검증"""
        if isinstance(values, dict):
            validated_values = {}
            for key, value in values.items():
                if isinstance(value, list):
                    validated_items = []
                    for item in value:
                        if isinstance(item, dict):
                            validated_items.append(TagItem(**item))
                        elif isinstance(item, TagItem):
                            validated_items.append(item)
                        else:
                            raise ValueError(
                                f"Invalid item type in {key}: {type(item)}"
                            )
                    validated_values[key] = validated_items
                else:
                    raise ValueError(f"Field {key} must be a list")
            return validated_values
        return values

    def get_category(self, category_name: str) -> List[TagItem]:
        """특정 카테고리의 태그들을 가져오기"""
        if hasattr(self, "__pydantic_extra__") and self.__pydantic_extra__:
            if category_name in self.__pydantic_extra__:
                return self.__pydantic_extra__[category_name]
        return getattr(self, category_name, [])

    def get_all_categories(self) -> Dict[str, List[TagItem]]:
        """모든 카테고리와 태그들을 딕셔너리로 반환"""
        return self.model_dump()


class TagListResponse(BaseModel):
    data: List[Dict[str, List[TagItem]]] = Field(...)

class TagGroupResponse(BaseModel):
    """특정 그룹의 태그 리스트 응답"""
    data: List[TagItem] = Field(..., description="태그 목록")
    remaining_count: int = Field(0, description="남은 태그 개수")


class TagGroupAllResponse(BaseModel):
    """특정 태그 그룹 전체 조회 응답"""
    data: List[TagItem] = Field(..., description="태그 전체 목록")

class TagsParams(BaseModel):
    """태그 조회 파라미터"""
    market: Optional[str] = Field("huggingface", description="모델 마켓")


# ===== Datasets =====

class DatasetListParams(BaseModel):
    """데이터셋 목록 조회 파라미터 (공개 API는 page/size 사용, 서비스에서 limit로 변환)"""
    market: Optional[str] = Field("huggingface", description="대상 마켓")
    query: Optional[str] = Field(None, description="검색어")
    sort: Optional[str] = Field("likes", description="정렬 기준")
    page: Optional[int] = Field(1, ge=1, description="페이지 번호")
    size: Optional[int] = Field(20, ge=1, le=100, description="페이지당 항목 수")


class HubDatasetItem(BaseModel):
    """데이터셋 목록 아이템"""
    id: str = Field(..., description="데이터셋 식별자")
    author: Optional[str] = Field(None, description="작성자")
    downloads: Optional[int] = Field(None, description="다운로드 수")
    likes: Optional[int] = Field(None, description="좋아요 수")
    lastModified: Optional[Union[str, datetime]] = Field(None, description="마지막 수정 시각")
    gated: Optional[Union[bool, str]] = Field(None, description="접근 제한 여부")
    private: Optional[bool] = Field(None, description="비공개 여부")
    repoType: Optional[str] = Field(None, description="저장소 타입")

    model_config = ConfigDict(extra="allow")


class DatasetListResponse(BaseModel):
    """데이터셋 목록 응답 (게이트웨이 공개 계약: data/total/page/size)"""
    data: List[HubDatasetItem] = Field(..., description="데이터셋 목록")
    total: Optional[int] = Field(None, description="전체 개수 또는 하한값 (total_is_exact=false일 때는 '최소 이만큼'의 의미)")
    page: int = Field(1, description="현재 페이지")
    size: int = Field(20, description="페이지당 항목 수")
    has_more: Optional[bool] = Field(None, description="다음 페이지 존재 가능성")
    total_is_exact: Optional[bool] = Field(None, description="total이 정확한 전체 수인지 여부 (HF=true, Kaggle=false)")


class DatasetInfoResponse(BaseModel):
    """데이터셋 상세 응답"""
    dataset_info: Dict[str, Any] = Field(default_factory=dict, description="설정별 데이터셋 상세 정보 (Kaggle은 features/splits 메타가 없어 항상 빈 객체)")
    pending: List[str] = Field(default_factory=list, description="아직 준비 중인 항목 목록")
    failed: List[Any] = Field(default_factory=list, description="조회 실패 항목 목록")
    partial: Optional[bool] = Field(None, description="일부만 조회되었는지 여부 (Kaggle은 항상 true)")
    cardData: Optional[Dict[str, Any]] = Field(None, description="README 카드 메타데이터")

    model_config = ConfigDict(extra="allow")


class DatasetFileInfo(BaseModel):
    """데이터셋 파일 정보"""
    name: str = Field(..., description="파일명 또는 저장소 내 경로")
    size: Optional[str] = Field(None, description="사람이 읽기 쉬운 파일 크기")
    blob_id: Optional[str] = Field(None, description="파일 blob 식별자 (Kaggle은 항상 null)")


class DatasetFilesResponse(BaseModel):
    """데이터셋 파일 목록 응답"""
    data: List[DatasetFileInfo] = Field(..., description="파일 목록")


class DatasetSnapshotDownloadResponse(BaseModel):
    """데이터셋 스냅샷 다운로드 결과 (download_dir 지정 시)"""
    download_type: str = Field(..., description="다운로드 방식")
    snapshot_path: Optional[str] = Field(None, description="저장된 스냅샷 경로")
    repo_id: str = Field(..., description="대상 데이터셋 ID")
    total_files: Optional[int] = Field(None, description="저장된 파일 수")
    message: Optional[str] = Field(None, description="캐시 다운로드 시 안내 메시지")
    filters_applied: Optional[bool] = Field(None, description="(Kaggle 전용) allow/ignore 패턴이 실제 적용되었는지 여부")
