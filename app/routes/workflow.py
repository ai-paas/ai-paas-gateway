from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.cruds.workflow import workflow_crud
from app.auth import get_current_user
from app.schemas.workflow import (
    WorkflowCreateRequest,
    WorkflowUpdateRequest,
    WorkflowResponse,
    WorkflowDetailResponse,
    WorkflowListResponse,
    WorkflowExecuteRequest,
    WorkflowExecuteResponse,
    WorkflowTestRAGRequest,
    WorkflowTestResponse
)
from app.services.workflow_service import workflow_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])

# ===== Component Types =====

@router.get("/component-types")
async def get_component_types(
        current_user=Depends(get_current_user)
):

    """
    사용 가능한 컴포넌트 타입 조회

    워크플로우 구성에 사용할 수 있는 컴포넌트 타입 목록을 조회합니다. 각 타입별로 고유한 component_id와 설명을 제공하여 워크플로우 정의 시 활용할 수 있습니다.

    ## Usage Example
    1. 이 API로 사용 가능한 컴포넌트 타입 확인
    2. workflow_definition 작성 시 component_id 사용
    3. 각 컴포넌트 타입에 맞는 설정 적용

    ## Notes
    - 고정된 타입 목록 반환 (동적 변경 없음)
    - 워크플로우는 반드시 START로 시작하고 END로 종료
    - MODEL 타입은 model_id 필수, prompt_id 선택
    - KNOWLEDGE_BASE 타입은 knowledge_base_id 필수
    """
    """사용 가능한 컴포넌트 타입 조회"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    component_types = await workflow_service.get_component_types(user_info)

    # data로 래핑
    return {
        "data": component_types
    }

# ===== Workflow CRUD =====

@router.post("/", response_model=WorkflowResponse, status_code=status.HTTP_201_CREATED)
async def create_workflow(
        workflow_create: WorkflowCreateRequest,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우 생성"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    # 외부 API 호출
    workflow_definition_dict = None
    if workflow_create.workflow_definition:
        workflow_definition_dict = workflow_create.workflow_definition.dict()

    external_workflow = await workflow_service.create_workflow(
        name=workflow_create.name,
        description=workflow_create.description,
        category=workflow_create.category,
        service_id=workflow_create.service_id,
        workflow_definition=workflow_definition_dict,
        user_info=user_info
    )

    # 우리 DB에 저장
    try:
        db_workflow = workflow_crud.create_workflow(
            db=db,
            name=workflow_create.name,
            description=workflow_create.description,
            created_by=current_user.member_id,
            surro_workflow_id=external_workflow.id
        )
        logger.info(
            f"Created workflow: surro_id={external_workflow.id}, "
            f"member_id={current_user.member_id}"
        )
    except Exception as mapping_error:
        logger.error(f"Failed to create workflow: {str(mapping_error)}")
        logger.warning(
            f"Workflow {external_workflow.id} created in external API but DB save failed"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Workflow created in external API but failed to save: {str(mapping_error)}"
        )

    # 응답: DB 메타정보 + 외부 API 데이터
    return WorkflowResponse(
        id=db_workflow.id,
        surro_workflow_id=db_workflow.surro_workflow_id,
        created_at=db_workflow.created_at,
        updated_at=db_workflow.updated_at,
        created_by=db_workflow.created_by,
        name=external_workflow.name,
        description=external_workflow.description,
        category=external_workflow.category,
        status=external_workflow.status,
        service_id=external_workflow.service_id,
        is_template=external_workflow.is_template,
        template_id=external_workflow.template_id
    )


@router.get("/", response_model=WorkflowListResponse)
async def get_workflows(
        page: Optional[int] = Query(None, ge=1, description="페이지 번호 (1부터 시작)"),
        size: Optional[int] = Query(None, ge=1, le=1000, description="페이지당 항목 수"),
        search: Optional[str] = Query(None, description="검색어 (이름, 설명)"),
        creator_id: Optional[str] = Query(None, description="생성자 ID 필터"),
        status: Optional[str] = Query(None, description="상태 필터 (DRAFT/ACTIVE/ERROR)"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우 목록 조회 (우리 DB 기준)"""
    skip = None
    limit = None

    if page is not None and size is not None:
        skip = (page - 1) * size
        limit = size

    # DB에서 조회
    workflows, total = workflow_crud.get_workflows(
        db=db,
        skip=skip,
        limit=limit,
        search=search,
        creator_id=creator_id,
        status=status
    )

    # 외부 API에서 각 워크플로우의 상세 정보 조회하여 병합
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    response_data = []
    for wf in workflows:
        try:
            external_wf = await workflow_service.get_workflow(wf.surro_workflow_id, user_info)
            if external_wf:
                response_data.append(
                    WorkflowResponse(
                        id=wf.id,
                        surro_workflow_id=wf.surro_workflow_id,
                        created_at=wf.created_at,
                        updated_at=wf.updated_at,
                        created_by=wf.created_by,
                        name=external_wf.name,
                        description=external_wf.description,
                        category=external_wf.category,
                        status=external_wf.status,
                        service_id=external_wf.service_id,
                        is_template=external_wf.is_template,
                        template_id=external_wf.template_id
                    )
                )
        except Exception as e:
            logger.error(f"Error fetching workflow {wf.surro_workflow_id}: {str(e)}")
            # 외부 API 조회 실패시에도 DB 정보라도 표시
            response_data.append(
                WorkflowResponse(
                    id=wf.id,
                    surro_workflow_id=wf.surro_workflow_id,
                    created_at=wf.created_at,
                    updated_at=wf.updated_at,
                    created_by=wf.created_by,
                    name=wf.name,
                    description=wf.description,
                    category=None,
                    status="UNKNOWN",
                    service_id=None,
                    is_template=False,
                    template_id=None
                )
            )

    return WorkflowListResponse(
        data=response_data,
        total=total,
        page=page,
        size=size
    )

# ===== Template 관련 =====

@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
        template_create: WorkflowCreateRequest,
        current_user=Depends(get_current_user)
):
    """워크플로우 템플릿 생성"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    workflow_definition_dict = None
    if template_create.workflow_definition:
        workflow_definition_dict = template_create.workflow_definition.dict()

    template_response = await workflow_service.create_template(
        name=template_create.name,
        description=template_create.description,
        category=template_create.category,
        workflow_definition=workflow_definition_dict,
        user_info=user_info
    )

    return template_response

@router.get("/templates")
async def get_templates(
        page: Optional[int] = Query(None, ge=1, description="페이지 번호 (1부터 시작)"),
        size: Optional[int] = Query(None, ge=1, le=1000, description="페이지당 항목 수"),
        category: Optional[str] = Query(None, description="카테고리 필터"),
        current_user=Depends(get_current_user)
):
    """워크플로우 템플릿 목록 조회 (외부 API에서만 조회)"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    templates_response = await workflow_service.get_templates(
        page=page,
        page_size=size,
        category=category,
        user_info=user_info
    )

    # 외부 API 응답을 그대로 반환
    return templates_response


@router.get("/templates/{template_id}")
async def get_template(
        template_id: str,
        current_user=Depends(get_current_user)
):
    """워크플로우 템플릿 상세 조회 (외부 API에서만 조회)"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    template_response = await workflow_service.get_template(
        template_id,
        user_info
    )

    if not template_response:
        raise HTTPException(status_code=404, detail="Template not found")

    return template_response

@router.put("/templates/{template_id}")
async def update_template(
        template_id: str,
        template_update: WorkflowUpdateRequest,
        current_user=Depends(get_current_user)
):
    """워크플로우 템플릿 수정"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    workflow_definition_dict = None
    if template_update.workflow_definition:
        workflow_definition_dict = template_update.workflow_definition.dict()

    template_response = await workflow_service.update_template(
        template_id=template_id,
        name=template_update.name,
        description=template_update.description,
        category=template_update.category,
        status=template_update.status,
        workflow_definition=workflow_definition_dict,
        user_info=user_info
    )

    return template_response


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(
        template_id: str,
        current_user=Depends(get_current_user)
):
    """워크플로우 템플릿 삭제"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    success = await workflow_service.delete_template(
        template_id,
        user_info
    )

    if not success:
        raise HTTPException(status_code=404, detail="Template not found")

    return None

@router.post("/templates/{template_id}/clone")
async def clone_template(
        template_id: str,
        workflow_name: str = Query(..., description="새로 생성할 워크플로우 이름"),
        service_id: Optional[int] = Query(None, description="연결할 서비스 ID"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """템플릿으로부터 워크플로우 생성"""
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    # 외부 API에서 템플릿 복제
    clone_response = await workflow_service.clone_template(
        template_id=template_id,
        workflow_name=workflow_name,
        service_id=service_id,
        user_info=user_info
    )

    # 우리 DB에 저장
    try:
        db_workflow = workflow_crud.create_workflow(
            db=db,
            name=workflow_name,
            description=clone_response.get('description'),
            created_by=current_user.member_id,
            surro_workflow_id=clone_response['id']
        )
        logger.info(
            f"Created workflow from template: surro_id={clone_response['id']}, "
            f"template_id={template_id}, member_id={current_user.member_id}"
        )

        # 응답에 DB 메타정보 추가
        clone_response['db_id'] = db_workflow.id
        clone_response['db_created_at'] = db_workflow.created_at.isoformat()
        clone_response['db_created_by'] = db_workflow.created_by

    except Exception as mapping_error:
        logger.error(f"Failed to save cloned workflow to DB: {str(mapping_error)}")
        logger.warning(
            f"Workflow {clone_response['id']} created from template but DB save failed"
        )

    return clone_response

@router.get("/{surro_workflow_id}", response_model=WorkflowDetailResponse)
async def get_workflow(
        surro_workflow_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우 상세 정보 조회"""
    # DB에서 조회
    db_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not db_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 외부 API에서 상세 정보 조회
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    external_workflow = await workflow_service.get_workflow(
        surro_workflow_id,
        user_info
    )

    if not external_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found in external service")

    # 응답 생성 (DB 필수 필드 + 외부 API 전체 데이터)
    return WorkflowDetailResponse(
        # DB 메타 정보 (필수)
        id=db_workflow.id,
        surro_workflow_id=db_workflow.surro_workflow_id,
        created_at=db_workflow.created_at,
        updated_at=db_workflow.updated_at,
        created_by=db_workflow.created_by,
        # 외부 API 데이터
        name=external_workflow.name,
        description=external_workflow.description,
        category=external_workflow.category,
        status=external_workflow.status,
        service_id=external_workflow.service_id,
        service_name=external_workflow.service_name,
        creator_id=external_workflow.creator_id,
        is_template=external_workflow.is_template,
        template_id=external_workflow.template_id,
        template_name=external_workflow.template_name,
        kubeflow_run_id=external_workflow.kubeflow_run_id,
        public_url=external_workflow.public_url,
        backend_api_url=external_workflow.backend_api_url,
        components=external_workflow.components,
        component_connections=external_workflow.component_connections
    )

@router.put("/{surro_workflow_id}", response_model=WorkflowResponse)
async def update_workflow(
        surro_workflow_id: str,
        workflow_update: WorkflowUpdateRequest,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우 정보 수정"""
    # 우리 DB에서 기존 워크플로우 조회 (권한 확인용)
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 권한 확인
    if current_user.role != "admin" and existing_workflow.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 업데이트
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    workflow_definition_dict = None
    if workflow_update.workflow_definition:
        workflow_definition_dict = workflow_update.workflow_definition.dict()

    try:
        updated_external = await workflow_service.update_workflow(
            workflow_id=surro_workflow_id,
            name=workflow_update.name,
            description=workflow_update.description,
            category=workflow_update.category,
            status=workflow_update.status,
            service_id=workflow_update.service_id,
            workflow_definition=workflow_definition_dict,
            user_info=user_info
        )

        if not updated_external:
            raise HTTPException(
                status_code=404,
                detail="Workflow not found in external service"
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update external workflow: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update external workflow: {str(e)}"
        )

    # DB 업데이트
    try:
        if workflow_update.name:
            existing_workflow.name = updated_external.name
        if workflow_update.description is not None:
            existing_workflow.description = updated_external.description

        db.commit()
        db.refresh(existing_workflow)
    except Exception as e:
        logger.error(f"Failed to sync DB with external API: {str(e)}")

    # 응답
    return WorkflowResponse(
        id=existing_workflow.id,
        surro_workflow_id=existing_workflow.surro_workflow_id,
        created_at=existing_workflow.created_at,
        updated_at=existing_workflow.updated_at,
        created_by=existing_workflow.created_by,
        name=updated_external.name,
        description=updated_external.description,
        category=updated_external.category,
        status=updated_external.status,
        service_id=updated_external.service_id,
        is_template=updated_external.is_template,
        template_id=updated_external.template_id
    )

@router.delete("/{surro_workflow_id}", status_code=202)
async def delete_workflow(
        surro_workflow_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우 삭제 시작"""
    # 외부 ID로 우리 DB에서 기존 워크플로우 조회
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 권한 확인
    if current_user.role != "admin" and existing_workflow.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 삭제 시작
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        deletion_response = await workflow_service.delete_workflow(
            surro_workflow_id,
            user_info
        )
        return deletion_response
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start workflow deletion: {str(e)}"
        )

@router.post("/{surro_workflow_id}/finalize-deletion")
async def finalize_workflow_deletion(
        surro_workflow_id: str,
        run_id: str = Query(..., description="Cleanup run ID"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우 삭제 완료 처리"""
    # 외부 API 삭제 완료 확인
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        finalize_response = await workflow_service.finalize_deletion(
            surro_workflow_id,
            run_id,
            user_info
        )

        # 삭제 완료된 경우 우리 DB에서도 삭제
        if finalize_response.get('status') == 'completed' and finalize_response.get('deleted_from_db'):
            success = workflow_crud.delete_workflow_by_surro_id(
                db=db,
                surro_workflow_id=surro_workflow_id
            )
            if not success:
                logger.warning(f"Workflow {surro_workflow_id} already deleted from DB")

        return finalize_response
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to finalize workflow deletion: {str(e)}"
        )

# ===== Workflow 실행 =====
@router.post("/{surro_workflow_id}/execute", response_model=WorkflowExecuteResponse)
async def execute_workflow(
        surro_workflow_id: str,
        execute_request: WorkflowExecuteRequest,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    워크플로우 실행 (KServe 배포 + Kubeflow 파이프라인 실행)

    워크플로우를 실행하여 ML 모델을 배포합니다. Kubeflow 파이프라인을 통해 KServe InferenceService를 생성하고,
    모델 서빙 엔드포인트를 활성화합니다.

    ## Process
    1. 지식베이스가 모델 앞에 있는지 검증
    2. MODEL 컴포넌트를 KServe InferenceService로 배포
    3. 워크플로우를 Kubeflow 파이프라인으로 변환
    4. 파이프라인 실행 및 모니터링 시작
    5. KServeDeployment 테이블에 배포 정보 기록

    ## Response Status
    - **PENDING**: 대기중
    - **RUNNING**: 실행중
    - **SUCCEEDED**: 성공
    - **FAILED**: 실패

    ## Notes
    - 워크플로우 상태가 **ERROR**인 경우만 실행 불가
    - **DRAFT** 상태에서도 실행 가능 (파이프라인 완료 시 자동으로 ACTIVE로 변경됨)
    - 지식베이스 컴포넌트는 모델 컴포넌트보다 앞에 있어야 함
    - 배포된 모델은 `/workflows/{workflow_id}/models`로 확인
    - 실행 상태는 `/workflows/{workflow_id}/status`로 모니터링
    - 파이프라인 완료 시 워크플로우 상태가 자동으로 **ACTIVE**로 변경됨

    ## Example Request
    ```json
    {
      "parameters": {
        "gpu_enabled": true,
        "replicas": 2
      }
    }
    ```
    """
    # 권한 확인
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 외부 API 실행
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    execute_response = await workflow_service.execute_workflow(
        surro_workflow_id,
        execute_request.parameters,
        user_info
    )

    return execute_response

@router.get("/{surro_workflow_id}/status")
async def get_workflow_status(
        surro_workflow_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우 실행 상태 조회"""
    # 권한 확인
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 외부 API 상태 조회
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    status_response = await workflow_service.get_workflow_status(
        surro_workflow_id,
        user_info
    )

    return status_response

# ===== Component Deployment Status (내부 API) =====

@router.post("/{surro_workflow_id}/components/{component_id}/deployment-status")
async def update_component_deployment_status(
        surro_workflow_id: str,
        component_id: str,
        service_name: str = Form(...),
        service_hostname: str = Form(...),
        model_name: str = Form(...),
        status: str = Form(...),
        internal_url: Optional[str] = Form(None),
        error_message: Optional[str] = Form(None),
        current_user=Depends(get_current_user)
):
    """
    컴포넌트 KServe 배포 상태 업데이트

    중요: 이 API는 Kubeflow Pipeline 내부에서만 호출되는 내부 API입니다.
    프론트엔드나 외부 클라이언트에서는 사용하지 않아야 합니다.
    """
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    update_response = await workflow_service.update_component_deployment_status(
        workflow_id=surro_workflow_id,
        component_id=component_id,
        service_name=service_name,
        service_hostname=service_hostname,
        model_name=model_name,
        status=status,
        internal_url=internal_url,
        error_message=error_message,
        user_info=user_info
    )

    return update_response

# ===== Workflow 테스트 =====

@router.post("/{surro_workflow_id}/test/rag", response_model=WorkflowTestResponse)
async def test_rag_workflow(
        surro_workflow_id: str,
        text: str = Form(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """RAG 워크플로우 테스트"""
    # 권한 확인
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 외부 API 테스트
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    test_response = await workflow_service.test_rag_workflow(
        surro_workflow_id,
        text,
        user_info
    )

    return test_response


@router.post("/{surro_workflow_id}/test/ml", response_model=WorkflowTestResponse)
async def test_ml_workflow(
        surro_workflow_id: str,
        image: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """ML 워크플로우 테스트"""
    # 권한 확인
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 외부 API 테스트
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    test_response = await workflow_service.test_ml_workflow(
        surro_workflow_id,
        image,
        user_info
    )

    return test_response

# ===== Workflow 상태 및 모델 조회 =====

@router.get("/{surro_workflow_id}/models")
async def get_workflow_models(
        surro_workflow_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우에 배포된 모델 목록 조회"""
    # 권한 확인
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 외부 API 모델 목록 조회
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    models_response = await workflow_service.get_workflow_models(
        surro_workflow_id,
        user_info
    )

    return models_response

# ===== Workflow 정리 =====

@router.post("/{surro_workflow_id}/cleanup", status_code=202)
async def cleanup_workflow(
        surro_workflow_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우 리소스 정리 시작"""
    # 권한 확인
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    if current_user.role != "admin" and existing_workflow.created_by != current_user.member_id:
        raise HTTPException(status_code=403, detail="Permission denied")

    # 외부 API 정리 시작
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        cleanup_response = await workflow_service.cleanup_workflow(
            surro_workflow_id,
            user_info
        )
        return cleanup_response
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start workflow cleanup: {str(e)}"
        )


@router.post("/{surro_workflow_id}/finalize-cleanup")
async def finalize_workflow_cleanup(
        surro_workflow_id: str,
        run_id: str = Query(..., description="Cleanup run ID"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """워크플로우 정리 완료 처리"""
    # 권한 확인
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    # 외부 API 정리 완료 확인
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    try:
        finalize_response = await workflow_service.finalize_cleanup(
            surro_workflow_id,
            run_id,
            user_info
        )
        return finalize_response
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to finalize workflow cleanup: {str(e)}"
        )