import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, File, UploadFile, Form
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.cruds import model_crud
from app.database import get_db
from app.models import Member, Model
from app.schemas.model import (
    ModelResponse, ModelCreateRequest,
    ModelCreateResponse,
    InnoUserInfo
)
from app.services.model_service import model_service

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


@router.post("", response_model=ModelCreateResponse)
async def create_model(
        name: str = Form(..., description="모델 이름"),
        repo_id: str = Form(..., description="모델 저장소 ID"),
        provider_id: int = Form(..., description="프로바이더 ID"),
        type_id: int = Form(..., description="모델 타입 ID"),
        format_id: int = Form(..., description="모델 포맷 ID"),
        description: Optional[str] = Form(None, description="모델 설명"),
        parent_model_id: Optional[int] = Form(None, description="부모 모델 ID (내부 시스템 전용)"),
        task: Optional[str] = Form(None, max_length=500, description="모델 태스크"),
        parameter: Optional[str] = Form(None, max_length=100, description="모델 파라미터"),
        sample_code: Optional[str] = Form(None, description="샘플 코드"),
        model_registry_schema: Optional[str] = Form(None, description="모델 레지스트리 스키마 (내부 시스템 전용)"),
        file: Optional[UploadFile] = File(None, description="모델 파일 (binary)"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 등록

    Model Registry에 모델을 등록합니다.
    제공자(provider)에 따라 HuggingFace 모델 또는 커스텀 모델로 등록됩니다.
    게이트웨이는 MLOps에 등록한 뒤, 게이트웨이 DB에 사용자-모델 매핑을 저장합니다
    (admin이 호출하면 `is_catalog=true`로 분류).

    ## Request Body (multipart/form-data)
    - **name** (str, required): 모델 이름
        - 모델을 식별하기 위한 이름
        - YOLOX 모델인 경우 학습 가능 모델로 자동 설정됨
    - **description** (str, optional): 모델 설명
    - **repo_id** (str, optional): 모델 저장소 ID
        - HuggingFace 모델인 경우: repository ID (예: "google/owlv2-base-patch16")
        - 커스텀 모델인 경우: 모델 식별자
        - 생략 가능 (null 허용)
    - **provider_id** (int, required): 모델 제공자 ID
        - **중요**: `GET /api/v1/models/providers` 로 조회 후 `id` 값을 사용
        - 하드코딩된 숫자 값을 사용하지 마세요
    - **type_id** (int, required): 모델 타입 ID
        - **중요**: `GET /api/v1/models/types` 로 조회 후 `id` 값을 사용
    - **format_id** (int, required): 모델 포맷 ID
        - **중요**: `GET /api/v1/models/formats` 로 조회 후 `id` 값을 사용
    - **parent_model_id** (int, optional): 부모 모델 ID
        - 내부 시스템 전용 — 프론트엔드에서 전달 금지
    - **task** (str, optional): 모델 태스크
        - 허용 값: "embedding", "text-generation", "object-detection" 중 하나
        - 다른 값 입력 시 422 에러 발생
    - **parameter** (str, optional): 모델 파라미터 (최대 100자)
    - **sample_code** (str, optional): 샘플 코드
    - **file** (UploadFile, optional): 커스텀 모델 파일 (binary)
    - **model_registry_schema** (str, optional): 모델 레지스트리 스키마 (JSON 문자열)
        - 내부 시스템 전용 — 프론트엔드에서 전달 금지

    ## Response (ModelBriefReadSchema)
    - **id** (int): 모델 고유 ID
    - **name** (str): 모델 이름
    - **description** (str, optional): 모델 설명
    - **repo_id** (str, optional): 모델 저장소 ID
    - **provider_info** (ModelProviderReadSchema): 모델 제공자 정보
        - id (int): 제공자 ID
        - name (str): 제공자 이름
        - description (str): 제공자 설명
    - **type_info** (ModelTypeReadSchema): 모델 타입 정보
        - id / name / description
    - **format_info** (ModelFormatReadSchema): 모델 포맷 정보
        - id / name / description
    - **parent_model_id** (int, optional): 부모 모델 ID
    - **task** (str, optional): 모델 태스크
    - **parameter** (str, optional): 모델 파라미터
    - **sample_code** (str, optional): 샘플 코드
    - **registry** (ModelRegistryReadSchema): 모델 레지스트리 정보
        - id (int): 레지스트리 ID
        - artifact_path (str): 아티팩트 경로
        - uri (str): 모델 URI
        - run_id (str, optional): MLflow 실행 ID
        - reference_model_id (int): 참조 모델 ID
        - created_at / updated_at (datetime)
    - **created_at** (datetime): 모델 생성 시각
    - **updated_at** (datetime): 모델 수정 시각

    ## Notes
    - **ID 값 조회**: `provider_id`, `type_id`, `format_id`는 각각 해당 조회 API를 먼저 호출하여 확인 후 사용
    - HuggingFace 모델인 경우 `provider_id`가 huggingface의 ID와 일치해야 함
    - 커스텀 모델인 경우 `provider_id`가 custom의 ID와 일치해야 하며 `file` 필요
    - YOLOX 모델인 경우에만 자동으로 학습 가능 모델(learning_enable_yn=True)로 설정
    - `parent_model_id`와 `model_registry_schema`는 내부 시스템 전용 — 프론트엔드에서 전달 금지
    - MLOps에는 등록되었으나 게이트웨이 DB 매핑 저장이 실패하면 경고만 로그하고 응답은 그대로 반환

    ## Errors
    - **400**: 유효하지 않은 요청 또는 필수 파라미터 누락
    - **401**: 인증되지 않은 사용자
    - **500**: 모델 등록 중 서버 내부 오류
    """
    try:
        # 파일 처리
        file_data = None
        file_name = None
        if file:
            file_data = await file.read()
            file_name = file.filename
            logger.info(f"File uploaded: {file_name}, size: {len(file_data)} bytes")

        # 모델 생성 요청 데이터 구성
        model_data = ModelCreateRequest(
            name=name,
            repo_id=repo_id,
            description=description,
            provider_id=provider_id,
            type_id=type_id,
            format_id=format_id,
            parent_model_id=parent_model_id,
            task=task,
            parameter=parameter,
            sample_code=sample_code,
            model_registry_schema=model_registry_schema
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
            # 관리자(admin)가 생성한 모델은 카탈로그 모델로 설정
            is_catalog = current_user.role.lower() == 'admin'

            model_crud.create_model_mapping(
                db=db,
                surro_model_id=created_model.id,
                member_id=current_user.member_id,
                model_name=created_model.name,
                is_catalog=is_catalog
            )
            logger.info(
                f"Created model mapping: surro_id={created_model.id}, "
                f"member_id={current_user.member_id}, is_catalog={is_catalog}"
            )
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


@router.get("")
async def get_all_models(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어"),
        model_type_id: Optional[int] = Query(None, description="모델 타입 ID로 필터링"),
        model_provider_id: Optional[int] = Query(None, description="모델 제공자 ID로 필터링"),
        model_format_id: Optional[int] = Query(None, description="모델 포맷 ID로 필터링"),
        filter_type: Optional[str] = Query(None, description="필터 타입: 'custom'(내 모델만), 'catalog'(카탈로그만), None(전체)"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 목록 조회

    등록된 모델들의 목록을 페이지네이션하여 조회합니다.
    model_type_id, model_provider_id, model_format_id, filter_type을 사용하여 필터링할 수 있습니다.

    게이트웨이는 MLOps 목록을 받아 게이트웨이 DB의 사용자-모델 매핑과 교차하여
    현재 사용자가 접근 가능한 모델(본인 소유 + 카탈로그)만 반환합니다.

    ## Query Parameters
    - **page** (int, optional): 페이지 번호 (1부터 시작, 기본값 1)
    - **size** (int, optional): 페이지당 항목 수 (1-100, 기본값 20)
        - MLOps 원본의 `page_size`에 대응 — 게이트웨이-프론트 계약에 따라 `size`로 노출
    - **search** (str, optional): 이름/설명 검색어 (게이트웨이 확장, MLOps 원본에는 없음)
    - **model_type_id** (int, optional): 모델 타입 ID로 필터링
        - `GET /api/v1/models/types` API로 타입 목록 조회 가능
    - **model_provider_id** (int, optional): 모델 제공자 ID로 필터링
        - `GET /api/v1/models/providers` API로 제공자 목록 조회 가능
    - **model_format_id** (int, optional): 모델 포맷 ID로 필터링
        - `GET /api/v1/models/formats` API로 포맷 목록 조회 가능
    - **filter_type** (str, optional): 목록 구분 필터 (MLOps 원본의 `visibility`에 대응)
        - `catalog`: 카탈로그 모델만 반환 (초기 등록 모델, 최적화 비대상)
        - `custom`: 커스텀 모델만 반환 (사용자가 직접 등록한 모델)
        - 생략 시: 본인 소유 + 카탈로그 전체 반환

    ## Response (WrappedList)
    게이트웨이-프론트 계약에 따라 `{data, total, page, size}` 래퍼로 반환:
    - **data** (List[ModelBriefReadSchema]): 모델 목록
        - id (int): 모델 고유 ID
        - name (str): 모델 이름
        - description (str, optional): 모델 설명
        - repo_id (str, optional): 모델 저장소 ID
        - provider_info (ModelProviderReadSchema): 모델 제공자 정보 (id/name/description)
        - type_info (ModelTypeReadSchema): 모델 타입 정보 (id/name/description)
        - format_info (ModelFormatReadSchema): 모델 포맷 정보 (id/name/description)
        - parent_model_id (int, optional): 부모 모델 ID
        - task (str, optional): 모델 태스크
        - parameter (str, optional): 모델 파라미터
        - sample_code (str, optional): 샘플 코드
        - registry (ModelRegistryReadSchema): 모델 레지스트리 정보
            - id, artifact_path, uri, run_id, reference_model_id, created_at, updated_at
        - learning_enable_yn (bool): 학습 파이프라인 사용 가능 여부
        - opt_enable_yn (bool): 최적화/경량화 대상 여부
        - visibility (str): 모델 분류 (`CATALOG` 또는 `CUSTOM`)
        - created_at (datetime): 모델 생성 시각
        - updated_at (datetime): 모델 수정 시각
    - **total** (int): 필터 조건에 맞는 전체 모델 수
    - **page** (int): 요청한 페이지 번호
    - **size** (int): 요청한 페이지 크기

    ## Notes
    - page와 size 모두 지정되지 않으면 기본값(1, 20)으로 조회합니다
    - 필터링 파라미터(model_type_id, model_provider_id, model_format_id, filter_type)는 함께 사용 가능
    - 게이트웨이는 MLOps에서 받은 목록을 게이트웨이 DB의 매핑 정보로 필터링 후 페이지네이션합니다
    - `search`/`filter_type`은 게이트웨이에서 처리되므로, MLOps에는 전달되지 않을 수 있습니다

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **422**: filter_type 값이 유효하지 않음 ('catalog' 또는 'custom'만 허용)
    - **500**: 서버 내부 오류
    """
    try:
        # 1. Surro API에서 모델 조회 (MLOps 파라미터 변환은 서비스 내부에서 처리)
        all_surro_models = await model_service.get_models(
            skip=0,
            limit=1000,
            search=search,
            provider_id=model_provider_id,
            type_id=model_type_id,
            format_id=model_format_id,
            filter_type=filter_type,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 2. 로컬 DB에서 모델 정보 조회
        user_model_ids = []
        catalog_model_ids = []

        if filter_type != 'catalog':  # catalog만 조회하는 경우가 아니면 user 모델도 조회
            user_models = db.query(Model).filter(
                Model.created_by == current_user.member_id,
                Model.deleted_at.is_(None)
            ).all()
            user_model_ids = [model.surro_model_id for model in user_models if model.surro_model_id]

        if filter_type != 'custom':  # custom만 조회하는 경우가 아니면 catalog 모델도 조회
            catalog_models = db.query(Model).filter(
                Model.is_catalog == True,
                Model.deleted_at.is_(None)
            ).all()
            catalog_model_ids = [model.surro_model_id for model in catalog_models if model.surro_model_id]

        # 3. filter_type에 따라 모델 필터링
        if filter_type == 'custom':
            # 내 모델만
            filtered_models = [m for m in all_surro_models if m.id in user_model_ids]
        elif filter_type == 'catalog':
            # 카탈로그 모델만
            filtered_models = [m for m in all_surro_models if m.id in catalog_model_ids]
        else:
            # 전체 (중복 제거)
            all_model_ids = set(user_model_ids) | set(catalog_model_ids)
            filtered_models = [m for m in all_surro_models if m.id in all_model_ids]

        # 4. 검색어 필터링
        if search:
            search_lower = search.lower()
            filtered_models = [
                m for m in filtered_models
                if search_lower in m.name.lower() or
                   (m.description and search_lower in m.description.lower())
            ]

        # 5. 모델 타입, 제공자, 포맷 필터링
        if model_type_id is not None:
            filtered_models = [
                m for m in filtered_models
                if hasattr(m, 'type_info') and m.type_info and
                   hasattr(m.type_info, 'id') and m.type_info.id == model_type_id
            ]

        if model_provider_id is not None:
            filtered_models = [
                m for m in filtered_models
                if hasattr(m, 'provider_info') and m.provider_info and
                   hasattr(m.provider_info, 'id') and m.provider_info.id == model_provider_id
            ]

        if model_format_id is not None:
            filtered_models = [
                m for m in filtered_models
                if hasattr(m, 'format_info') and m.format_info and
                   hasattr(m.format_info, 'id') and m.format_info.id == model_format_id
            ]

        # 6. 페이지네이션 적용
        total = len(filtered_models)
        skip = (page - 1) * size
        paginated_models = filtered_models[skip:skip + size]

        # 7. ModelResponse로 변환
        wrapped_models = [ModelResponse(**m.model_dump()) for m in paginated_models]

        return _create_pagination_response(wrapped_models, total, page, size)

    except Exception as e:
        logger.error(f"Error getting all models for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get models: {str(e)}"
        )

@router.get("/custom-models")
async def get_user_models(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어"),
        model_type_id: Optional[int] = Query(None, description="모델 타입 ID로 필터링"),
        model_provider_id: Optional[int] = Query(None, description="모델 제공자 ID로 필터링"),
        model_format_id: Optional[int] = Query(None, description="모델 포맷 ID로 필터링"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    내 커스텀 모델 목록 조회 (게이트웨이 확장)

    현재 로그인한 사용자가 직접 등록한 커스텀 모델만 조회합니다.
    이 엔드포인트는 게이트웨이 전용이며, MLOps 원본 스펙에는 없습니다.
    `GET /api/v1/models?filter_type=custom` 과 동등한 결과를 반환합니다.

    ## Query Parameters
    - **page** (int, optional): 페이지 번호 (1부터 시작, 기본값 1)
    - **size** (int, optional): 페이지당 항목 수 (1-100, 기본값 20)
    - **search** (str, optional): 이름/설명 검색어 (게이트웨이 자체 필터)
    - **model_type_id** (int, optional): 모델 타입 ID 필터
    - **model_provider_id** (int, optional): 모델 제공자 ID 필터
    - **model_format_id** (int, optional): 모델 포맷 ID 필터

    ## Response (WrappedList)
    `{data, total, page, size}` 형식으로 반환:
    - **data** (List[ModelBriefReadSchema]): 모델 목록 (필드는 `GET /models` 응답과 동일)
    - **total** (int): 필터 조건에 맞는 전체 커스텀 모델 수
    - **page** (int): 요청한 페이지 번호
    - **size** (int): 요청한 페이지 크기

    ## Notes
    - 게이트웨이 DB의 `created_by == 현재 사용자`인 모델만 대상
    - 삭제된 모델(`deleted_at` 설정됨)은 제외
    - MLOps 원본에는 없는 게이트웨이 확장 엔드포인트

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류
    """
    try:
        # 1. 사용자 커스텀 모델 ID 목록 조회 (전체)
        user_models = db.query(Model).filter(
            Model.created_by == current_user.member_id,
            Model.deleted_at.is_(None)
        ).all()

        user_model_ids = [model.surro_model_id for model in user_models if model.surro_model_id]

        if not user_model_ids:
            return _create_pagination_response([], 0, page, size)

        # 2. Surro API에서 전체 모델 조회 (필터 없이)
        all_surro_models = await model_service.get_models(
            skip=0,
            limit=1000,
            search=None,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 3. 사용자 커스텀 모델만 필터링
        filtered_models = [m for m in all_surro_models if m.id in user_model_ids]

        # 4. 로컬에서 검색어 필터링 적용
        if search:
            search_lower = search.lower()
            filtered_models = [
                m for m in filtered_models
                if search_lower in m.name.lower() or
                   (m.description and search_lower in m.description.lower())
            ]

        # 5. 모델 타입, 제공자, 포맷 필터링 (중첩 객체 구조)
        if model_type_id is not None:
            filtered_models = [
                m for m in filtered_models
                if hasattr(m, 'type_info') and m.type_info and
                   hasattr(m.type_info, 'id') and m.type_info.id == model_type_id
            ]

        if model_provider_id is not None:
            filtered_models = [
                m for m in filtered_models
                if hasattr(m, 'provider_info') and m.provider_info and
                   hasattr(m.provider_info, 'id') and m.provider_info.id == model_provider_id
            ]

        if model_format_id is not None:
            filtered_models = [
                m for m in filtered_models
                if hasattr(m, 'format_info') and m.format_info and
                   hasattr(m.format_info, 'id') and m.format_info.id == model_format_id
            ]

        # 6. 필터링된 결과에 페이지네이션 적용
        total = len(filtered_models)
        skip = (page - 1) * size
        paginated_models = filtered_models[skip:skip + size]

        # 7. ModelResponse로 변환
        wrapped_models = [ModelResponse(**m.model_dump()) for m in paginated_models]

        return _create_pagination_response(wrapped_models, total, page, size)

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
        search: Optional[str] = Query(None, description="검색어"),
        model_type_id: Optional[int] = Query(None, description="모델 타입 ID로 필터링"),
        model_provider_id: Optional[int] = Query(None, description="모델 제공자 ID로 필터링"),
        model_format_id: Optional[int] = Query(None, description="모델 포맷 ID로 필터링"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    카탈로그 모델 목록 조회 (게이트웨이 확장)

    관리자(admin)가 등록하여 카탈로그로 분류된(`is_catalog=true`) 모델만 조회합니다.
    모든 사용자가 열람 가능한 공용 모델 목록입니다.
    이 엔드포인트는 게이트웨이 전용이며, MLOps 원본 스펙에는 없습니다.
    `GET /api/v1/models?filter_type=catalog` 과 동등한 결과를 반환합니다.

    ## Query Parameters
    - **page** (int, optional): 페이지 번호 (1부터 시작, 기본값 1)
    - **size** (int, optional): 페이지당 항목 수 (1-100, 기본값 20)
    - **search** (str, optional): 이름/설명 검색어 (게이트웨이 자체 필터)
    - **model_type_id** (int, optional): 모델 타입 ID 필터
    - **model_provider_id** (int, optional): 모델 제공자 ID 필터
    - **model_format_id** (int, optional): 모델 포맷 ID 필터

    ## Response (WrappedList)
    `{data, total, page, size}` 형식으로 반환:
    - **data** (List[ModelBriefReadSchema]): 모델 목록 (필드는 `GET /models` 응답과 동일)
    - **total** (int): 필터 조건에 맞는 전체 카탈로그 모델 수
    - **page** (int): 요청한 페이지 번호
    - **size** (int): 요청한 페이지 크기

    ## Notes
    - 게이트웨이 DB의 `is_catalog=true`이며 `deleted_at`이 없는 모델만 대상
    - 카탈로그 모델은 관리자 등록 시점에 자동으로 분류되며, 사용자 삭제 불가
    - MLOps 원본에는 없는 게이트웨이 확장 엔드포인트

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류
    """
    try:
        # 1. 카탈로그 모델 ID 목록 조회 (전체)
        catalog_models = db.query(Model).filter(
            Model.is_catalog == True,
            Model.deleted_at.is_(None)
        ).all()

        catalog_model_ids = [model.surro_model_id for model in catalog_models if model.surro_model_id]

        if not catalog_model_ids:
            return _create_pagination_response([], 0, page, size)

        # 2. Surro API에서 전체 모델 조회 (필터 없이)
        all_surro_models = await model_service.get_models(
            skip=0,
            limit=1000,
            search=None,
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            }
        )

        # 3. 카탈로그 모델만 필터링
        filtered_models = [m for m in all_surro_models if m.id in catalog_model_ids]

        # 4. 로컬에서 검색어 필터링 적용
        if search:
            search_lower = search.lower()
            filtered_models = [
                m for m in filtered_models
                if search_lower in m.name.lower() or
                   (m.description and search_lower in m.description.lower())
            ]

        # 5. 모델 타입, 제공자, 포맷 필터링 (중첩 객체 구조)
        if model_type_id is not None:
            filtered_models = [
                m for m in filtered_models
                if hasattr(m, 'type_info') and m.type_info and
                   hasattr(m.type_info, 'id') and m.type_info.id == model_type_id
            ]

        if model_provider_id is not None:
            filtered_models = [
                m for m in filtered_models
                if hasattr(m, 'provider_info') and m.provider_info and
                   hasattr(m.provider_info, 'id') and m.provider_info.id == model_provider_id
            ]

        if model_format_id is not None:
            filtered_models = [
                m for m in filtered_models
                if hasattr(m, 'format_info') and m.format_info and
                   hasattr(m.format_info, 'id') and m.format_info.id == model_format_id
            ]

        # 6. 필터링된 결과에 페이지네이션 적용
        total = len(filtered_models)
        skip = (page - 1) * size
        paginated_models = filtered_models[skip:skip + size]

        # 7. ModelResponse로 변환
        wrapped_models = [ModelResponse(**m.model_dump()) for m in paginated_models]

        return _create_pagination_response(wrapped_models, total, page, size)

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
    모델 제공자 조회

    등록 가능한 모델 제공자 목록을 조회하거나, 이름으로 특정 제공자를 조회합니다.

    ## Query Parameters
    - **page** (int, optional): 페이지 번호 (1부터 시작, 기본값 1)
    - **size** (int, optional): 페이지당 항목 수 (1-100, 기본값 20)
    - **provider_name** (str, optional): 조회할 모델 제공자 이름
        - 제공 시: 해당 이름이 포함된 제공자만 반환 (게이트웨이에서 부분 일치 필터)
        - 생략 시: 전체 모델 제공자 목록 반환
        - 예: "huggingface", "ollama", "custom" 등

    ## Response (WrappedList)
    MLOps 원본은 `ModelProviderReadSchema` 단일 객체 또는 목록을 반환하지만,
    게이트웨이는 프론트 계약에 따라 `{data, total, page, size}` 래퍼로 반환:
    - **data** (List[ModelProviderReadSchema]): 제공자 목록
        - id (int): 모델 제공자 ID
        - name (str): 모델 제공자 이름
        - description (str): 모델 제공자 설명
    - **total** (int): 필터 조건에 맞는 전체 제공자 수
    - **page** (int): 요청한 페이지 번호
    - **size** (int): 요청한 페이지 크기

    ## Notes
    - `provider_name` 필터는 게이트웨이에서 부분 일치(lowercase `in` 비교)로 처리
    - 조회된 `id` 값은 `POST /models` 의 `provider_id` 파라미터에 사용
    - 하드코딩된 숫자 값 대신 반드시 이 API로 조회한 `id`를 사용할 것

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류
    """
    try:
        all_providers_data = await model_service.get_model_providers(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            },
            provider_name=None
        )

        # 데이터 추출
        if isinstance(all_providers_data, list):
            data = all_providers_data
        elif isinstance(all_providers_data, dict) and 'data' in all_providers_data:
            data = all_providers_data.get('data', [])
        else:
            data = []

        # 로컬에서 provider_name 필터링
        if provider_name and data:
            data = [
                fmt for fmt in data
                if provider_name.lower() in fmt.get('name', '').lower()
            ]

        # 페이지네이션 적용
        total = len(data)
        skip = (page - 1) * size
        paginated_data = data[skip:skip + size]

        return _create_pagination_response(paginated_data, total, page, size)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting model providers: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model providers: {str(e)}"
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
    모델 타입 조회

    등록 가능한 모델 타입 목록을 조회하거나, 이름으로 특정 타입을 조회합니다.

    ## Query Parameters
    - **page** (int, optional): 페이지 번호 (1부터 시작, 기본값 1)
    - **size** (int, optional): 페이지당 항목 수 (1-100, 기본값 20)
    - **type_name** (str, optional): 조회할 모델 타입 이름
        - 제공 시: 해당 이름이 포함된 타입만 반환 (게이트웨이에서 부분 일치 필터)
        - 생략 시: 전체 모델 타입 목록 반환
        - 예: "Object Detection Model", "Fine-tuned Model" 등

    ## Response (WrappedList)
    MLOps 원본은 `ModelTypeReadSchema` 단일 객체 또는 목록을 반환하지만,
    게이트웨이는 프론트 계약에 따라 `{data, total, page, size}` 래퍼로 반환:
    - **data** (List[ModelTypeReadSchema]): 타입 목록
        - id (int): 모델 타입 ID
        - name (str): 모델 타입 이름
        - description (str): 모델 타입 설명
    - **total** (int): 필터 조건에 맞는 전체 타입 수
    - **page** (int): 요청한 페이지 번호
    - **size** (int): 요청한 페이지 크기

    ## Notes
    - `type_name` 필터는 게이트웨이에서 부분 일치(lowercase `in` 비교)로 처리
    - 조회된 `id` 값은 `POST /models` 의 `type_id` 파라미터에 사용
    - 하드코딩된 숫자 값 대신 반드시 이 API로 조회한 `id`를 사용할 것

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류
    """
    try:
        all_types_data = await model_service.get_model_types(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            },
            type_name=None
        )

        # 데이터 추출
        if isinstance(all_types_data, list):
            data = all_types_data
        elif isinstance(all_types_data, dict) and 'data' in all_types_data:
            data = all_types_data.get('data', [])
        else:
            data = []

        # 로컬에서 type_name 필터링
        if type_name and data:
            data = [
                fmt for fmt in data
                if type_name.lower() in fmt.get('name', '').lower()
            ]

        # 페이지네이션 적용
        total = len(data)
        skip = (page - 1) * size
        paginated_data = data[skip:skip + size]

        return _create_pagination_response(paginated_data, total, page, size)

    except HTTPException:
        raise
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
    모델 포맷 조회

    등록 가능한 모델 포맷 목록을 조회하거나, 이름으로 특정 포맷을 조회합니다.

    ## Query Parameters
    - **page** (int, optional): 페이지 번호 (1부터 시작, 기본값 1)
    - **size** (int, optional): 페이지당 항목 수 (1-100, 기본값 20)
    - **format_name** (str, optional): 조회할 모델 포맷 이름
        - 제공 시: 해당 이름이 포함된 포맷만 반환 (게이트웨이에서 부분 일치 필터)
        - 생략 시: 전체 모델 포맷 목록 반환
        - 예: "transformers", "sentence-transformers", "gguf", "bge-m3" 등

    ## Response (WrappedList)
    MLOps 원본은 `ModelFormatReadSchema` 단일 객체 또는 목록을 반환하지만,
    게이트웨이는 프론트 계약에 따라 `{data, total, page, size}` 래퍼로 반환:
    - **data** (List[ModelFormatReadSchema]): 포맷 목록
        - id (int): 모델 포맷 ID
        - name (str): 모델 포맷 이름
        - description (str): 모델 포맷 설명
    - **total** (int): 필터 조건에 맞는 전체 포맷 수
    - **page** (int): 요청한 페이지 번호
    - **size** (int): 요청한 페이지 크기

    ## Notes
    - `format_name` 필터는 게이트웨이에서 부분 일치(lowercase `in` 비교)로 처리
    - 조회된 `id` 값은 `POST /models` 의 `format_id` 파라미터에 사용
    - 하드코딩된 숫자 값 대신 반드시 이 API로 조회한 `id`를 사용할 것

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류
    """
    try:
        # format_name 없이 전체 데이터 가져오기
        all_formats_data = await model_service.get_model_formats(
            user_info={
                'member_id': current_user.member_id,
                'role': current_user.role,
                'name': current_user.name
            },
            format_name=None  # API 파라미터로 전달하지 않음
        )

        # 데이터 추출
        if isinstance(all_formats_data, list):
            data = all_formats_data
        elif isinstance(all_formats_data, dict) and 'data' in all_formats_data:
            data = all_formats_data.get('data', [])
        else:
            data = []

        # 로컬에서 format_name 필터링
        if format_name and data:
            data = [
                fmt for fmt in data
                if format_name.lower() in fmt.get('name', '').lower()
            ]

        # 페이지네이션 적용
        total = len(data)
        skip = (page - 1) * size
        paginated_data = data[skip:skip + size]

        return _create_pagination_response(paginated_data, total, page, size)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting model formats: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get model formats: {str(e)}"
        )

@router.post("/auto-generate")
async def auto_generate_model(
        model_key: str = Query(..., description="등록할 사전 정의 모델 키"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    사전 정의 모델 자동 등록

    사전 정의된 모델 목록에서 선택하여 자동으로 등록합니다.
    `POST /api/v1/models`와 동일한 등록 프로세스를 수행하되,
    모델의 provider, type, format 등의 메타 정보가 MLOps 내부에서 자동으로 설정됩니다.

    ## Query Parameters
    - **model_key** (str, required): 등록할 사전 정의 모델 키
        - `hustvl/yolos-tiny`: YOLOS Tiny (object-detection, HuggingFace, pytorch)
        - `hustvl/yolos-small`: YOLOS Small (object-detection, HuggingFace, pytorch)
        - `facebook/detr-resnet-50`: DETR ResNet-50 (object-detection, HuggingFace, pytorch)
        - `facebook/detr-resnet-101`: DETR ResNet-101 (object-detection, HuggingFace, pytorch)
        - `ahmgam/medllama3-v20:latest`: MedLlama3 (text-generation, Ollama, gguf)
        - `bge-m3`: BGE-M3 Embedding (embedding, Ollama, gguf)
        - `yolox_s`: YOLOX-S (object-detection, Custom, yolox) — 가중치 자동 다운로드
        - `yolox_m`: YOLOX-M (object-detection, Custom, yolox) — 가중치 자동 다운로드
        - `qwq:32b`: QwQ-32B (text-generation, Ollama, gguf)
        - `qwen3:32b`: Qwen3-32B (text-generation, Ollama, gguf)
        - `qwen3:30b`: Qwen3-30B (text-generation, Ollama, gguf)
        - `gpt-oss:20b`: GPT-OSS-20B (text-generation, Ollama, gguf)

    ## Response (ModelBriefReadSchema)
    `POST /api/v1/models`와 동일한 응답 형식
    - **id** (int): 모델 고유 ID
    - **name** (str): 모델 이름
    - **description** (str, optional): 모델 설명
    - **repo_id** (str, optional): 모델 저장소 ID
    - **provider_info** / **type_info** / **format_info**: 각 메타 정보 (id/name/description)
    - **parent_model_id** (int, optional): 부모 모델 ID
    - **task** / **parameter** / **sample_code** (optional)
    - **registry** (ModelRegistryReadSchema): 모델 레지스트리 정보
    - **created_at** / **updated_at** (datetime)

    게이트웨이는 MLOps 응답을 그대로 전달하며, 추가로 게이트웨이 DB에
    사용자-모델 매핑을 생성합니다 (admin이 호출하면 카탈로그 모델로 분류).

    ## Notes
    - 각 모델의 provider_id, type_id, format_id는 MLOps DB에서 이름으로 자동 조회됩니다
    - `bge-m3`는 Ollama Embedding 모델로, PVC 다운로드 및 자동 배포가 수행됩니다
    - `yolox_s`, `yolox_m`은 GitHub에서 가중치 파일(.pth)을 자동 다운로드하여 MLflow에 등록합니다
    - MLOps에는 등록되었으나 게이트웨이 DB 매핑 저장에 실패하는 경우 경고만 기록하고 MLOps 응답은 그대로 반환됩니다

    ## Errors
    - **400**: 모델 키에 해당하는 provider/type/format을 MLOps DB에서 찾을 수 없음
    - **401**: 인증되지 않은 사용자
    - **422**: 유효하지 않은 model_key
    - **500**: 모델 등록 중 서버 내부 오류 (가중치 다운로드 실패 포함)
    """
    try:
        user_info = {
            'member_id': current_user.member_id,
            'role': current_user.role,
            'name': current_user.name,
        }

        created = await model_service.auto_generate_model(
            model_key=model_key, user_info=user_info
        )

        # 게이트웨이 DB에 사용자-모델 매핑 저장
        try:
            is_catalog = current_user.role.lower() == 'admin'
            model_crud.create_model_mapping(
                db=db,
                surro_model_id=created.get('id'),
                member_id=current_user.member_id,
                model_name=created.get('name', model_key),
                is_catalog=is_catalog,
            )
            logger.info(
                f"Auto-generated model mapping saved: surro_id={created.get('id')}, "
                f"member_id={current_user.member_id}, is_catalog={is_catalog}"
            )
        except Exception as mapping_error:
            logger.warning(
                f"Model {created.get('id')} auto-generated in MLOps but mapping failed: {mapping_error}"
            )

        return created

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error auto-generating model ({model_key}) for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to auto-generate model: {str(e)}"
        )


@router.put("/base-deployments/{model_id}/status")
async def update_model_base_deployment_status(
        model_id: int = Path(..., description="모델 ID"),
        service_name: str = Form(...),
        service_hostname: str = Form(...),
        deployment_status: str = Form(..., alias="status"),
        internal_url: Optional[str] = Form(None),
        error_message: Optional[str] = Form(None),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 기본 배포 상태 업데이트 (백엔드 서버 내부 전용 API)

    **⚠️ 경고: 이 API는 백엔드 서버 내부에서만 사용하는 내부 API입니다.**
    **프론트엔드나 외부 클라이언트에서 직접 호출해서는 안 됩니다.**

    Kubeflow 파이프라인 컴포넌트에서 배포 상태를 업데이트하기 위한 엔드포인트입니다.
    파이프라인 컴포넌트 내부에서 인증 토큰을 발급받아 사용합니다.
    게이트웨이는 호환성 유지를 위해 MLOps로 그대로 프록시합니다.

    ## 사용 목적
    - Kubeflow 파이프라인 컴포넌트에서 모델 배포 상태를 DB에 업데이트하기 위해 사용
    - 백엔드 서버 내부 시스템 간 통신용으로만 사용

    ## Path Parameters
    - **model_id** (int): 모델 ID

    ## Request Body (Form Data)
    - **service_name** (str, required): 서비스 이름
    - **service_hostname** (str, required): 서비스 호스트명
    - **status** (str, required): 배포 상태 ("deployed", "deploying", "failed")
    - **internal_url** (str, optional): 내부 접근 URL
    - **error_message** (str, optional): 오류 메시지 (실패 시)

    ## Response
    - **success** (bool): 업데이트 성공 여부
    - **message** (str): 결과 메시지

    ## Notes
    - **내부 API**: 백엔드 서버 내부에서만 사용하는 API입니다
    - **호출 주체**: Kubeflow 파이프라인 컴포넌트에서만 호출됩니다
    - **인증**: 인증 토큰이 필요하며, 파이프라인 컴포넌트에서 자동으로 발급받아 사용합니다
    - **프론트엔드 사용 금지**: 프론트엔드나 외부 클라이언트에서 직접 호출하지 마세요

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 배포 정보를 찾을 수 없음
    - **500**: 서버 내부 오류
    """
    try:
        user_info = {
            'member_id': current_user.member_id,
            'role': current_user.role,
            'name': current_user.name,
        }
        return await model_service.update_base_deployment_status(
            model_id=model_id,
            service_name=service_name,
            service_hostname=service_hostname,
            deployment_status=deployment_status,
            internal_url=internal_url,
            error_message=error_message,
            user_info=user_info,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating base deployment status for model {model_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update base deployment status: {str(e)}"
        )


@router.get("/{model_id}", response_model=ModelResponse)
async def get_model(
    model_id: int = Path(..., description="조회할 모델 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 상세정보 조회

    특정 모델의 상세 정보를 조회합니다.
    제공자, 타입, 포맷 정보와 부모/자식 모델 관계를 포함하여 반환합니다.

    게이트웨이 권한 검사: 본인 소유 모델 또는 카탈로그 모델만 조회 가능.
    접근 권한이 없는 경우 404로 응답합니다.

    ## Path Parameters
    - **model_id** (int): 조회할 모델 ID

    ## Response (ModelReadSchema)
    - **id** (int): 모델 고유 ID
    - **name** (str): 모델 이름
    - **description** (str, optional): 모델 설명
    - **repo_id** (str, optional): 모델 저장소 ID
    - **provider_info** (ModelProviderReadSchema): 모델 제공자 정보
        - id (int): 제공자 ID
        - name (str): 제공자 이름
        - description (str): 제공자 설명
    - **type_info** (ModelTypeReadSchema): 모델 타입 정보
        - id / name / description
    - **format_info** (ModelFormatReadSchema): 모델 포맷 정보
        - id / name / description
    - **parent_model_id** (int, optional): 부모 모델 ID
        - 파인튜닝된 모델인 경우 원본 모델 ID
    - **task** (str, optional): 모델 태스크
    - **parameter** (str, optional): 모델 파라미터
    - **sample_code** (str, optional): 샘플 코드
    - **registry** (ModelRegistryReadSchema): 모델 레지스트리 정보
        - id (int): 레지스트리 ID
        - artifact_path (str): 아티팩트 경로
        - uri (str): 모델 URI
        - run_id (str, optional): MLflow 실행 ID
        - reference_model_id (int): 참조 모델 ID
        - created_at / updated_at (datetime)
    - **parent_model** (ModelReadParentSchema, optional): 부모 모델 정보
        - id / name / description
        - parent_model (ModelReadParentSchema, optional): 상위 부모 모델 (재귀적)
    - **child_models** (List[ModelReadChildSchema], optional): 자식 모델 목록
        - id / name / description
        - child_models (List[ModelReadChildSchema], optional): 하위 자식 모델 (재귀적)
    - **created_at** (datetime): 모델 생성 시각
    - **updated_at** (datetime): 모델 수정 시각

    ## Notes
    - 모델의 모든 관련 정보(제공자, 타입, 포맷, 레지스트리)를 포함하여 반환
    - 부모/자식 모델 관계는 재귀적으로 조회
    - 게이트웨이는 접근 권한 체크 후 MLOps 응답을 그대로 전달

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 모델을 찾을 수 없거나 접근 권한이 없음
        - 본인 소유 모델도 아니고 카탈로그 모델도 아닌 경우
    - **500**: 서버 내부 오류
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

@router.delete("/{model_id}")
async def delete_model(
    model_id: int = Path(..., description="삭제할 모델 ID"),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    모델 삭제

    모델을 삭제합니다. 참조 관계를 확인하여 안전하게 삭제합니다.
    다른 엔티티에서 참조되고 있는 경우 삭제할 수 없습니다.

    게이트웨이 권한 검사: 본인 소유 모델만 삭제 가능 (카탈로그 모델 삭제 불가).

    ## Path Parameters
    - **model_id** (int): 삭제할 모델 ID

    ## Response
    - **message** (str): 삭제 결과 메시지 (예: "Model {model_id} deleted successfully")

    MLOps 원본은 `{success: bool, message: str}`을 반환하지만, 게이트웨이는
    MLOps 삭제 성공 후 게이트웨이 DB 매핑도 함께 삭제하고 `message`만 포함하여 응답합니다.

    ## Notes
    - 모델이 다음 엔티티에서 참조되고 있으면 삭제할 수 없습니다:
        - Experiment (실험)
        - WorkflowComponent (워크플로우 컴포넌트)
        - 다른 모델의 parent_model (자식 모델)
    - 참조 관계가 있는 경우 MLOps에서 400 에러를 반환
    - 삭제 성공 시 게이트웨이 DB의 사용자-모델 매핑도 제거됨

    ## Errors
    - **400**: 모델이 다른 엔티티에서 참조되고 있어 삭제할 수 없음 (MLOps 원본 에러 전달)
    - **401**: 인증되지 않은 사용자
    - **404**: 모델을 찾을 수 없거나 접근 권한이 없음 (본인 소유가 아님)
    - **500**: 모델 삭제 중 서버 내부 오류
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
