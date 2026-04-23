import logging
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Response, status, Query, Path

from app.auth import get_current_user
from app.models import Member
from app.schemas.hub_connect import (
    ModelListParams, HubModelListWrapper, ModelListPagination, HubUserInfo,
    ExtendedHubModelResponse, HubModelFilesWrapper, ModelDownloadResponse,
    TagListResponse, TagGroupResponse, TagGroupAllResponse,
    DatasetListParams, DatasetListResponse,
    DatasetInfoResponse, DatasetFilesResponse, DatasetSnapshotDownloadResponse,
)
from app.services.hub_connect_service import hub_connect_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hub-connect", tags=["Hub Connect"])

# Swagger UI에서 market 파라미터에 드롭다운 예시를 제공하기 위한 공통 OpenAPI examples.
# huggingface/kaggle을 한 번의 클릭으로 값 채우기 가능.
_MARKET_EXAMPLES = {
    "huggingface": {"summary": "HuggingFace", "value": "huggingface"},
    "kaggle": {"summary": "Kaggle", "value": "kaggle"},
}


def _create_hub_user_info(user: Member) -> HubUserInfo:
    """Member 객체에서 HubUserInfo 생성"""
    return HubUserInfo(
        member_id=user.member_id,
        role=user.role,
        name=user.name
    )


def _create_user_info_dict(user: Member) -> dict:
    """Member 객체에서 user_info 딕셔너리 생성"""
    return {
        'member_id': user.member_id,
        'role': user.role,
        'name': user.name
    }


@router.get(
    "/models",
    response_model=HubModelListWrapper,
    summary="모델 목록 조회",
    description="마켓별 모델 목록을 조회하거나 검색합니다.\n\n"
                "정렬값이 `trending`이면 트렌딩 조회 로직을 사용하고, 그 외에는 일반 검색 로직을 사용합니다.\n\n"
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| market | query | Y | 대상 마켓 이름입니다. | huggingface |\n"
                "| search | query | N | 검색어입니다. 외부 API의 `query` 파라미터로 전달됩니다. | llama |\n"
                "| sort | query | N | 정렬 기준입니다. | downloads |\n"
                "| page | query | N | 페이지 번호입니다. 1부터 시작합니다. | 1 |\n"
                "| limit | query | N | 페이지당 최대 조회 개수입니다. | 30 |\n"
                "| num_parameters_min | query | N | 최소 파라미터 범위입니다. | 7B |\n"
                "| num_parameters_max | query | N | 최대 파라미터 범위입니다. | 70B |\n"
                "| task | query | N | 단일 파이프라인 태그 필터입니다. 외부 API의 `pipeline_tag`로 전달됩니다. | text-generation |\n"
                "| library | query | N | 다중 라이브러리 필터입니다. | transformers |\n"
                "| language | query | N | 다중 언어 필터입니다. | en |\n"
                "| license | query | N | 단일 라이선스 필터입니다. | apache-2.0 |\n"
                "| apps | query | N | 다중 앱 필터입니다. | llama.cpp |\n"
                "| inference_provider | query | N | 다중 추론 제공자 필터입니다. | nebius |\n"
                "| other | query | N | 기타 다중 필터입니다. | 4-bit |\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| data | 모델 목록입니다. |\n"
                "| pagination.total | 전체 모델 수입니다. |\n"
                "| pagination.page | 현재 페이지 번호입니다. |\n"
                "| pagination.limit | 페이지당 조회 개수입니다. |\n\n"
                "data 내부 공통 필드:\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| id | 모델 식별자입니다. |\n"
                "| downloads | 다운로드 수입니다. |\n"
                "| likes | 좋아요 수입니다. |\n"
                "| lastModified | 마지막 수정 시각입니다. |\n"
                "| pipeline_tag | 대표 태스크 태그입니다. |\n"
                "| tags | 태그 목록입니다. |\n"
                "| parameterDisplay | 사람이 읽기 쉬운 파라미터 표기입니다. Kaggle은 항상 `null`입니다. |\n"
                "| parameterRange | 파라미터 범주 정보입니다. Kaggle은 항상 `null`입니다. |\n\n"
                "pagination 내부 추가 필드 (Kaggle 포함 일부 마켓):\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| has_more | 다음 페이지가 있을 가능성을 나타냅니다. |\n"
                "| total_is_exact | `total`이 정확한 전체 수인지 여부입니다. HuggingFace=`true`, Kaggle=`false`(하한값). |\n"
                "| applied_filters | 실제 업스트림에 적용된 필터 정보입니다. |",
    responses={
        200: {"description": "모델 목록을 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "모델 목록 조회에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다 (예: Kaggle 자격 증명 미설정)."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def get_hub_models(
        market: str = Query(..., description="대상 마켓 이름입니다.", openapi_examples=_MARKET_EXAMPLES),
        sort: str = Query("downloads", description="정렬 기준입니다.", examples=["downloads"]),
        page: int = Query(1, ge=1, description="페이지 번호입니다. 1부터 시작합니다.", examples=[1]),
        limit: int = Query(30, ge=1, le=100, description="페이지당 최대 조회 개수입니다.", examples=[30]),
        search: str = Query(None, description="검색어입니다. 외부 API의 `query` 파라미터로 전달됩니다.", examples=["llama"]),
        num_parameters_min: str = Query(None, description="최소 파라미터 범위입니다. 예: `3B`, `7B`, `24B`", examples=["7B"]),
        num_parameters_max: str = Query(None, description="최대 파라미터 범위입니다. 예: `128B`, `256B`", examples=["70B"]),
        task: Optional[str] = Query(None, description="단일 파이프라인 태그/태스크 필터입니다. 외부 API의 `pipeline_tag`로 전달됩니다.", examples=["text-generation"]),
        library: Optional[List[str]] = Query(None, description="라이브러리 필터 (복수 선택 가능, 예: transformers, peft)"),
        language: Optional[List[str]] = Query(None, description="언어 필터 (복수 선택 가능, 예: en, ru, multilingual)"),
        license: Optional[str] = Query(None, description="라이선스 필터 (단일 선택, 예: apache-2.0)"),
        apps: Optional[List[str]] = Query(None, description="앱 필터 (복수 선택 가능, 예: llama.cpp, lmstudio)"),
        inference_provider: Optional[List[str]] = Query(None, description="추론 제공자 필터 (복수 선택 가능, 예: novita, nebius)"),
        other: Optional[List[str]] = Query(None, description="기타 필터 (복수 선택 가능, 예: endpoints_compatible, 4-bit)"),
        current_user: Member = Depends(get_current_user)
):
    """
    마켓별 모델 목록을 조회하거나 검색합니다.

    정렬값이 `trending`이면 트렌딩 조회 로직을 사용하고, 그 외에는 일반 검색 로직을 사용합니다.
    """
    try:
        # 요청 파라미터 구성
        params = ModelListParams(
            market=market,
            sort=sort,
            page=page,
            limit=limit,
            search=search,
            num_parameters_min=num_parameters_min,
            num_parameters_max=num_parameters_max,
            task=task,
            library=library,
            language=language,
            license=license,
            apps=apps,
            inference_provider=inference_provider,
            other=other
        )

        # 사용자 정보 구성
        user_info = {
            'member_id': current_user.member_id,
            'role': current_user.role,
            'name': current_user.name
        }

        # 허브 API에서 모델 목록 조회
        hub_response = await hub_connect_service.get_models(params, user_info)

        # 페이지네이션 정보 (Kaggle 신규 필드 포함)
        pagination = ModelListPagination(
            total=hub_response.total,
            page=hub_response.page,
            limit=hub_response.limit,
            has_more=hub_response.has_more,
            total_is_exact=hub_response.total_is_exact,
            applied_filters=hub_response.applied_filters,
        )

        return HubModelListWrapper(
            data=hub_response.data,
            pagination=pagination
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hub models for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hub models: {str(e)}"
        )

@router.get(
    "/models/{model_id:path}/files",
    response_model=HubModelFilesWrapper,
    summary="모델 파일 목록 조회",
    description="특정 모델 저장소의 파일 목록을 조회합니다.\n\n"
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| model_id | path | Y | 모델 저장소 ID입니다. 마켓별 형식이 다릅니다. HF: `owner/repo`, Kaggle: `owner/model/framework/variation`(4-세그먼트). | meta-llama/Llama-3-8B |\n"
                "| market | query | Y | 대상 마켓 이름입니다. | huggingface |\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| data | 모델 파일 목록입니다. |\n\n"
                "data 내부 항목:\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| name | 파일명 또는 저장소 내 경로입니다. |\n"
                "| size | 사람이 읽기 쉬운 파일 크기입니다. |\n"
                "| blob_id | 파일 blob 식별자입니다. Kaggle은 항상 `null`입니다. |",
    responses={
        200: {"description": "모델 파일 목록을 정상 조회했습니다."},
        400: {"description": "잘못된 모델 핸들입니다 (예: Kaggle 3/4-세그먼트 형식 검증 실패)."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "모델 파일 목록 조회에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def get_hub_model_files(
        model_id: str = Path(..., description="모델 저장소 ID입니다.", examples=["meta-llama/Llama-3-8B"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", openapi_examples=_MARKET_EXAMPLES),
        current_user: Member = Depends(get_current_user)
):
    """
    특정 모델 저장소의 파일 목록을 조회합니다.
    """
    try:
        # 사용자 정보 구성
        user_info = _create_user_info_dict(current_user)

        # 허브 API에서 모델 파일 목록 조회
        files_response = await hub_connect_service.get_model_files(str(model_id), market, user_info)

        return HubModelFilesWrapper(
            data=files_response.data
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hub model files {model_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hub model files: {str(e)}"
        )


@router.get(
    "/models/{model_id:path}/download",
    response_model=ModelDownloadResponse,
    response_model_exclude_none=True,
    summary="모델 파일 다운로드",
    description="특정 모델 파일을 다운로드합니다.\n\n"
                "`download_dir`를 지정하면 서버가 해당 경로로 파일을 복사하고 JSON 정보를 반환합니다.\n"
                "`download_dir`를 지정하지 않으면 파일 응답으로 바로 다운로드합니다.\n\n"
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| model_id | path | Y | 모델 저장소 ID입니다. Kaggle은 `owner/model/framework/variation`(4-세그먼트)를 권장합니다. | meta-llama/Llama-3-8B |\n"
                "| filename | query | Y | 다운로드할 파일명입니다. | config.json |\n"
                "| market | query | Y | 대상 마켓 이름입니다. | huggingface |\n"
                "| download_dir | query | N | 서버 내 사용자 지정 다운로드 경로입니다. | C:/downloads/models |\n\n"
                "### 응답 필드\n"
                "| 항목 | 설명 |\n"
                "| --- | --- |\n"
                "| 파일 응답 | `download_dir` 미지정 시 파일 다운로드 응답입니다. |\n"
                "| download_type | `download_dir` 지정 시 다운로드 방식입니다. |\n"
                "| file_path | 저장된 서버 경로입니다. |\n"
                "| file_size | 저장된 파일 크기(byte)입니다. |\n"
                "| filename | 다운로드한 파일명입니다. |\n"
                "| model_id | 대상 모델 ID입니다. |",
    responses={
        200: {"description": "모델 파일 다운로드를 처리했습니다."},
        400: {"description": "잘못된 모델 핸들입니다 (예: Kaggle 3/4-세그먼트 형식 검증 실패)."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "모델 파일 다운로드에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def download_hub_model_file(
        model_id: str = Path(..., description="모델 저장소 ID입니다.", examples=["meta-llama/Llama-3-8B"]),
        filename: str = Query(..., description="다운로드할 파일명입니다.", examples=["config.json"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", openapi_examples=_MARKET_EXAMPLES),
        download_dir: Optional[str] = Query(None, description="서버 내 사용자 지정 다운로드 경로입니다.", examples=["C:/downloads/models"]),
        current_user: Member = Depends(get_current_user)
):
    """
    특정 모델 파일을 다운로드합니다.

    `download_dir`를 지정하면 서버가 해당 경로로 파일을 복사하고 JSON 정보를 반환합니다.
    `download_dir`를 지정하지 않으면 파일 응답으로 바로 다운로드합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)
        download_result = await hub_connect_service.download_model_file(
            str(model_id),
            filename,
            market,
            download_dir,
            user_info
        )

        if isinstance(download_result, dict):
            return ModelDownloadResponse(**download_result)

        passthrough_headers = {}
        for header_name in ("content-disposition", "content-length", "etag", "last-modified"):
            header_value = download_result.headers.get(header_name)
            if header_value:
                passthrough_headers[header_name] = header_value

        return Response(
            content=download_result.content,
            media_type=download_result.headers.get("content-type", "application/octet-stream"),
            headers=passthrough_headers
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading hub model file {model_id}/{filename}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download hub model file: {str(e)}"
        )

@router.get(
    "/models/{model_id:path}",
    response_model=ExtendedHubModelResponse,
    summary="모델 상세 조회",
    description="특정 모델의 상세 정보를 조회합니다.\n\n"
                "마켓 서비스에서 받은 모델 정보와 모델 카드 정보를 합쳐 반환합니다.\n\n"
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| model_id | path | Y | 모델 저장소 ID입니다. HF: `owner/repo`, Kaggle: `owner/model/framework/variation`(4-세그먼트). | meta-llama/Llama-3-8B |\n"
                "| market | query | Y | 대상 마켓 이름입니다. | huggingface |\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| id | 모델 식별자입니다. |\n"
                "| downloads | 다운로드 수입니다. |\n"
                "| likes | 좋아요 수입니다. |\n"
                "| lastModified | 마지막 수정 시각입니다. |\n"
                "| pipeline_tag | 대표 태스크 태그입니다. |\n"
                "| tags | 태그 목록입니다. |\n"
                "| card_html | 모델 카드 내용을 HTML로 변환한 값입니다. |\n"
                "| variation_resolved | (Kaggle 전용) 요청 핸들의 framework/variation 메타가 exact match로 해결되었는지 여부입니다. `false`면 모델 레벨 정보로 폴백했습니다. |\n"
                "| 그 외 필드 | 마켓 카드 메타데이터가 추가로 포함될 수 있습니다. |",
    responses={
        200: {"description": "모델 상세 정보를 정상 조회했습니다."},
        400: {"description": "잘못된 모델 핸들입니다 (예: Kaggle 3/4-세그먼트 형식 검증 실패)."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        404: {"description": "요청한 모델을 찾을 수 없습니다."},
        500: {"description": "모델 상세 조회에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def get_hub_model_detail(
        model_id: str = Path(..., description="모델 저장소 ID입니다.", examples=["meta-llama/Llama-3-8B"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", openapi_examples=_MARKET_EXAMPLES),
        current_user: Member = Depends(get_current_user)
):
    """
    특정 모델의 상세 정보를 조회합니다.

    마켓 서비스에서 받은 모델 정보와 모델 카드 정보를 합쳐 반환합니다.
    """
    try:
        # 사용자 정보 구성 (필요시 서비스에 전달할 수 있도록)
        user_info = _create_user_info_dict(current_user)

        # 허브 API에서 모델 상세 정보 조회
        hub_model = await hub_connect_service.get_model_detail(str(model_id), market, user_info)

        if not hub_model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hub model {model_id} not found"
            )

        return hub_model

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hub model {model_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hub model detail: {str(e)}"
        )


@router.get(
    "/tags",
    response_model=TagListResponse,
    summary="전체 태그 그룹 조회",
    description="선택한 마켓의 전체 태그 그룹 데이터를 조회합니다.\n\n"
                "Kaggle은 HuggingFace와 같은 통합 태그 체계가 없어 **부분 응답**을 반환합니다: `library`(framework 상수)와 `dataset`만 채워지고 나머지 그룹은 빈 배열입니다.\n\n"
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| market | query | Y | 대상 마켓 이름입니다. 예: `huggingface`, `kaggle` | huggingface |\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| data | 태그 그룹 데이터 목록입니다. 현재 응답은 단일 객체를 배열로 감싸 반환합니다. |\n"
                "| region | 지역 태그 목록입니다. Kaggle은 `[]`. |\n"
                "| other | 기타 태그 목록입니다. Kaggle은 `[]`. |\n"
                "| library | 라이브러리 태그 목록입니다. Kaggle은 framework 상수로 채워집니다. |\n"
                "| license | 라이선스 태그 목록입니다. Kaggle은 `[]`. |\n"
                "| language | 언어 태그 목록입니다. Kaggle은 `[]`. |\n"
                "| dataset | 데이터셋 관련 태그 목록입니다. |\n"
                "| task | 파이프라인 태그 목록입니다. 외부 API의 `pipeline_tag`를 내부적으로 `task`로 변환해 반환합니다. Kaggle은 `[]`. |",
    responses={
        200: {"description": "전체 태그 그룹을 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "태그 그룹 조회에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def get_all_tags(
        market: str = Query(..., description="대상 AI 모델 마켓플레이스입니다. 예: `huggingface`, `kaggle`", openapi_examples=_MARKET_EXAMPLES),
        current_user: Member = Depends(get_current_user)
):
    try:
        logger.info(f"Getting all tags for market: {market}, user: {current_user.member_id}")

        # 사용자 정보 구성
        user_info = _create_user_info_dict(current_user)

        # 외부 허브 API에서 태그 목록 조회
        tags_response = await hub_connect_service.get_all_tags(market, user_info)

        logger.info(f"Successfully retrieved tags for market: {market}")

        return tags_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting all tags for market '{market}', user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tags: {str(e)}"
        )


@router.get(
    "/tags/{group}/all",
    response_model=TagGroupAllResponse,
    summary="특정 태그 그룹 전체 조회",
    description="특정 태그 그룹의 전체 데이터를 제한 없이 조회합니다.\n\n"
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| group | path | Y | 태그 그룹 이름입니다. | language |\n"
                "| market | query | Y | 대상 마켓 이름입니다. | huggingface |\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| data | 태그 데이터 전체 목록입니다. |",
    responses={
        200: {"description": "태그 그룹 전체 데이터를 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        404: {"description": "지원하지 않는 태그 그룹입니다."},
        500: {"description": "태그 그룹 전체 조회에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def get_all_tags_by_group(
        group: str = Path(
            ...,
            description="태그 그룹명입니다. 허용값: `region`, `other`, `library`, `license`, `language`, `dataset`, `pipeline_tag`",
            examples=["language"]
        ),
        market: str = Query(..., description="대상 AI 모델 마켓플레이스입니다. 예: `huggingface`, `kaggle`", openapi_examples=_MARKET_EXAMPLES),
        current_user: Member = Depends(get_current_user)
):
    try:
        logger.info(f"Getting all tags for group: {group}, market: {market}, user: {current_user.member_id}")

        user_info = _create_user_info_dict(current_user)
        group_response = await hub_connect_service.get_all_tags_by_group(group, market, user_info)

        logger.info(f"Successfully retrieved {len(group_response.data)} all tags for group '{group}' in market '{market}'")

        return group_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting all tags for group '{group}' in market '{market}', user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get all tags for group '{group}': {str(e)}"
        )


@router.get(
    "/tags/{group}",
    response_model=TagGroupResponse,
    summary="특정 태그 그룹 조회",
    description="특정 태그 그룹의 값을 조회합니다. 일부 그룹은 설정된 개수만큼만 반환하며 나머지 개수는 `remaining_count`로 제공합니다.\n\n"
                "업스트림이 해당 그룹을 미지원하거나 404를 반환하는 경우, 게이트웨이는 `data=[]`, `remaining_count=0`인 빈 응답을 200으로 반환합니다 (Kaggle 미지원 그룹 포함).\n\n"
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| group | path | Y | 태그 그룹 이름입니다. | library |\n"
                "| market | query | Y | 대상 마켓 이름입니다. | huggingface |\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| data | 태그 데이터 목록입니다. |\n"
                "| remaining_count | 제한 조회 후 남은 개수입니다. |",
    responses={
        200: {"description": "태그 그룹을 정상 조회했습니다. 미지원 그룹은 빈 배열로 반환됩니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        404: {"description": "지원하지 않는 태그 그룹입니다."},
        500: {"description": "태그 그룹 조회에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def get_tags_by_group(
        group: str = Path(
            ...,
            description="태그 그룹명입니다. 허용값: `region`, `other`, `library`, `license`, `language`, `dataset`, `pipeline_tag`",
            examples=["library"]
        ),
        market: str = Query(..., description="대상 AI 모델 마켓플레이스입니다. 예: `huggingface`, `kaggle`", openapi_examples=_MARKET_EXAMPLES),
        current_user: Member = Depends(get_current_user)
):
    try:
        logger.info(f"Getting tags for group: {group}, market: {market}, user: {current_user.member_id}")

        # 사용자 정보 구성
        user_info = _create_user_info_dict(current_user)

        # 외부 허브 API에서 특정 그룹의 태그 목록 조회
        group_response = await hub_connect_service.get_tags_by_group(group, market, user_info)

        logger.info(f"Successfully retrieved {len(group_response.data)} tags "
                    f"for group '{group}' in market '{market}' (remaining: {group_response.remaining_count})")

        return group_response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tags for group '{group}' in market '{market}', user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tags for group '{group}': {str(e)}"
        )


# ============================================================================
# Datasets (업스트림 hub-connect /datasets 래핑)
# ----------------------------------------------------------------------------
# 경로 등록 순서: 구체적인 suffix(`/info`, `/files`, `/download/{filename}`)를
# 먼저, 일반 `/download`를 나중에 정의해 `:path` 매칭 혼선을 피합니다.
# ============================================================================


@router.get(
    "/datasets/",
    response_model=DatasetListResponse,
    summary="데이터셋 목록 조회",
    description="마켓별 데이터셋 목록을 조회합니다.\n\n"
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| market | query | Y | 대상 마켓 이름입니다. | huggingface |\n"
                "| query | query | N | 검색어입니다. | titanic |\n"
                "| sort | query | N | 정렬 기준입니다. | likes |\n"
                "| page | query | N | 페이지 번호입니다. 1부터 시작합니다. | 1 |\n"
                "| size | query | N | 페이지당 항목 수입니다. | 20 |\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| data | 데이터셋 목록입니다. |\n"
                "| total | 전체 데이터셋 수 또는 하한값입니다. `total_is_exact=false`일 때는 '최소 이만큼'으로 해석합니다. |\n"
                "| page | 현재 페이지 번호입니다. |\n"
                "| size | 페이지당 반환 개수입니다. |\n"
                "| has_more | 다음 페이지 존재 가능성입니다. |\n"
                "| total_is_exact | `total`이 정확한 전체 수인지 여부입니다. HuggingFace=`true`, Kaggle=`false`. |",
    responses={
        200: {"description": "데이터셋 목록을 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "데이터셋 목록 조회에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다 (예: Kaggle 자격 증명 미설정)."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def get_hub_datasets(
        market: str = Query(..., description="대상 마켓 이름입니다.", openapi_examples=_MARKET_EXAMPLES),
        query: Optional[str] = Query(None, description="검색어입니다.", examples=["titanic"]),
        sort: Optional[str] = Query("likes", description="정렬 기준입니다.", examples=["likes"]),
        page: int = Query(1, ge=1, description="페이지 번호입니다. 1부터 시작합니다.", examples=[1]),
        size: int = Query(20, ge=1, le=100, description="페이지당 항목 수입니다.", examples=[20]),
        current_user: Member = Depends(get_current_user)
):
    try:
        params = DatasetListParams(
            market=market, query=query, sort=sort, page=page, size=size
        )
        user_info = _create_user_info_dict(current_user)

        return await hub_connect_service.get_datasets(params, user_info)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hub datasets for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hub datasets: {str(e)}"
        )


@router.get(
    "/datasets/{repo_id:path}/info",
    response_model=DatasetInfoResponse,
    summary="데이터셋 상세 조회",
    description="특정 데이터셋의 상세 정보를 조회합니다.\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| dataset_info | 설정별 데이터셋 상세 정보입니다. Kaggle은 features/splits 메타가 없어 항상 빈 객체입니다. |\n"
                "| pending | 아직 준비 중인 항목 목록입니다. |\n"
                "| failed | 조회 실패 항목 목록입니다. |\n"
                "| partial | 일부만 조회되었는지 여부입니다. Kaggle은 항상 `true`입니다. |\n"
                "| cardData | README 카드 메타데이터입니다. Kaggle은 description/license/tags/size_bytes/usability_rating/last_updated를 여기로 노출합니다. |",
    responses={
        200: {"description": "데이터셋 상세 정보를 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        404: {"description": "요청한 데이터셋을 찾을 수 없습니다."},
        500: {"description": "데이터셋 상세 조회에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def get_hub_dataset_info(
        repo_id: str = Path(..., description="데이터셋 저장소 ID입니다.", examples=["stanfordnlp/imdb"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", openapi_examples=_MARKET_EXAMPLES),
        current_user: Member = Depends(get_current_user)
):
    try:
        user_info = _create_user_info_dict(current_user)
        return await hub_connect_service.get_dataset_info(str(repo_id), market, user_info)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hub dataset info {repo_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hub dataset info: {str(e)}"
        )


@router.get(
    "/datasets/{repo_id:path}/files",
    response_model=DatasetFilesResponse,
    summary="데이터셋 파일 목록 조회",
    description="특정 데이터셋 저장소의 파일 목록을 조회합니다.\n\n"
                "### 응답 필드\n"
                "data 내부 항목:\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| name | 파일명 또는 저장소 내 경로입니다. |\n"
                "| size | 사람이 읽기 쉬운 파일 크기입니다. |\n"
                "| blob_id | 파일 blob 식별자입니다. Kaggle은 항상 `null`입니다. |",
    responses={
        200: {"description": "데이터셋 파일 목록을 정상 조회했습니다."},
        400: {"description": "잘못된 데이터셋 핸들입니다 (예: Kaggle 2-세그먼트 형식 검증 실패)."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "데이터셋 파일 목록 조회에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def get_hub_dataset_files(
        repo_id: str = Path(..., description="데이터셋 저장소 ID입니다.", examples=["stanfordnlp/imdb"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", openapi_examples=_MARKET_EXAMPLES),
        current_user: Member = Depends(get_current_user)
):
    try:
        user_info = _create_user_info_dict(current_user)
        return await hub_connect_service.get_dataset_files(str(repo_id), market, user_info)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hub dataset files {repo_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hub dataset files: {str(e)}"
        )


@router.get(
    "/datasets/{repo_id:path}/download/{filename:path}",
    summary="데이터셋 파일 단건 다운로드",
    description="특정 데이터셋 파일을 단건으로 다운로드합니다. 바이너리 또는 JSON 응답이 반환될 수 있습니다.",
    responses={
        200: {"description": "데이터셋 파일 다운로드를 처리했습니다."},
        400: {"description": "잘못된 데이터셋 핸들입니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        404: {"description": "요청한 파일을 찾을 수 없습니다."},
        500: {"description": "데이터셋 파일 다운로드에 실패했습니다."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def download_hub_dataset_file(
        repo_id: str = Path(..., description="데이터셋 저장소 ID입니다.", examples=["stanfordnlp/imdb"]),
        filename: str = Path(..., description="다운로드할 파일명입니다.", examples=["train.csv"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", openapi_examples=_MARKET_EXAMPLES),
        current_user: Member = Depends(get_current_user)
):
    try:
        user_info = _create_user_info_dict(current_user)
        download_result = await hub_connect_service.download_dataset_file(
            str(repo_id), str(filename), market, user_info
        )

        if isinstance(download_result, dict):
            return download_result

        passthrough_headers = {}
        for header_name in ("content-disposition", "content-length", "etag", "last-modified"):
            header_value = download_result.headers.get(header_name)
            if header_value:
                passthrough_headers[header_name] = header_value

        return Response(
            content=download_result.content,
            media_type=download_result.headers.get("content-type", "application/octet-stream"),
            headers=passthrough_headers
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading hub dataset file {repo_id}/{filename}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download hub dataset file: {str(e)}"
        )


@router.get(
    "/datasets/{repo_id:path}/download",
    response_model=DatasetSnapshotDownloadResponse,
    response_model_exclude_none=True,
    summary="데이터셋 스냅샷 다운로드",
    description="특정 데이터셋 저장소의 스냅샷을 다운로드합니다.\n\n"
                "`download_dir`를 지정하면 서버가 해당 경로로 스냅샷을 저장하고 JSON 정보를 반환합니다.\n"
                "`allow_patterns`/`ignore_patterns`로 파일 패턴 필터를 전달할 수 있으며, Kaggle에서는 SDK 제약에 따라 지원이 제한될 수 있습니다.\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| download_type | 다운로드 방식입니다. |\n"
                "| snapshot_path | 저장된 스냅샷 경로입니다. |\n"
                "| repo_id | 대상 데이터셋 ID입니다. |\n"
                "| total_files | 사용자 지정 경로 다운로드 시 저장된 파일 수입니다. |\n"
                "| message | 캐시 다운로드 시 안내 메시지입니다. |\n"
                "| filters_applied | (Kaggle 전용) allow/ignore 패턴이 실제 적용되었는지 여부입니다. |",
    responses={
        200: {"description": "데이터셋 스냅샷 다운로드를 처리했습니다."},
        400: {"description": "잘못된 데이터셋 핸들입니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        404: {"description": "allow/ignore 패턴에 매치되는 파일이 없습니다."},
        500: {"description": "데이터셋 스냅샷 다운로드에 실패했습니다."},
        501: {"description": "필터 기반 스냅샷 다운로드가 지원되지 않습니다 (Kaggle SDK 파일 목록 미지원 등). `kaggle` 패키지를 업그레이드하거나 allow_patterns/ignore_patterns를 생략하세요."},
        503: {"description": "업스트림 허브 서비스가 일시적으로 불가용합니다."},
        504: {"description": "업스트림 허브 서비스 응답 지연으로 시간 초과되었습니다."},
    }
)
async def download_hub_dataset_snapshot(
        repo_id: str = Path(..., description="데이터셋 저장소 ID입니다.", examples=["stanfordnlp/imdb"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", openapi_examples=_MARKET_EXAMPLES),
        download_dir: Optional[str] = Query(None, description="서버 내 사용자 지정 다운로드 경로입니다.", examples=["C:/downloads/datasets"]),
        allow_patterns: Optional[List[str]] = Query(None, description="허용 파일 패턴(여러 개 가능)."),
        ignore_patterns: Optional[List[str]] = Query(None, description="제외 파일 패턴(여러 개 가능)."),
        current_user: Member = Depends(get_current_user)
):
    try:
        user_info = _create_user_info_dict(current_user)
        download_result = await hub_connect_service.download_dataset_snapshot(
            str(repo_id), market,
            download_dir=download_dir,
            allow_patterns=allow_patterns,
            ignore_patterns=ignore_patterns,
            user_info=user_info,
        )

        if isinstance(download_result, dict):
            return download_result

        passthrough_headers = {}
        for header_name in ("content-disposition", "content-length", "etag", "last-modified"):
            header_value = download_result.headers.get(header_name)
            if header_value:
                passthrough_headers[header_name] = header_value

        return Response(
            content=download_result.content,
            media_type=download_result.headers.get("content-type", "application/octet-stream"),
            headers=passthrough_headers
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading hub dataset snapshot {repo_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download hub dataset snapshot: {str(e)}"
        )
