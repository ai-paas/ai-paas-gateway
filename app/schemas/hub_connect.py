from pydantic import BaseModel, Field, ConfigDict, model_validator
from typing import List, Optional, Dict, Any, Union
from datetime import datetime


class ModelListParams(BaseModel):
    """모델 목록 조회 파라미터"""
    market: Optional[str] = Field("huggingface", description="모델 마켓")
    sort: Optional[str] = Field("downloads", description="정렬 방식 (downloads, created, relevance)")
    page: Optional[int] = Field(1, ge=1, description="페이지 번호")
    limit: Optional[int] = Field(30, ge=1, le=100, description="페이지 당 항목 수")


class HubModelResponse(BaseModel):
    # 외부 API 필드들
    mongo_id: Optional[str] = Field(None, alias="_id", description="MongoDB ObjectID")
    id: str = Field(..., description="모델 ID")
    modelId: Optional[str] = Field(None, description="모델 ID (중복)")
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
    library_name: Optional[str] = Field(None, description="라이브러리 이름")

    # 상태 정보
    private: Optional[bool] = Field(False, description="비공개 여부")
    gated: Optional[bool] = Field(False, description="게이트 여부")
    sha: Optional[str] = Field(None, description="SHA 해시")


class ModelListResponse(BaseModel):
    """모델 목록 응답"""
    data: List[HubModelResponse] = Field(..., description="모델 목록")
    total: Optional[int] = Field(None, description="총 모델 수")
    page: int = Field(1, description="현재 페이지")
    limit: int = Field(30, description="페이지 당 항목 수")


class ModelFileInfo(BaseModel):
    """모델 파일 정보"""
    name: str = Field(..., description="파일명")
    size: Optional[str] = Field(None, description="파일 크기")
    blob_id: Optional[str] = Field(None, description="")


class ModelFilesResponse(BaseModel):
    """모델 파일 목록 응답"""
    data: List[ModelFileInfo] = Field(..., description="파일 목록")


class ModelDownloadResponse(BaseModel):
    """모델 다운로드 응답"""
    download_url: str = Field(..., description="다운로드 URL")
    filename: str = Field(..., description="파일명")
    model_id: str = Field(..., description="모델 ID")
    file_size: Optional[int] = Field(None, description="파일 크기")


class HubUserInfo(BaseModel):
    """허브 연결 사용자 정보"""
    member_id: str = Field(..., description="사용자 ID")
    role: str = Field(..., description="사용자 역할")
    name: str = Field(..., description="사용자 이름")

class HubModelListWrapper(BaseModel):
    """허브 모델 목록 래퍼"""
    data: List[HubModelResponse] = Field(..., description="모델 목록")
    pagination: Optional[Dict[str, Any]] = Field(None, description="페이지네이션 정보")


class HubModelFilesWrapper(BaseModel):
    """허브 모델 파일 목록 래퍼"""
    data: List[ModelFileInfo] = Field(..., description="파일 목록")


class HubModelDownloadWrapper(BaseModel):
    """허브 모델 다운로드 래퍼"""
    download_url: str = Field(..., description="다운로드 URL")
    filename: str = Field(..., description="파일명")
    model_id: str = Field(..., description="모델 ID")
    file_size: Optional[int] = Field(None, description="파일 크기")
    user_info: HubUserInfo = Field(..., description="사용자 정보")

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

class TagsParams(BaseModel):
    """태그 조회 파라미터"""
    market: Optional[str] = Field("huggingface", description="모델 마켓")