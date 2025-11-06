from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from typing import Optional, Union, List
import logging

from app.auth import get_current_user
from app.schemas.hub_connect import (
    ModelListParams, HubModelListWrapper, HubUserInfo,
    ExtendedHubModelResponse, HubModelFilesWrapper, TagListResponse, TagGroupResponse
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


@router.get("/models", response_model=HubModelListWrapper)
async def get_hub_models(
        market: str = Query(..., description="Market name (e.g., huggingface, aihub)"),
        sort: str = Query("downloads", description="정렬 방식 (downloads, created, relevance)"),
        page: int = Query(1, ge=1, description="페이지 번호"),
        limit: int = Query(30, ge=1, le=100, description="페이지 당 항목 수"),
        search: str = Query(None, description="검색 키워드"),
        num_parameters_min: str = Query(None, description="Minimum parameters (e.g., '3B', '7B', '24B')"),
        num_parameters_max: str = Query(None, description="Maximum parameters (e.g., '128B', '256B')"),
        tasks: Optional[str] = Query(None, description="Filter by task (single selection, mapped to pipeline_tag in external API)"),
        library: Optional[List[str]] = Query(None, description="Filter by library (multiple allowed, e.g., transformers, peft)"),
        language: Optional[List[str]] = Query(None, description="Filter by language (multiple allowed, e.g., en, ru, multilingual)"),
        license: Optional[str] = Query(None, description="Filter by license (single selection, e.g., license:apache-2.0)"),
        apps: Optional[List[str]] = Query(None, description="Filter by apps (multiple allowed, e.g., llama.cpp, lmstudio)"),
        inference_provider: Optional[List[str]] = Query(None, description="Filter by inference provider (multiple allowed, e.g., novita, nebius)"),
        other: Optional[List[str]] = Query(None, description="Other filters (multiple allowed, e.g., endpoints_compatible, 4-bit)"),
        current_user: Member = Depends(get_current_user)
):
    """
    허브에서 모델 목록 조회
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
            tasks=tasks,
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

@router.get("/models/{model_id:path}/files", response_model=HubModelFilesWrapper)
async def get_hub_model_files(
        model_id: str = Path(..., description="모델 ID"),
        market: str = Query(..., description="모델 마켓"),
        current_user: Member = Depends(get_current_user)
):
    """
    허브 모델 파일 목록 조회
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

@router.get("/models/{model_id:path}", response_model=ExtendedHubModelResponse)
async def get_hub_model_detail(
        model_id: str = Path(..., description="모델 ID"),
        market: str = Query(..., description="모델 마켓"),
        current_user: Member = Depends(get_current_user)
):
    """
    허브 모델 상세 정보 조회
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


@router.get("/tags", response_model=TagListResponse)
async def get_all_tags(
        market: str = Query(..., description="모델 마켓 (예: huggingface)"),
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


@router.get("/tags/{group}", response_model=TagGroupResponse)
async def get_tags_by_group(
        group: str = Path(..., description="태그 그룹명 (예: region, library, framework)"),
        market: str = Query(..., description="모델 마켓 (예: huggingface)"),
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