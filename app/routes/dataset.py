from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, File, UploadFile, Form
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import logging

from app.database import get_db
from app.auth import get_current_user
from app.cruds import dataset_crud
from app.schemas.dataset import (
    DatasetCreateRequest, DatasetReadSchema, DatasetListWrapper,
    DatasetWithMemberInfo, InnoUserInfo, DatasetValidationResponse
)
from app.services.dataset_service import dataset_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/datasets", tags=["Datasets"])


def _create_inno_user_info(user: Member) -> InnoUserInfo:
    """Member 객체에서 InnoUserInfo 생성"""
    return InnoUserInfo(
        member_id=user.member_id,
        role=user.role,
        name=user.name
    )


def _create_pagination_response(
        data: List[Any],
        total: int,
        page: int,
        size: int
) -> Dict[str, Any]:
    """페이지네이션 응답 생성"""
    return {
        "data": data,
        "total": total,
        "page": page,
        "size": size
    }


@router.get("", response_model=DatasetListWrapper)
async def get_datasets(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    사용자별 데이터셋 목록 조회 (페이지네이션 포함)

    - 현재 사용자가 생성한 데이터셋만 조회합니다.
    - 페이지네이션을 지원합니다.
    """
    try:
        skip = (page - 1) * size

        # 1. 사용자 데이터셋 총 개수 조회 (Inno DB)
        total_datasets = dataset_crud.get_datasets_count_by_member(
            db=db,
            member_id=current_user.member_id
        )

        if total_datasets == 0:
            return _create_pagination_response([], 0, page, size)

        # 2. 사용자 데이터셋 ID 목록 조회 (페이지네이션 적용)
        user_dataset_ids = dataset_crud.get_datasets_by_member_id(
            db,
            current_user.member_id,
            skip=skip,
            limit=size
        )

        if not user_dataset_ids:
            return _create_pagination_response([], total_datasets, page, size)

        # 3. 외부 API에서 전체 데이터셋 조회 (페이지네이션 없이)
        all_datasets_response = await dataset_service.get_datasets(
            page=None,
            page_size=None,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 4. 사용자 소유 데이터셋만 필터링
        filtered = [d for d in all_datasets_response.data if d.id in user_dataset_ids]

        # 5. 사용자 정보 추가
        member_info = _create_inno_user_info(current_user)
        wrapped = []
        for dataset in filtered:
            dataset_dict = dataset.model_dump()
            dataset_dict["member_info"] = member_info.model_dump()
            wrapped.append(DatasetWithMemberInfo(**dataset_dict))

        return _create_pagination_response(wrapped, total_datasets, page, size)

    except Exception as e:
        logger.error(f"Error getting datasets for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get datasets: {str(e)}"
        )


@router.get("/{dataset_id}", response_model=DatasetReadSchema)
async def get_dataset(
        dataset_id: int = Path(..., description="데이터셋 ID (외부 API 데이터셋 ID)"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    특정 데이터셋 상세 정보 조회

    - 현재 사용자가 소유한 데이터셋인지 확인 후 상세 정보를 반환합니다.
    - 데이터셋 레지스트리 정보를 포함합니다.
    """
    try:
        # 1. 사용자가 해당 데이터셋을 소유하고 있는지 확인
        if not dataset_crud.check_dataset_ownership(db, dataset_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found or access denied"
            )

        # 2. 외부 API에서 데이터셋 상세 정보 조회
        dataset = await dataset_service.get_dataset(
            dataset_id=dataset_id,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        if not dataset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found"
            )

        return dataset

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting dataset {dataset_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get dataset: {str(e)}"
        )


@router.post("/validate", response_model=DatasetValidationResponse)
async def validate_dataset(
        file: UploadFile = File(..., description="검증할 데이터셋 ZIP 파일"),
        current_user: Member = Depends(get_current_user)
):
    """
    데이터셋 파일 유효성 검증

    - COCO128 형식의 데이터셋 구조를 검증합니다.
    - 데이터셋 등록 전에 호출하는 것을 권장합니다.
    """
    try:
        validation_result = await dataset_service.validate_dataset(
            file=file,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        return validation_result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validating dataset for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to validate dataset: {str(e)}"
        )


@router.post("", response_model=DatasetReadSchema)
async def create_dataset(
        name: str = Form(..., description="데이터셋 이름"),
        description: str = Form(..., description="데이터셋 설명"),
        file: UploadFile = File(..., description="데이터셋 ZIP 파일 (COCO128 형식)"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    새 데이터셋 생성

    - 외부 API에 데이터셋을 생성한 후, Inno DB에 사용자-데이터셋 매핑을 저장합니다.
    - COCO128 형식의 ZIP 파일을 업로드해야 합니다.
    - /datasets/validate API를 먼저 호출하여 파일을 검증하는 것을 권장합니다.
    """
    try:
        # 데이터셋 생성 요청 데이터 구성
        dataset_data = DatasetCreateRequest(
            name=name,
            description=description
        )

        # 1. 외부 API를 통해 데이터셋 생성
        created_dataset = await dataset_service.create_dataset(
            dataset_data=dataset_data,
            file=file,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 2. Inno DB에 사용자-데이터셋 매핑 저장
        try:
            dataset_crud.create_dataset_mapping(
                db=db,
                surro_dataset_id=created_dataset.id,
                member_id=current_user.member_id,
                dataset_name=created_dataset.name
            )
            logger.info(
                f"Created dataset mapping: surro_id={created_dataset.id}, "
                f"member_id={current_user.member_id}"
            )
        except Exception as mapping_error:
            logger.error(f"Failed to create dataset mapping: {str(mapping_error)}")
            # 매핑 저장에 실패해도 외부 API에는 이미 생성되었으므로, 경고만 로그
            logger.warning(
                f"Dataset {created_dataset.id} created in external API but mapping failed"
            )

        return created_dataset

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating dataset for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create dataset: {str(e)}"
        )