from fastapi import APIRouter, Depends, HTTPException, Response, status, Query, Path
from typing import Optional, Union, List
import logging

from app.auth import get_current_user
from app.schemas.hub_connect import (
    ModelListParams, HubModelListWrapper, HubUserInfo,
    ExtendedHubModelResponse, HubModelFilesWrapper, ModelDownloadResponse,
    TagListResponse, TagGroupResponse, TagGroupAllResponse
)
from app.services.hub_connect_service import hub_connect_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/hub-connect", tags=["Hub Connect"])


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
                "| parameterDisplay | 사람이 읽기 쉬운 파라미터 표기입니다. |\n"
                "| parameterRange | 파라미터 범주 정보입니다. |",
    responses={
        200: {"description": "모델 목록을 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "모델 목록 조회에 실패했습니다."},
    }
)
async def get_hub_models(
        market: str = Query(..., description="대상 마켓 이름입니다.", examples=["huggingface"]),
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

        # 페이지네이션 정보
        pagination = {
            "total": hub_response.total,
            "page": hub_response.page,
            "limit": hub_response.limit
        }

        return HubModelListWrapper(
            data=hub_response.data,
            pagination=pagination
        )

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
                "| model_id | path | Y | 모델 저장소 ID입니다. | meta-llama/Llama-3-8B |\n"
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
                "| blob_id | 파일 blob 식별자입니다. |",
    responses={
        200: {"description": "모델 파일 목록을 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "모델 파일 목록 조회에 실패했습니다."},
    }
)
async def get_hub_model_files(
        model_id: str = Path(..., description="모델 저장소 ID입니다.", examples=["meta-llama/Llama-3-8B"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", examples=["huggingface"]),
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

    except Exception as e:
        logger.error(f"Error getting hub model files {model_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hub model files: {str(e)}"
        )


@router.get(
    "/models/{model_id:path}/download",
    summary="모델 파일 다운로드",
    description="특정 모델 파일을 다운로드합니다.\n\n"
                "`download_dir`를 지정하면 서버가 해당 경로로 파일을 복사하고 JSON 정보를 반환합니다.\n"
                "`download_dir`를 지정하지 않으면 파일 응답으로 바로 다운로드합니다.\n\n"
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| model_id | path | Y | 모델 저장소 ID입니다. | meta-llama/Llama-3-8B |\n"
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
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "모델 파일 다운로드에 실패했습니다."},
    }
)
async def download_hub_model_file(
        model_id: str = Path(..., description="모델 저장소 ID입니다.", examples=["meta-llama/Llama-3-8B"]),
        filename: str = Query(..., description="다운로드할 파일명입니다.", examples=["config.json"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", examples=["huggingface"]),
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
                "| model_id | path | Y | 모델 저장소 ID입니다. | meta-llama/Llama-3-8B |\n"
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
                "| 그 외 필드 | 마켓 카드 메타데이터가 추가로 포함될 수 있습니다. |",
    responses={
        200: {"description": "모델 상세 정보를 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        404: {"description": "요청한 모델을 찾을 수 없습니다."},
    }
)
async def get_hub_model_detail(
        model_id: str = Path(..., description="모델 저장소 ID입니다.", examples=["meta-llama/Llama-3-8B"]),
        market: str = Query(..., description="대상 마켓 이름입니다.", examples=["huggingface"]),
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
                "### 입력 필드\n"
                "| 필드 | 위치 | 필수 | 설명 | 예시 |\n"
                "| --- | --- | --- | --- | --- |\n"
                "| market | query | Y | 대상 마켓 이름입니다. 예: `huggingface`, `aihub` | huggingface |\n\n"
                "### 응답 필드\n"
                "| 필드 | 설명 |\n"
                "| --- | --- |\n"
                "| data | 태그 그룹 데이터 목록입니다. 현재 응답은 단일 객체를 배열로 감싸 반환합니다. |\n"
                "| region | 지역 태그 목록입니다. |\n"
                "| other | 기타 태그 목록입니다. |\n"
                "| library | 라이브러리 태그 목록입니다. |\n"
                "| license | 라이선스 태그 목록입니다. |\n"
                "| language | 언어 태그 목록입니다. |\n"
                "| dataset | 데이터셋 관련 태그 목록입니다. |\n"
                "| task | 파이프라인 태그 목록입니다. 외부 API의 `pipeline_tag`를 내부적으로 `task`로 변환해 반환합니다. |",
    responses={
        200: {"description": "전체 태그 그룹을 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        500: {"description": "태그 그룹 조회에 실패했습니다."},
    }
)
async def get_all_tags(
        market: str = Query(..., description="대상 AI 모델 마켓플레이스입니다. 예: `huggingface`, `aihub`", examples=["huggingface"]),
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
    }
)
async def get_all_tags_by_group(
        group: str = Path(
            ...,
            description="태그 그룹명입니다. 허용값: `region`, `other`, `library`, `license`, `language`, `dataset`, `pipeline_tag`",
            examples=["language"]
        ),
        market: str = Query(..., description="대상 AI 모델 마켓플레이스입니다. 예: `huggingface`, `aihub`", examples=["huggingface"]),
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
        200: {"description": "태그 그룹을 정상 조회했습니다."},
        401: {"description": "인증이 필요하거나 인증 정보가 올바르지 않습니다."},
        404: {"description": "지원하지 않는 태그 그룹입니다."},
        500: {"description": "태그 그룹 조회에 실패했습니다."},
    }
)
async def get_tags_by_group(
        group: str = Path(
            ...,
            description="태그 그룹명입니다. 허용값: `region`, `other`, `library`, `license`, `language`, `dataset`, `pipeline_tag`",
            examples=["library"]
        ),
        market: str = Query(..., description="대상 AI 모델 마켓플레이스입니다. 예: `huggingface`, `aihub`", examples=["huggingface"]),
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

    except Exception as e:
        logger.error(f"Error getting tags for group '{group}' in market '{market}', user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tags for group '{group}': {str(e)}"
        )
