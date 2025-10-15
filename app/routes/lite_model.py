from fastapi import APIRouter, Depends, HTTPException, status, Query, Path, Body, Request, UploadFile, File, Form
from typing import Optional, Any, Dict
import logging
import json

from app.auth import get_current_user
from app.schemas.lite_model import LiteModelResponse, LiteModelDataResponse, OptimizeRequest, TaskUpdate
from app.services.lite_model_service import lite_model_service
from app.models import Member

logger = logging.getLogger(__name__)

router_model = APIRouter(prefix="/models", tags=["Lite Model - Models"])
router_task = APIRouter(prefix="/tasks", tags=["Lite Model - Tasks"])
router_optimize = APIRouter(prefix="/optimize", tags=["Lite Model - Optimize"])
router_info = APIRouter(prefix="/checked", tags=["Lite Model - Info"])

def _create_user_info_dict(user: Member) -> Dict[str, str]:
    """Member 객체에서 user_info 딕셔너리 생성"""
    return {
        'member_id': user.member_id,
        'role': user.role,
        'name': user.name
    }

# 모델 조회 API
@router_info.get("/model", response_model=LiteModelDataResponse)
async def get_models(
        current_user: Member = Depends(get_current_user),
        page: Optional[int] = Query(1, alias="page", description="page_num"),
        size: Optional[int] = Query(10, alias="size", description="page_size"),
        name: Optional[str] = Query("", alias="name", description="name"),
        optimizer_id: Optional[int] = Query("", alias="optimizer_id", description="optimizer_id"),
):
    """
    모델 전체 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await lite_model_service.get_models(
            user_info=user_info,
            page_num=page,
            page_size=size,
            name=name,
            optimizer_id=optimizer_id
        )

        # 목록 조회는 data로 래핑하여 반환
        return LiteModelDataResponse(data=response["data"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting models for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve models"
        )

# 모델 상세 조회 API
@router_info.get("/model/{model_id}", response_model=LiteModelResponse)
async def get_model(
        current_user: Member = Depends(get_current_user),
        model_id: int = Path(..., alias="model_id", description="model_id"),
):
    """
    모델 상세 내용을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await lite_model_service.get_model(
            user_info=user_info,
            model_id=model_id
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting model for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve model"
        )

# Optimizer 조회 API
@router_info.get("/optimizer", response_model=LiteModelDataResponse)
async def get_models(
        current_user: Member = Depends(get_current_user),
        page: Optional[int] = Query(1, alias="page", description="page_num"),
        size: Optional[int] = Query(10, alias="size", description="page_size"),
        name: Optional[str] = Query("", alias="name", description="name"),
        model_id: Optional[int] = Query("", alias="model_id", description="model_id"),
):
    """
    Optimizer 전체 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await lite_model_service.get_optimizers(
            user_info=user_info,
            page_num=page,
            page_size=size,
            name=name,
            model_id=model_id
        )

        # 목록 조회는 data로 래핑하여 반환
        return LiteModelDataResponse(data=response["data"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting optimizers for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve optimizers"
        )

# Optimizer 상세 조회 API
@router_info.get("/optimizer/{optimizer_id}", response_model=LiteModelResponse)
async def get_models(
        current_user: Member = Depends(get_current_user),
        optimizer_id: Optional[int] = Path(..., alias="optimizer_id", description="optimizer_id"),
):
    """
    Optimizer 전체 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await lite_model_service.get_optimizer(
            user_info=user_info,
            optimizer_id=optimizer_id
        )

        # 목록 조회는 data로 래핑하여 반환
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting optimize for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve optimizer"
        )

# Optimize 실행 API (POST)
@router_optimize.post("/optimize/{optimizer_id}", response_model=LiteModelResponse)
async def execute_optimize(
        current_user: Member = Depends(get_current_user),
        optimizer_id: int = Path(..., description="optimizer_id"),
        request_data: OptimizeRequest = Body(..., description="Optimize request body")
):
    """
    Optimizer를 실행합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await lite_model_service.execute_optimize(
            user_info=user_info,
            optimizer_id=optimizer_id,
            optimize_data=request_data.dict(exclude_none=True)
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing optimize for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute optimize"
        )

# Task 조회 API
@router_task.get("/tasks", response_model=LiteModelDataResponse)
async def get_tasks(
        current_user: Member = Depends(get_current_user),
        model_name_query: Optional[str] = Query("", alias="model_name_query", description="model_name_query"),
        optimizer_name_query: Optional[str] = Query("", alias="optimizer_name_query", description="optimizer_name_query"),
        task_status: Optional[str] = Query("", alias="task_status", description="task_status"),
        page: Optional[int] = Query(1, alias="page", description="page_num"),
        size: Optional[int] = Query(10, alias="size", description="page_size")
):
    """
    Task 전체 목록을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await lite_model_service.get_tasks(
            user_info=user_info,
            page_num=page,
            page_size=size,
            model_name_query=model_name_query,
            optimizer_name_query=optimizer_name_query,
            task_status=task_status
        )

        # 목록 조회는 data로 래핑하여 반환
        return LiteModelDataResponse(data=response["data"])

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting tasks for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve tasks"
        )

# Task 상세 조회 API
@router_task.get("/tasks/{task_id}", response_model=LiteModelResponse)
async def get_task(
        current_user: Member = Depends(get_current_user),
        task_id: Optional[str] = Path(..., alias="task_id", description="task_id"),
):
    """
    Task 상세 내용을 조회합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await lite_model_service.get_task(
            user_info=user_info,
            task_id=task_id
        )

        # 목록 조회는 data로 래핑하여 반환
        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve task"
        )

# Task 업데이트 API
@router_task.patch("/tasks/{task_id}", response_model=LiteModelResponse)
async def patch_task(
        current_user: Member = Depends(get_current_user),
        task_id: str = Path(..., description="task_id"),
        request_data: TaskUpdate = Body(..., description="Task update body")
):
    """
    Task 상태를 업데이트합니다.
    """
    try:
        user_info = _create_user_info_dict(current_user)

        response = await lite_model_service.patch_task(
            user_info=user_info,
            task_id=task_id,
            task_data=request_data.dict(exclude_none=True)
        )

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating task for {current_user.member_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update task"
        )