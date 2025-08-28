from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, File, UploadFile, Form
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import logging
import json

from app.database import get_db
from app.auth import get_current_user, get_current_admin_user
from app.cruds import dataset_crud
from app.schemas.dataset import (
    DatasetCreate, DatasetUpdate, DatasetResponse,
    DatasetListResponse, DatasetCreateRequest,
    ExternalDatasetResponse, InnoUserInfo, EnhancedDatasetResponse, DatasetWithMemberInfo ,DatasetListWrapper
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

def _create_pagination_response(data: List[Any], total: int, page: int, size: int) -> Dict[str, Any]:
    return {
        "data": data,
        "total": total,
        "page": page,
        "size": size
    }

@router.get("")
async def get_datasets(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="이름 또는 설명 검색"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    사용자별 데이터셋 목록 조회 (페이지네이션 포함)
    """
    try:
        skip = (page - 1) * size

        # 1. 사용자 데이터셋 ID 전체 개수 조회
        total_datasets = dataset_crud.get_datasets_count(
            db=db,
            search=search,
            is_active=True
        )

        if total_datasets == 0:
            return _create_pagination_response([], 0, page, size)

        # 2. 사용자 데이터셋 ID 조회 (page/size 기반)
        user_dataset_ids = dataset_crud.get_datasets_by_member_id(
            db,
            current_user.member_id,
            skip=skip,
            limit=size
        )

        if not user_dataset_ids:
            return _create_pagination_response([], total_datasets, page, size)

        # 3. Surro API에서 전체 조회
        all_surro_datasets = await dataset_service.get_datasets(
            skip=0,
            limit=1000,
            search=search,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 4. 사용자 소유 데이터셋만 필터링
        filtered = [d for d in all_surro_datasets if d.id in user_dataset_ids]

        # 5. 사용자 정보 추가
        member_info = _create_inno_user_info(current_user)
        wrapped = []
        for d in filtered:
            d_dict = d.model_dump()
            d_dict["member_info"] = member_info.model_dump()
            wrapped.append(DatasetWithMemberInfo(**d_dict))

        return _create_pagination_response(wrapped, total_datasets, page, size)

    except Exception as e:
        logger.error(f"Error getting datasets for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get datasets: {str(e)}"
        )

@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
        dataset_id: int = Path(..., description="데이터셋 ID (Surro API 데이터셋 ID)"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    특정 데이터셋 상세 정보 조회

    - 현재 사용자가 소유한 데이터셋인지 확인 후 상세 정보를 반환합니다.
    """
    try:
        # 1. 사용자가 해당 데이터셋을 소유하고 있는지 확인
        if not dataset_crud.check_dataset_ownership(db, dataset_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found or access denied"
            )

        # 2. Surro API에서 데이터셋 상세 정보 조회
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


@router.post("", response_model=DatasetResponse)
async def create_dataset(
        name: str = Form(..., description="데이터셋 이름"),
        description: str = Form(..., description="데이터셋 설명"),
        file: Optional[UploadFile] = File(None, description="데이터셋 파일"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    새 데이터셋 생성

    - Surro API에 데이터셋을 생성한 후, Inno DB에 사용자-데이터셋 매핑을 저장합니다.
    - 필수 파라미터: name, description
    - 선택적 파라미터: file (바이너리 파일)
    """
    try:
        # 파일 처리
        file_data = None
        file_name = None
        if file:
            file_data = await file.read()
            file_name = file.filename

        # 데이터셋 생성 요청 데이터 구성
        dataset_data = DatasetCreateRequest(
            name=name,
            description=description
        )

        # 1. Surro API를 통해 데이터셋 생성
        created_dataset = await dataset_service.create_dataset(
            dataset_data=dataset_data,
            file_data=file_data,
            file_name=file_name,
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
                dataset_name=created_dataset.name,
                description=created_dataset.description
            )
            logger.info(f"Created dataset mapping: surro_id={created_dataset.id}, member_id={current_user.member_id}")
        except Exception as mapping_error:
            logger.error(f"Failed to create dataset mapping: {str(mapping_error)}")
            # 매핑 저장에 실패해도 Surro API에는 이미 생성되었으므로, 경고만 로그
            logger.warning(f"Dataset {created_dataset.id} created in Surro API but mapping failed")

        return created_dataset

    except Exception as e:
        logger.error(f"Error creating dataset for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create dataset: {str(e)}"
        )


@router.put("/{dataset_id}", response_model=DatasetResponse)
async def update_dataset(
        dataset_id: int = Path(..., description="데이터셋 ID (Surro API 데이터셋 ID)"),
        name: Optional[str] = Form(None, description="데이터셋 이름"),
        description: Optional[str] = Form(None, description="데이터셋 설명"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    데이터셋 수정

    - 현재 사용자가 소유한 데이터셋만 수정할 수 있습니다.
    """
    try:
        # 1. 사용자가 해당 데이터셋을 소유하고 있는지 확인
        if not dataset_crud.check_dataset_ownership(db, dataset_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found or access denied"
            )

        # 2. 수정할 데이터 구성
        update_data = DatasetUpdate()
        if name is not None:
            update_data.name = name
        if description is not None:
            update_data.description = description

        # 3. Surro API에서 데이터셋 수정
        updated_dataset = await dataset_service.update_dataset(
            dataset_id=dataset_id,
            dataset_data=update_data,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        if not updated_dataset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found in Surro API"
            )

        logger.info(f"Updated dataset {dataset_id} for user {current_user.member_id}")
        return updated_dataset

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating dataset {dataset_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update dataset: {str(e)}"
        )


@router.delete("/{dataset_id}")
async def delete_dataset(
        dataset_id: int = Path(..., description="데이터셋 ID (Surro API 데이터셋 ID)"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    데이터셋 삭제

    - 현재 사용자가 소유한 데이터셋만 삭제할 수 있습니다.
    - Surro API에서 데이터셋을 삭제한 후, Inno DB의 매핑도 삭제합니다.
    """
    try:
        # 1. 사용자가 해당 데이터셋을 소유하고 있는지 확인
        if not dataset_crud.check_dataset_ownership(db, dataset_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found or access denied"
            )

        # 2. Surro API에서 데이터셋 삭제
        success = await dataset_service.delete_dataset(
            dataset_id=dataset_id,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Dataset {dataset_id} not found in Surro API"
            )

        # 3. Inno DB에서 매핑 삭제
        dataset_crud.delete_dataset_mapping(db, dataset_id, current_user.member_id)

        logger.info(f"Deleted dataset {dataset_id} and mapping for user {current_user.member_id}")
        return {"message": f"Dataset {dataset_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting dataset {dataset_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete dataset: {str(e)}"
        )