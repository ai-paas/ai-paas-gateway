from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from typing import Optional, Union
import logging

from app.auth import get_current_user
from app.schemas.hub_connect import (
    ModelListParams, HubModelListWrapper, HubUserInfo,
    ExtendedHubModelResponse, HubModelFilesWrapper, HubModelDownloadWrapper,
    TagListResponse, TagGroupResponse
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


@router.get("/models", response_model=HubModelListWrapper)
async def get_hub_models(
        market: Optional[str] = Query(..., description="Market name (e.g., huggingface, aihub)"),
        sort: Optional[str] = Query("downloads", description=""),
        page: int = Query(1, ge=1, description="페이지 번호"),
        limit: int = Query(30, ge=1, le=100, description="페이지 당 항목 수"),
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
            limit=limit
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
        model_id: Union[str, int] = Path(..., description="모델 ID"),
        market: Optional[str] = Query(..., description="모델 마켓")
):
    """
    허브 모델 파일 목록 조회
    """
    try:

        # 허브 API에서 모델 파일 목록 조회
        files_response = await hub_connect_service.get_model_files(str(model_id), market)

        return HubModelFilesWrapper(
            data=files_response.data
        )

    except Exception as e:
        logger.error(f"Error getting hub model files {model_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hub model files: {str(e)}"
        )


@router.get("/models/{model_id:path}/download", response_model=HubModelDownloadWrapper)
async def download_hub_model_file(
        model_id: Union[str, int] = Path(..., description="모델 ID"),
        filename: str = Query(..., description="다운로드할 파일명"),
        market: Optional[str] = Query(..., description="모델 마켓"),
        current_user: Member = Depends(get_current_user)
):
    """
    허브 모델 파일 다운로드
    """
    try:
        # 사용자 정보 구성
        user_info = {
            'member_id': current_user.member_id,
            'role': current_user.role,
            'name': current_user.name
        }

        # 허브 API에서 다운로드 URL 조회
        download_response = await hub_connect_service.download_model_file(
            str(model_id), filename, market, user_info
        )

        # 사용자 정보 생성
        hub_user_info = _create_hub_user_info(current_user)

        return HubModelDownloadWrapper(
            download_url=download_response.download_url,
            filename=download_response.filename,
            model_id=download_response.model_id,
            file_size=download_response.file_size,
            user_info=hub_user_info
        )

    except Exception as e:
        logger.error(f"Error downloading hub model file {model_id}/{filename}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to download hub model file: {str(e)}"
        )


@router.get("/models/{model_id:path}", response_model=ExtendedHubModelResponse)
async def get_hub_model_detail(
        model_id: Union[str, int] = Path(..., description="모델 ID"),
        market: Optional[str] = Query(..., description="모델 마켓")
):
    """
    허브 모델 상세 정보 조회
    """
    try:
        # 허브 API에서 모델 상세 정보 조회
        hub_model = await hub_connect_service.get_model_detail(str(model_id), market)

        if not hub_model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Hub model {model_id} not found"
            )

        return hub_model

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting hub model {model_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get hub model detail: {str(e)}"
        )


@router.get("/tags", response_model=TagListResponse)
async def get_all_tags(
        market: str = Query("", description="모델 마켓 (예: huggingface)")
):
    try:
        logger.info(f"Getting all tags for market: {market}")

        # 외부 허브 API에서 태그 목록 조회
        tags_response = await hub_connect_service.get_all_tags(market)

        logger.info(f"Successfully retrieved tags for market: {market}")

        return tags_response

    except Exception as e:
        logger.error(f"Error getting all tags for market '{market}': {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tags: {str(e)}"
        )


@router.get("/tags/{group}", response_model=TagGroupResponse)
async def get_tags_by_group(
        group: str = Path(..., description="태그 그룹명 (예: region, library, framework)"),
        market: str = Query("", description="모델 마켓 (예: huggingface)")
):
    try:
        logger.info(f"Getting tags for group: {group}, market: {market}")

        # 외부 허브 API에서 특정 그룹의 태그 목록 조회
        group_response = await hub_connect_service.get_tags_by_group(group, market)

        logger.info(f"Successfully retrieved {len(group_response.data)} tags "
                    f"for group '{group}' in market '{market}' (remaining: {group_response.remaining_count})")

        return group_response

    except Exception as e:
        logger.error(f"Error getting tags for group '{group}' in market '{market}': {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tags for group '{group}': {str(e)}"
        )