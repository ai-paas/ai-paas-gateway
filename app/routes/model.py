from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, File, UploadFile, Form
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import logging
import json

from app.database import get_db
from app.auth import get_current_user, get_current_admin_user
from app.cruds import model_crud
from app.schemas.model import (
    ModelCreate, ModelUpdate, ModelResponse,
    ModelListResponse, ModelCreateRequest,
    ModelTestRequest, ModelTestResponse,
    ExternalModelResponse
)
from app.services.model_service import model_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["Models"])


@router.get("", response_model=List[ModelResponse])
async def get_models(
        skip: int = Query(0, ge=0, description="건너뛸 항목 수"),
        limit: int = Query(100, ge=1, le=1000, description="반환할 최대 항목 수"),
        provider_id: Optional[int] = Query(None, description="프로바이더 ID로 필터링"),
        type_id: Optional[int] = Query(None, description="타입 ID로 필터링"),
        format_id: Optional[int] = Query(None, description="포맷 ID로 필터링"),
        search: Optional[str] = Query(None, description="이름 또는 설명 검색"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 목록 조회

    - 외부 API를 통해 모델 목록을 가져옵니다.
    - 필터링 및 검색 기능을 제공합니다.
    """
    try:
        # 외부 API 호출
        models = await model_service.get_models(
            skip=skip,
            limit=limit,
            provider_id=provider_id,
            type_id=type_id,
            format_id=format_id,
            search=search,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )
        return models
    except Exception as e:
        logger.error(f"Error getting models: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get models: {str(e)}"
        )


@router.get("/{model_id}", response_model=ModelResponse)
async def get_model(
        model_id: int = Path(..., description="모델 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    특정 모델 상세 정보 조회

    - 모델 ID로 특정 모델의 상세 정보를 조회합니다.
    """
    try:
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
        logger.error(f"Error getting model {model_id}: {str(e)}")
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

    - 모델 메타데이터와 선택적으로 파일을 업로드합니다.
    - multipart/form-data 형식으로 전송해야 합니다.
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

        # 외부 API를 통해 모델 생성
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

        return created_model

    except Exception as e:
        logger.error(f"Error creating model: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create model: {str(e)}"
        )


@router.put("/{model_id}", response_model=ModelResponse)
async def update_model(
        model_id: int = Path(..., description="모델 ID"),
        model_update: ModelUpdate = ...,
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 정보 수정

    - 기존 모델의 메타데이터를 수정합니다.
    """
    try:
        updated_model = await model_service.update_model(
            model_id=model_id,
            model_data=model_update,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        if not updated_model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Model {model_id} not found"
            )

        return updated_model

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating model {model_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update model: {str(e)}"
        )


@router.delete("/{model_id}")
async def delete_model(
        model_id: int = Path(..., description="모델 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_admin_user)  # 관리자만 삭제 가능
):
    """
    모델 삭제

    - 관리자 권한이 필요합니다.
    - 소프트 삭제를 수행합니다.
    """
    try:
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
                detail=f"Model {model_id} not found"
            )

        return {"message": f"Model {model_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting model {model_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete model: {str(e)}"
        )


@router.post("/{model_id}/test", response_model=ModelTestResponse)
async def test_model(
        model_id: int = Path(..., description="모델 ID"),
        test_request: ModelTestRequest = ...,
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 테스트 실행

    - 특정 모델을 테스트 데이터로 실행합니다.
    - 결과와 실행 시간을 반환합니다.
    """
    try:
        result = await model_service.test_model(
            model_id=model_id,
            input_data=test_request.input_data,
            parameters=test_request.parameters,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        return ModelTestResponse(
            model_id=model_id,
            status=result.get('status', 'completed'),
            output=result.get('output'),
            error=result.get('error'),
            execution_time=result.get('execution_time')
        )

    except Exception as e:
        logger.error(f"Error testing model {model_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to test model: {str(e)}"
        )


@router.get("/{model_id}/registry")
async def get_model_registry(
        model_id: int = Path(..., description="모델 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 레지스트리 정보 조회

    - 모델의 MLflow 레지스트리 정보를 조회합니다.
    """
    try:
        registry = await model_service.get_model_registry(
            model_id=model_id,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        if not registry:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Registry for model {model_id} not found"
            )

        return registry

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting registry for model {model_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model registry: {str(e)}"
        )


@router.get("/providers/list")
async def get_providers(
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    사용 가능한 프로바이더 목록 조회
    """
    try:
        providers = await model_service.get_providers(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )
        return providers
    except Exception as e:
        logger.error(f"Error getting providers: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get providers: {str(e)}"
        )


@router.get("/types/list")
async def get_model_types(
        db: Session = Depends(get_db),
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
            }
        )
        return types
    except Exception as e:
        logger.error(f"Error getting model types: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model types: {str(e)}"
        )


@router.get("/formats/list")
async def get_model_formats(
        db: Session = Depends(get_db),
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
            }
        )
        return formats
    except Exception as e:
        logger.error(f"Error getting model formats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model formats: {str(e)}"
        )