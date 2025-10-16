from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, File, UploadFile, Form
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import logging
import json
import math

from app.database import get_db
from app.auth import get_current_user, get_current_admin_user
from app.cruds import model_crud
from app.schemas.model import (
    ModelResponse, ModelCreateRequest,
    ModelTestRequest, ModelTestResponse,
    InnoUserInfo, ModelWithMemberInfo, ModelListWrapper
)
from app.services.model_service import model_service
from app.models import Member, Model

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["Models"])


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


@router.get("/custom-models")
async def get_user_models(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        provider_id: Optional[int] = Query(None, description="프로바이더 ID로 필터링"),
        type_id: Optional[int] = Query(None, description="모델 타입 ID로 필터링"),
        format_id: Optional[int] = Query(None, description="모델 포맷 ID로 필터링"),
        search: Optional[str] = Query(None, description="검색어"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    현재 로그인한 사용자가 생성한 모델만 조회 (페이지네이션 포함)
    """
    try:
        # 1. 사용자 커스텀 모델 총 개수 조회
        total_user_models = db.query(Model).filter(
            Model.created_by == current_user.member_id,
            Model.deleted_at.is_(None)
        ).count()

        if total_user_models == 0:
            return _create_pagination_response([], 0, page, size)

        # page/size 기반 조회
        skip = (page - 1) * size
        user_models = db.query(Model).filter(
            Model.created_by == current_user.member_id,
            Model.deleted_at.is_(None)
        ).offset(skip).limit(size).all()

        user_model_ids = [model.surro_model_id for model in user_models if model.surro_model_id]

        if not user_model_ids:
            return _create_pagination_response([], total_user_models, page, size)

        # 3. Surro API 모델 전체 조회 후 필터링
        all_surro_models = await model_service.get_models(
            skip=0, limit=1000,  # 전체 조회 후 필터링
            provider_id=provider_id, type_id=type_id,
            format_id=format_id, search=search,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 4. 사용자 커스텀 모델만 필터링
        filtered_models = [m for m in all_surro_models if m.id in user_model_ids]

        # 5. surro_data + member_info 합치기
        wrapped_models = []
        for surro_model in filtered_models:
            model_dict = surro_model.model_dump()
            wrapped_models.append(ModelResponse(**model_dict))

        return _create_pagination_response(wrapped_models, total_user_models, page, size)

    except Exception as e:
        logger.error(f"Error getting user models for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user models: {str(e)}"
        )

@router.get("/model-catalog")
async def get_catalog_models(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        provider_id: Optional[int] = Query(None, description="프로바이더 ID로 필터링"),
        type_id: Optional[int] = Query(None, description="모델 타입 ID로 필터링"),
        format_id: Optional[int] = Query(None, description="모델 포맷 ID로 필터링"),
        search: Optional[str] = Query(None, description="검색어"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 카탈로그 조회 (is_catalog가 true인 모델만, 페이지네이션 포함)
    """
    try:
        # 1. 카탈로그 모델 총 개수 조회
        total_catalog_models = db.query(Model).filter(
            Model.is_catalog == True,
            Model.deleted_at.is_(None)
        ).count()

        if total_catalog_models == 0:
            return _create_pagination_response([], 0, page, size)

        # 2. 카탈로그 모델 조회 (페이지네이션 적용)
        skip = (page - 1) * size
        catalog_models = db.query(Model).filter(
            Model.is_catalog == True,
            Model.deleted_at.is_(None)
        ).offset(skip).limit(size).all()

        catalog_model_ids = [model.surro_model_id for model in catalog_models if model.surro_model_id]

        if not catalog_model_ids:
            return _create_pagination_response([], total_catalog_models, page, size)

        # 3. Surro API 모델 전체 조회 후 필터링 (custom-models와 동일한 패턴)
        all_surro_models = await model_service.get_models(
            skip=0, limit=1000,  # 전체 조회 후 필터링
            provider_id=provider_id, type_id=type_id,
            format_id=format_id, search=search,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 4. 카탈로그 모델만 필터링
        filtered_models = [m for m in all_surro_models if m.id in catalog_model_ids]

        # 4. surro_data + member_info 합치기
        wrapped_models = []
        for surro_model in filtered_models:
            model_dict = surro_model.model_dump()
            wrapped_models.append(ModelResponse(**model_dict))

        return _create_pagination_response(wrapped_models, total_catalog_models, page, size)

    except Exception as e:
        logger.error(f"Error getting catalog models: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get catalog models: {str(e)}"
        )


@router.get("/providers")
async def get_providers(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        provider_name: Optional[str] = Query(None, description="프로바이더 이름으로 필터링"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    사용 가능한 프로바이더 목록 조회 (페이지네이션 포함)
    """
    try:
        all_providers_data = await model_service.get_model_providers(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            },
            provider_name=provider_name
        )

        skip = (page - 1) * size

        if isinstance(all_providers_data, list):
            total = len(all_providers_data)
            paginated_data = all_providers_data[skip:skip + size]
            return _create_pagination_response(paginated_data, total, page, size)

        elif isinstance(all_providers_data, dict) and 'data' in all_providers_data:
            data = all_providers_data.get('data', [])
            total_from_api = all_providers_data.get('total', len(data))

            start_idx = skip
            end_idx = skip + size
            final_data = data[start_idx:end_idx] if start_idx < len(data) else []

            return _create_pagination_response(final_data, total_from_api, page, size)

        else:
            return _create_pagination_response([], 0, page, size)

    except Exception as e:
        logger.error(f"Error getting providers: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get providers: {str(e)}"
        )


@router.get("/types")
async def get_model_types(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        type_name: Optional[str] = Query(None, description="모델 타입 이름으로 필터링"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    사용 가능한 모델 타입 목록 조회 (페이지네이션 포함)
    """
    try:
        all_types_data = await model_service.get_model_types(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            },
            type_name=type_name
        )

        skip = (page - 1) * size

        if isinstance(all_types_data, list):
            total = len(all_types_data)
            paginated_data = all_types_data[skip:skip + size]
            return _create_pagination_response(paginated_data, total, page, size)

        elif isinstance(all_types_data, dict) and 'data' in all_types_data:
            data = all_types_data.get('data', [])
            total_from_api = all_types_data.get('total', len(data))

            start_idx = skip
            end_idx = skip + size
            final_data = data[start_idx:end_idx] if start_idx < len(data) else []

            return _create_pagination_response(final_data, total_from_api, page, size)

        else:
            return _create_pagination_response([], 0, page, size)

    except Exception as e:
        logger.error(f"Error getting model types: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model types: {str(e)}"
        )


@router.get("/formats")
async def get_model_formats(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        format_name: Optional[str] = Query(None, description="모델 포맷 이름으로 필터링"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    사용 가능한 모델 포맷 목록 조회 (페이지네이션 포함)
    """
    try:
        all_formats_data = await model_service.get_model_formats(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            },
            format_name=format_name
        )

        skip = (page - 1) * size

        if isinstance(all_formats_data, list):
            total = len(all_formats_data)
            paginated_data = all_formats_data[skip:skip + size]
            return _create_pagination_response(paginated_data, total, page, size)

        elif isinstance(all_formats_data, dict) and 'data' in all_formats_data:
            data = all_formats_data.get('data', [])
            total_from_api = all_formats_data.get('total', len(data))

            start_idx = skip
            end_idx = skip + size
            final_data = data[start_idx:end_idx] if start_idx < len(data) else []

            return _create_pagination_response(final_data, total_from_api, page, size)

        else:
            return _create_pagination_response([], 0, page, size)

    except Exception as e:
        logger.error(f"Error getting model formats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model formats: {str(e)}"
        )



@router.get("/{model_id}", response_model=ModelResponse)
async def get_model(
        model_id: int = Path(..., description="모델 ID (Surro API 모델 ID)"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    특정 모델 상세 정보 조회

    - 현재 사용자가 소유한 모델인지 확인 후 상세 정보를 반환합니다.
    """
    try:
        # 1. 사용자가 해당 모델을 소유하고 있는지 확인
        is_owner = model_crud.check_model_ownership(db, model_id, current_user.member_id)

        # 2. 소유하지 않았다면, 카탈로그 모델인지 확인
        catalog_model = db.query(Model).filter(
            Model.is_catalog == True,
            Model.deleted_at.is_(None),
            Model.surro_model_id == model_id
        ).first()

        # 3. 사용자 소유 모델도 아니고, 카탈로그 모델도 아닐 경우 접근 불가
        if not is_owner and not catalog_model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model {model_id} not found or access denied"
            )

        # 2. Surro API에서 모델 상세 정보 조회
        model = await model_service.get_model(
            model_id=model_id,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        if not model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model {model_id} not found"
            )

        return model

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting model {model_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model: {str(e)}"
        )


@router.post("", response_model=ModelResponse)
async def create_model(
        name: str = Form(..., description="모델 이름"),
        description: str = Form(..., description="모델 설명"),
        provider_id: int = Form(..., description="프로바이더 ID"),
        type_id: int = Form(..., description="모델 타입 ID"),
        format_id: int = Form(..., description="모델 포맷 ID"),
        parent_model_id: Optional[int] = Form(None, description="부모 모델 ID"),
        registry_schema: Optional[str] = Form(None, description="모델 레지스트리 스키마"),
        file: Optional[UploadFile] = File(None, description="모델 파일"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    새 모델 생성

    - Surro API에 모델을 생성한 후, Inno DB에 사용자-모델 매핑을 저장합니다.
    """
    try:
        # 파일 처리
        file_data = None
        file_name = None
        if file:
            file_data = await file.read()
            file_name = file.filename

        # 모델 생성 요청 데이터 구성
        model_data = ModelCreateRequest(
            name=name,
            description=description,
            provider_id=provider_id,
            type_id=type_id,
            format_id=format_id,
            parent_model_id=parent_model_id,
            registry_schema=registry_schema
        )

        # 1. Surro API를 통해 모델 생성
        created_model = await model_service.create_model(
            model_data=model_data,
            file_data=file_data,
            file_name=file_name,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 2. Inno DB에 사용자-모델 매핑 저장
        try:
            model_crud.create_model_mapping(
                db=db,
                surro_model_id=created_model.id,
                member_id=current_user.member_id,
                model_name=created_model.name
            )
            logger.info(f"Created model mapping: surro_id={created_model.id}, member_id={current_user.member_id}")
        except Exception as mapping_error:
            logger.error(f"Failed to create model mapping: {str(mapping_error)}")
            # 매핑 저장에 실패해도 Surro API에는 이미 생성되었으므로, 경고만 로그
            logger.warning(f"Model {created_model.id} created in Surro API but mapping failed")

        return created_model

    except Exception as e:
        logger.error(f"Error creating model for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create model: {str(e)}"
        )


@router.delete("/{model_id}")
async def delete_model(
        model_id: int = Path(..., description="모델 ID (Surro API 모델 ID)"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 삭제

    - 현재 사용자가 소유한 모델만 삭제할 수 있습니다.
    - Surro API에서 모델을 삭제한 후, Inno DB의 매핑도 삭제합니다.
    """
    try:
        # 1. 사용자가 해당 모델을 소유하고 있는지 확인
        if not model_crud.check_model_ownership(db, model_id, current_user.member_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model {model_id} not found or access denied"
            )

        # 2. Surro API에서 모델 삭제
        success = await model_service.delete_model(
            model_id=model_id,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model {model_id} not found in Surro API"
            )

        # 3. Inno DB에서 매핑 삭제
        model_crud.delete_model_mapping(db, model_id, current_user.member_id)

        logger.info(f"Deleted model {model_id} and mapping for user {current_user.member_id}")
        return {"message": f"Model {model_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting model {model_id} for user {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete model: {str(e)}"
        )