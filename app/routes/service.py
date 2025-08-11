from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional, List
from app.database import get_db
from app.crud import service_crud
from app.schemas import (
    ServiceCreate, ServiceUpdate, ServiceResponse, ServiceListResponse
)
from app.auth import (
    get_current_user,
    get_current_admin_user,
    check_member_access,
    verify_member_access
)

router = APIRouter(prefix="/services", tags=["services"])


@router.post("/", response_model=ServiceResponse)
def create_service(
        service: ServiceCreate,
        db: Session = Depends(get_db),
        _: None = Depends(get_current_admin_user)
):
    """서비스 생성"""
    return service_crud.create_service(db=db, service=service)


@router.get("/", response_model=ServiceListResponse)
def get_services(
        page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
        size: int = Query(20, ge=1, le=100, description="페이지 크기"),
        search: Optional[str] = Query(None, description="검색어 (이름)"),
        db: Session = Depends(get_db),
        _: None = Depends(get_current_user)
):
    """서비스 목록 조회 (검색 포함)"""
    skip = (page - 1) * size
    services, total = service_crud.get_services(db=db, skip=skip, limit=size, search=search)

    return ServiceListResponse(
        services=services,
        total=total,
        page=page,
        size=size
    )


@router.get("/{service_id}", response_model=ServiceResponse)
def get_service(
        service_id: int,
        db: Session = Depends(get_db),
        _: None = Depends(get_current_user)
):
    """서비스 기본 메타데이터 조회"""
    service = service_crud.get_service(db=db, service_id=service_id)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    return service

@router.put("/{service_id}", response_model=ServiceResponse)
def update_service(
        service_id: int,
        service_update: ServiceUpdate,
        db: Session = Depends(get_db),
        _: None = Depends(get_current_user)
):
    """서비스 편집"""
    service = service_crud.update_service(db=db, service_id=service_id, service_update=service_update)
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")
    return service


@router.delete("/{service_id}")
def delete_service(
        service_id: int,
        db: Session = Depends(get_db),
        _: None = Depends(get_current_user)
):
    """서비스 삭제 (소프트 삭제)"""
    success = service_crud.delete_service(db=db, service_id=service_id)
    if not success:
        raise HTTPException(status_code=404, detail="Service not found")
    return {"message": "Service deleted successfully"}


# # 워크플로우 관련 엔드포인트
# @router.get("/{service_id}/workflows", response_model=List[ServiceWorkflowResponse])
# def get_service_workflows(
#         service_id: int,
#         db: Session = Depends(get_db)
# ):
#     """서비스 워크플로우 조회"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.get_service_workflows(db=db, service_id=service_id)
#
#
# @router.post("/{service_id}/workflows")
# def add_workflow_to_service(
#         service_id: int,
#         workflow_id: int,
#         workflow_name: Optional[str] = None,
#         workflow_description: Optional[str] = None,
#         db: Session = Depends(get_db)
# ):
#     """서비스에 워크플로우 추가"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.add_workflow_to_service(
#         db=db,
#         service_id=service_id,
#         workflow_id=workflow_id,
#         workflow_name=workflow_name,
#         workflow_description=workflow_description
#     )
#
#
# # 데이터셋 관련 엔드포인트
# @router.get("/{service_id}/datasets", response_model=List[ServiceDatasetResponse])
# def get_service_datasets(
#         service_id: int,
#         db: Session = Depends(get_db)
# ):
#     """서비스 데이터셋 조회"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.get_service_datasets(db=db, service_id=service_id)
#
#
# @router.post("/{service_id}/datasets")
# def add_dataset_to_service(
#         service_id: int,
#         dataset_id: int,
#         dataset_name: Optional[str] = None,
#         dataset_description: Optional[str] = None,
#         dataset_type: Optional[str] = None,
#         db: Session = Depends(get_db)
# ):
#     """서비스에 데이터셋 추가"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.add_dataset_to_service(
#         db=db,
#         service_id=service_id,
#         dataset_id=dataset_id,
#         dataset_name=dataset_name,
#         dataset_description=dataset_description,
#         dataset_type=dataset_type
#     )
#
#
# # 모델 관련 엔드포인트
# @router.get("/{service_id}/models", response_model=List[ServiceModelResponse])
# def get_service_models(
#         service_id: int,
#         db: Session = Depends(get_db)
# ):
#     """서비스 모델 조회"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.get_service_models(db=db, service_id=service_id)
#
#
# @router.post("/{service_id}/models")
# def add_model_to_service(
#         service_id: int,
#         model_id: int,
#         model_name: Optional[str] = None,
#         model_description: Optional[str] = None,
#         model_type: Optional[str] = None,
#         model_version: Optional[str] = None,
#         db: Session = Depends(get_db)
# ):
#     """서비스에 모델 추가"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.add_model_to_service(
#         db=db,
#         service_id=service_id,
#         model_id=model_id,
#         model_name=model_name,
#         model_description=model_description,
#         model_type=model_type,
#         model_version=model_version
#     )
#
#
# # 프롬프트 관련 엔드포인트
# @router.get("/{service_id}/prompts", response_model=List[ServicePromptResponse])
# def get_service_prompts(
#         service_id: int,
#         db: Session = Depends(get_db)
# ):
#     """서비스 프롬프트 조회"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.get_service_prompts(db=db, service_id=service_id)
#
#
# @router.post("/{service_id}/prompts")
# def add_prompt_to_service(
#         service_id: int,
#         prompt_id: int,
#         prompt_name: Optional[str] = None,
#         prompt_content: Optional[str] = None,
#         prompt_type: Optional[str] = None,
#         db: Session = Depends(get_db)
# ):
#     """서비스에 프롬프트 추가"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.add_prompt_to_service(
#         db=db,
#         service_id=service_id,
#         prompt_id=prompt_id,
#         prompt_name=prompt_name,
#         prompt_content=prompt_content,
#         prompt_type=prompt_type
#     )
#
#
# # 모니터링 관련 엔드포인트
# @router.get("/{service_id}/monitoring", response_model=List[ServiceMonitoringResponse])
# def get_service_monitoring(
#         service_id: int,
#         db: Session = Depends(get_db)
# ):
#     """서비스 모니터링 조회"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.get_service_monitoring(db=db, service_id=service_id)
#
#
# @router.post("/{service_id}/monitoring")
# def add_monitoring_to_service(
#         service_id: int,
#         monitoring_id: int,
#         monitoring_name: Optional[str] = None,
#         monitoring_type: Optional[str] = None,
#         monitoring_config: Optional[str] = None,
#         db: Session = Depends(get_db)
# ):
#     """서비스에 모니터링 추가"""
#     service = service_crud.get_service(db=db, service_id=service_id)
#     if not service:
#         raise HTTPException(status_code=404, detail="Service not found")
#
#     return service_crud.add_monitoring_to_service(
#         db=db,
#         service_id=service_id,
#         monitoring_id=monitoring_id,
#         monitoring_name=monitoring_name,
#         monitoring_type=monitoring_type,
#         monitoring_config=monitoring_config
#     )