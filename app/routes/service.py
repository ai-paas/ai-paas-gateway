from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.cruds.service import service_crud
from app.auth import get_current_user, get_current_admin_user
from app.schemas.service import (
    ServiceCreate,
    ServiceUpdate,
    ServiceResponse,
    ServiceDetailResponse,
    ServiceListResponse
)
from app.services.service_service import service_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/services", tags=["services"])


@router.post("/", response_model=ServiceResponse)
async def create_service(
        service: ServiceCreate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_admin_user)
):
    """서비스 생성"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    # 외부 API 호출
    external_service = await service_service.create_service(
        name=service.name,
        description=service.description,
        tags=service.tags,
        user_info=user_info
    )

    # 우리 DB에 저장 (Model과 동일한 패턴)
    try:
        db_service = service_crud.create_service(
            db=db,
            service=service,
            created_by=current_user.member_id,
            surro_service_id=external_service.id
        )
        logger.info(
            f"Created service mapping: surro_id={external_service.id}, "
            f"member_id={current_user.member_id}"
        )
    except Exception as mapping_error:
        logger.error(f"Failed to create service mapping: {str(mapping_error)}")
        # 매핑 저장에 실패해도 외부 API에는 이미 생성됨
        logger.warning(f"Service {external_service.id} created in external API but mapping failed")
        # 여기서 어떻게 할지 결정 - 에러를 던질지, 부분 성공으로 처리할지
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Service created in external API but failed to save mapping: {str(mapping_error)}"
        )

    return db_service


@router.get("/", response_model=ServiceListResponse)
async def get_services(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지당 항목 수"),
        search: Optional[str] = Query(None, description="검색어 (이름, 설명)"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """서비스 목록 조회 (우리 DB 기준)

    - **page**: 페이지 번호
    - **size**: 페이지당 항목 수
    - **search**: 검색어 (선택)
    """
    skip = (page - 1) * size
    services, total = service_crud.get_services(
        db=db,
        skip=skip,
        limit=size,
        search=search
    )

    return ServiceListResponse(
        data=services,
        total=total,
        page=page,
        size=size
    )


@router.get("/{surro_service_id}", response_model=ServiceDetailResponse)
async def get_service(
        surro_service_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """서비스 상세 정보 조회"""
    # 1. 내부 DB 조회
    db_service = service_crud.get_service_by_surro_id(db=db, surro_service_id=surro_service_id)
    if not db_service:
        raise HTTPException(status_code=404, detail="Service not found")

    # 2. 외부 API 조회
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    external_data = None
    try:
        logger.info(f"Fetching external service data for UUID: {surro_service_id}")
        external_data = await service_service.get_service(
            surro_service_id,
            user_info
        )
        logger.info(f"External data fetched successfully: {external_data is not None}")
    except Exception as e:
        logger.error(f"Failed to fetch external service data for {surro_service_id}: {str(e)}", exc_info=True)

    # 3. 최종 응답 = 내부 DB + 필요한 외부 API 데이터 병합
    response = ServiceDetailResponse(
        id=db_service.id,
        name=db_service.name,
        description=db_service.description,
        tags=db_service.tags,
        created_at=db_service.created_at,
        updated_at=db_service.updated_at,
        created_by=db_service.created_by,
        surro_service_id=db_service.surro_service_id,

        # 외부 API 데이터 병합
        workflow_count=getattr(external_data, "workflow_count", 0),
        workflows=getattr(external_data, "workflows", []),
        monitoring_data=getattr(external_data, "monitoring_data", None)
    )

    return response



@router.put("/{surro_service_id}", response_model=ServiceResponse)
async def update_service(
        surro_service_id: str,  # int -> str (UUID)
        service_update: ServiceUpdate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """서비스 정보 수정

    - **surro_service_id**: 외부 API의 서비스 UUID
    """
    # UUID로 우리 DB에서 기존 서비스 조회
    existing_service = service_crud.get_service_by_surro_id(db=db, surro_service_id=surro_service_id)
    if not existing_service:
        raise HTTPException(status_code=404, detail="Service not found")

    # 권한 확인
    if current_user.role != "admin" and existing_service.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 업데이트
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        await service_service.update_service(
            service_id=surro_service_id,  # UUID 사용
            name=service_update.name,
            description=service_update.description,
            tags=service_update.tags,
            user_info=user_info
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update external service: {str(e)}"
        )

    # 우리 DB 업데이트
    updated_service = service_crud.update_service_by_surro_id(
        db=db,
        surro_service_id=surro_service_id,
        service_update=service_update
    )

    return updated_service


@router.delete("/{surro_service_id}", status_code=200)
async def delete_service(
        surro_service_id: str,  # int -> str (UUID)
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """서비스 삭제

    - **surro_service_id**: 외부 API의 서비스 UUID
    """
    # UUID로 우리 DB에서 기존 서비스 조회
    existing_service = service_crud.get_service_by_surro_id(db=db, surro_service_id=surro_service_id)
    if not existing_service:
        raise HTTPException(status_code=404, detail="Service not found")

    # 권한 확인
    if current_user.role != "admin" and existing_service.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 삭제
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        await service_service.delete_service(
            surro_service_id,  # UUID 사용
            user_info
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete external service: {str(e)}"
        )

    # 우리 DB 삭제
    success = service_crud.delete_service_by_surro_id(db=db, surro_service_id=surro_service_id)
    if not success:
        raise HTTPException(status_code=404, detail="Service not found")

    return {"message": "Service deleted successfully"}