from fastapi import APIRouter, Depends, HTTPException, status, Query, Path
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
import logging

from app.database import get_db
from app.auth import get_current_user, verify_member_access
from app.crud import workflow_crud
from app.schemas.workflow import (
    WorkflowCreate, WorkflowUpdate, WorkflowResponse,
    WorkflowDetailResponse, WorkflowListResponse
)
from app.services.workflow_service import external_workflow_service
from app.models import Member

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["Workflows"])


@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
        workflow: WorkflowCreate,
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    워크플로우 생성
    1. S업체 API 호출하여 외부 워크플로우 생성
    2. 우리 DB에 워크플로우 정보 저장
    """
    try:
        logger.info(f"[API_CALL] POST /workflows/ - Creating workflow for user {current_user.member_id}")

        # 사용자 정보 준비
        user_info = {
            'member_id': current_user.member_id,
            'name': current_user.name,
            'role': current_user.role,
            'email': current_user.email
        }

        # 1단계: S업체 API 호출하여 외부 워크플로우 생성
        logger.info(f"[EXTERNAL_CALL] Starting external workflow creation")
        logger.info(f"[EXTERNAL_CALL] User info: {user_info}")
        logger.info(f"[EXTERNAL_CALL] Parameters: {workflow.parameters}")

        external_response = await external_workflow_service.create_workflow(
            parameters=workflow.parameters,
            user_info=user_info
        )

        logger.info(f"[EXTERNAL_CALL] External workflow creation completed: {external_response.workflow_id}")

        logger.info(f"External workflow created: {external_response.workflow_id}")

        # 2단계: 우리 DB에 워크플로우 정보 저장
        db_workflow = workflow_crud.create_workflow(
            db=db,
            workflow=workflow,
            created_by=current_user.member_id,
            workflow_id=external_response.workflow_id
        )

        logger.info(f"Internal workflow created: ID {db_workflow.id}")

        return db_workflow

    except HTTPException:
        # HTTP 예외는 그대로 전파
        raise
    except Exception as e:
        logger.error(f"Error creating workflow: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create workflow: {str(e)}"
        )


@router.get("/", response_model=WorkflowListResponse)
async def get_workflows(
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user),
        skip: int = Query(0, ge=0, description="페이지네이션 오프셋"),
        limit: int = Query(100, ge=1, le=1000, description="페이지네이션 리미트"),
        search: Optional[str] = Query(None, description="검색어 (이름, 설명)"),
        creator_id: Optional[str] = Query(None, description="생성자 ID 필터 (관리자만)")
):
    """워크플로우 목록 조회"""

    logger.info(f"[API_CALL] GET /workflows/ - Getting workflows for user {current_user.member_id}")

    # 관리자가 아닐 경우 자신의 워크플로우만 조회
    if current_user.role != "admin":
        creator_id = current_user.member_id

    workflows, total = workflow_crud.get_workflows(
        db=db,
        skip=skip,
        limit=limit,
        search=search,
        creator_id=creator_id,
    )

    page = (skip // limit) + 1 if limit > 0 else 1

    return WorkflowListResponse(
        workflows=workflows,
        total=total,
        page=page,
        size=limit
    )


@router.get("/{workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow(
        workflow_id: int = Path(..., gt=0),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """워크플로우 상세 조회"""

    logger.info(f"[API_CALL] GET /workflows/{workflow_id} - Getting workflow detail for user {current_user.member_id}")

    workflow = workflow_crud.get_workflow_with_creator(db, workflow_id)

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )

    # 권한 확인: 본인의 워크플로우이거나 관리자인 경우만 조회 가능
    if workflow.created_by != current_user.member_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    return workflow


@router.put("/{workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
        workflow_id: int = Path(..., gt=0),
        workflow_update: WorkflowUpdate = ...,
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    워크플로우 업데이트
    1. 우리 DB의 워크플로우 업데이트
    2. S업체 API 호출하여 외부 워크플로우 업데이트 (파라미터 변경이 있는 경우)
    """

    logger.info(f"[API_CALL] PUT /workflows/{workflow_id} - Updating workflow for user {current_user.member_id}")

    # 기존 워크플로우 조회
    existing_workflow = workflow_crud.get_workflow(db, workflow_id)

    if not existing_workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )

    # 권한 확인: 본인의 워크플로우이거나 관리자인 경우만 수정 가능
    if existing_workflow.created_by != current_user.member_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    try:
        # 파라미터 변경이 있는 경우 외부 API 호출
        if workflow_update.parameters is not None:
            user_info = {
                'member_id': current_user.member_id,
                'name': current_user.name,
                'role': current_user.role
            }

            logger.info(f"[EXTERNAL_CALL] Starting external workflow update")
            logger.info(f"[EXTERNAL_CALL] External workflow ID: {existing_workflow.workflow_id}")
            logger.info(f"[EXTERNAL_CALL] User info: {user_info}")
            logger.info(f"[EXTERNAL_CALL] Update parameters: {workflow_update.parameters}")

            success = await external_workflow_service.update_workflow(
                external_workflow_id=existing_workflow.workflow_id,
                parameters=workflow_update.parameters,
                user_info=user_info
            )

            logger.info(f"[EXTERNAL_CALL] External workflow update result: {success}")
            if not success:
                logger.warning(f"Failed to update external workflow {existing_workflow.workflow_id}")

        # 우리 DB 업데이트
        updated_workflow = workflow_crud.update_workflow(db, workflow_id, workflow_update)

        if not updated_workflow:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update workflow"
            )

        return updated_workflow

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update workflow: {str(e)}"
        )


@router.delete("/{workflow_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow(
        workflow_id: int = Path(..., gt=0),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """
    워크플로우 삭제
    1. 우리 DB에서 워크플로우 소프트 삭제
    2. S업체 API 호출하여 외부 워크플로우 삭제
    """

    logger.info(f"[API_CALL] DELETE /workflows/{workflow_id} - Deleting workflow for user {current_user.member_id}")

    # 기존 워크플로우 조회
    existing_workflow = workflow_crud.get_workflow(db, workflow_id)

    if not existing_workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )

    # 권한 확인: 본인의 워크플로우이거나 관리자인 경우만 삭제 가능
    if existing_workflow.created_by != current_user.member_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    try:
        # 외부 워크플로우 삭제 시도
        user_info = {
            'member_id': current_user.member_id,
            'name': current_user.name,
            'role': current_user.role
        }

        logger.info(f"[EXTERNAL_CALL] Starting external workflow deletion")
        logger.info(f"[EXTERNAL_CALL] External workflow ID: {existing_workflow.workflow_id}")
        logger.info(f"[EXTERNAL_CALL] User info: {user_info}")

        success = await external_workflow_service.delete_workflow(
            external_workflow_id=existing_workflow.workflow_id,
            user_info=user_info
        )

        logger.info(f"[EXTERNAL_CALL] External workflow deletion result: {success}")
        if not success:
            logger.warning(f"Failed to delete external workflow {existing_workflow.workflow_id}")

        # 우리 DB에서 소프트 삭제 (status를 deleted로 변경)
        deleted = workflow_crud.delete_workflow(db, workflow_id)

        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete workflow"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting workflow {workflow_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete workflow: {str(e)}"
        )


@router.get("/my/workflows", response_model=WorkflowListResponse)
async def get_my_workflows(
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user),
        skip: int = Query(0, ge=0, description="페이지네이션 오프셋"),
        limit: int = Query(100, ge=1, le=1000, description="페이지네이션 리미트")
):
    """현재 사용자의 워크플로우 목록 조회"""

    logger.info(f"[API_CALL] GET /workflows/my/workflows - Getting my workflows for user {current_user.member_id}")

    workflows, total = workflow_crud.get_workflows_by_member(
        db=db,
        member_id=current_user.member_id,
        skip=skip,
        limit=limit
    )

    page = (skip // limit) + 1 if limit > 0 else 1

    return WorkflowListResponse(
        workflows=workflows,
        total=total,
        page=page,
        size=limit
    )


@router.get("/{workflow_id}/external-status")
async def get_workflow_external_status(
        workflow_id: int = Path(..., gt=0),
        db: Session = Depends(get_db),
        current_user: Member = Depends(get_current_user)
):
    """외부 워크플로우 상태 조회"""

    logger.info(
        f"[API_CALL] GET /workflows/{workflow_id}/external-status - Getting external status for user {current_user.member_id}")

    workflow = workflow_crud.get_workflow(db, workflow_id)

    if not workflow:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow not found"
        )

    # 권한 확인
    if workflow.created_by != current_user.member_id and current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied"
        )

    try:
        logger.info(f"[EXTERNAL_CALL] Getting external workflow status")
        logger.info(f"[EXTERNAL_CALL] External workflow ID: {workflow.workflow_id}")

        external_info = await external_workflow_service.get_workflow(
            external_workflow_id=workflow.workflow_id
        )

        logger.info(f"[EXTERNAL_CALL] External workflow get result: {'Found' if external_info else 'Not found'}")

        if external_info is None:
            return {
                "workflow_id": workflow.workflow_id,
                "status": "not_found",
                "message": "External workflow not found"
            }

        return {
            "workflow_id": workflow.workflow_id,
            "external_data": external_info
        }

    except Exception as e:
        logger.error(f"Error getting external workflow status: {str(e)}")
        return {
            "workflow_id": workflow.workflow_id,
            "status": "error",
            "message": str(e)
        }