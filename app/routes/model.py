from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, File, UploadFile, Form
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import logging
import json

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


@router.get("/custom-models", response_model=ModelListWrapper)
async def get_user_models(
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        provider_id: Optional[int] = Query(None),
        type_id: Optional[int] = Query(None),
        format_id: Optional[int] = Query(None),
        search: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    현재 로그인한 사용자가 생성한 모델만 조회
    """
    try:
        # 1. 사용자 커스텀 모델 ID 조회
        user_model_ids = model_crud.get_models_by_member_id(
            db, current_user.member_id, skip=skip, limit=limit
        )

        # 2. Surro API 모델 전체 조회
        all_surro_models = await model_service.get_models(
            skip=0, limit=1000,
            provider_id=provider_id, type_id=type_id,
            format_id=format_id, search=search,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 3. 사용자 커스텀 모델만 필터링
        filtered_models = [m for m in all_surro_models if m.id in user_model_ids]

        # 4. 사용자 정보 생성
        member_info = InnoUserInfo(
            member_id=current_user.member_id,
            role=current_user.role,
            name=current_user.name
        )

        # 5. surro_data + member_info 합치기
        wrapped_models = []
        for surro_model in filtered_models:
            model_dict = surro_model.model_dump()
            model_dict["member_info"] = member_info.model_dump()
            wrapped_models.append(ModelWithMemberInfo(**model_dict))

        return ModelListWrapper(data=wrapped_models)

    except Exception as e:
        logger.error(f"Error getting user models for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get user models: {str(e)}"
        )


@router.get("/model-catalog", response_model=ModelListWrapper)
async def get_catalog_models(
        skip: int = Query(0, ge=0),
        limit: int = Query(100, ge=1, le=1000),
        provider_id: Optional[int] = Query(None),
        type_id: Optional[int] = Query(None),
        format_id: Optional[int] = Query(None),
        search: Optional[str] = Query(None),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 카탈로그 조회 (is_catalog가 true인 모델만)
    """
    try:
        # 1. 카탈로그 모델 ID 조회
        catalog_models = db.query(Model).filter(
            Model.is_catalog == True,
            Model.deleted_at.is_(None)
        ).all()
        catalog_ids = [m.surro_model_id for m in catalog_models]

        # 2. Surro API 모델 전체 조회
        all_surro_models = await model_service.get_models(
            skip=0, limit=1000,
            provider_id=provider_id, type_id=type_id,
            format_id=format_id, search=search,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 3. 카탈로그 모델만 필터링
        filtered_models = [m for m in all_surro_models if m.id in catalog_ids]

        # 4. 사용자 정보 생성
        member_info = InnoUserInfo(
            member_id=current_user.member_id,
            role=current_user.role,
            name=current_user.name
        )

        # 5. surro_data + member_info 합치기
        wrapped_models = []
        for surro_model in filtered_models:
            model_dict = surro_model.model_dump()
            model_dict["member_info"] = member_info.model_dump()
            wrapped_models.append(ModelWithMemberInfo(**model_dict))

        return ModelListWrapper(data=wrapped_models)

    except Exception as e:
        logger.error(f"Error getting catalog models: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get catalog models: {str(e)}"
        )

@router.get("/providers")
async def get_providers(
        db: Session = Depends(get_db),
        provider_name: str = Query(None),
        current_user: Member = Depends(get_current_user)
):
    """
    사용 가능한 프로바이더 목록 조회
    """
    try:
        providers = await model_service.get_model_providers(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            },
            provider_name=provider_name
        )
        return providers
    except Exception as e:
        logger.error(f"Error getting providers: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get providers: {str(e)}"
        )


@router.get("/types")
async def get_model_types(
        db: Session = Depends(get_db),
        type_name: str = Query(None),
        current_user: Member = Depends(get_current_user)
):
    """
    사용 가능한 모델 타입 목록 조회
    """
    try:
        types = await model_service.get_model_types(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            },
            type_name=type_name
        )
        return types
    except Exception as e:
        logger.error(f"Error getting model types: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model types: {str(e)}"
        )


@router.get("/formats")
async def get_model_formats(
        db: Session = Depends(get_db),
        format_name: str = Query(None),
        current_user: Member = Depends(get_current_user)
):
    """
    사용 가능한 모델 포맷 목록 조회
    """
    try:
        formats = await model_service.get_model_formats(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            },
            format_name=format_name
        )
        return formats
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
        if not model_crud.check_model_ownership(db, model_id, current_user.member_id):
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