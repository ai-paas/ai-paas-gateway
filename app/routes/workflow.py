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
    """
    새로운 워크플로우 생성 (직접 생성)

    워크플로우를 직접 정의하여 생성합니다. 템플릿으로부터 생성하려면 /workflows/templates/{template_id}/clone API를 사용하세요. 생성된 워크플로우는 DRAFT 상태로 시작하며, execute API를 통해 실행할 수 있습니다.

    ## Request Body (WorkflowCreateRequest)
    - name (str, required): 워크플로우 이름
    - description (str, optional): 워크플로우 설명
    - category (str, optional): 카테고리 (분류용)
    - service_id (str, optional): 연결할 서비스 ID
    - workflow_definition (WorkflowDefinition, optional): 워크플로우 정의
        - components (List[ComponentCreateRequest]): 컴포넌트 목록
            - name (str): 컴포넌트 이름
            - type (ComponentType): 타입 (START/END/MODEL/KNOWLEDGE_BASE)
            - model_id (int, optional): MODEL 타입인 경우 모델 ID
            - knowledge_base_id (int, optional): KNOWLEDGE_BASE 타입인 경우 Knowledge Base ID
            - prompt_id (int, optional): MODEL 타입인 경우 프롬프트 ID
        - connections (List[ConnectionCreateRequest]): 연결 목록
            - source_component_type (ComponentType): 소스 컴포넌트 타입
            - target_component_type (ComponentType): 타겟 컴포넌트 타입

    ## Notes
    - 템플릿으로부터 생성하려면 /workflows/templates/{template_id}/clone API 사용
    - MODEL 컴포넌트는 유효한 model_id 필요, prompt_id는 선택
    - KNOWLEDGE_BASE 컴포넌트는 유효한 knowledge_base_id 필요
    - 생성 직후 상태는 DRAFT
    - is_template은 항상 false로 설정됨 (템플릿 생성은 /workflows/templates API 사용)
    - 상세 정보(components, connections, creator 등)는 GET /workflows/{workflow_id}로 조회 가능
    """
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
    """
        워크플로우 목록 조회 (템플릿 제외)

        생성된 워크플로우 목록을 조회합니다. 템플릿은 포함되지 않으며, 페이지네이션과 다양한 필터 옵션을 제공합니다.

        ## Query Parameters
        - page (int, optional): 페이지 번호 (1부터 시작)
        - page_size (int, optional): 페이지당 항목 수 (1-1000)
            - 페이지 파라미터 생략 시 전체 데이터 반환 (최대 10000개)
        - creator_id (int, optional): 특정 사용자가 생성한 워크플로우만 필터
        - service_id (int, optional): 특정 서비스에 연결된 워크플로우만 필터
        - status (str, optional): 워크플로우 상태 필터
            - "DRAFT": 임시저장 상태
            - "ACTIVE": 활성 상태 (배포됨)
            - "ERROR": 오류 상태

        ## Notes
        - 템플릿을 조회하려면 /workflows/templates API 사용
        - 페이지네이션 생략 시 최대 10000개까지 반환
        """
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
    """
        워크플로우 템플릿 생성

        재사용 가능한 워크플로우 템플릿을 생성합니다. 템플릿은 다른 사용자들이 복사하여 사용할 수 있는 기본 워크플로우 구조입니다.

        ## Request Body (WorkflowTemplateCreateRequest)
        - name (str, required): 템플릿 이름
        - description (str, optional): 템플릿 설명
        - category (str, optional): 템플릿 카테고리
        - workflow_definition (WorkflowDefinition, required): 템플릿 구조
            - components (List[ComponentCreateRequest]): 컴포넌트 정의
                - name (str): 컴포넌트 이름
                - type (str): 타입 (START/END/MODEL/KNOWLEDGE_BASE)
                - model_id (int, optional): MODEL 타입인 경우 모델 ID
                - knowledge_base_id (int, optional): KNOWLEDGE_BASE 타입인 경우 Knowledge Base ID
                - prompt_id (int, optional): MODEL 타입인 경우 프롬프트 ID
            - connections (List[ConnectionCreateRequest]): 연결 정의
                - source_component_id (str): 소스 컴포넌트 ID
                - target_component_id (str): 타겟 컴포넌트 ID

        ## Notes
        - 템플릿은 실행할 수 없고 복사용만 가능
        - 모든 사용자가 템플릿을 볼 수 있음
        - is_template은 항상 true로 설정됨
        - service_id는 항상 null로 설정됨 (템플릿은 서비스에 연결되지 않음)
        - usage_count는 0으로 시작
        - 상세 정보(components, connections 등)는 GET /workflows/templates/{template_id}로 조회 가능
        """
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
    """
        워크플로우 템플릿 목록 조회

        사용 가능한 모든 워크플로우 템플릿을 조회합니다. 템플릿은 모든 사용자가 확인하고 복사하여 사용할 수 있습니다.

        ## Query Parameters
        - page (int, optional): 페이지 번호 (1부터 시작)
        - page_size (int, optional): 페이지당 항목 수 (1-1000)
            - 페이지 파라미터 생략 시 전체 데이터 반환
        - category (str, optional): 템플릿 카테고리 필터
            - 특정 카테고리의 템플릿만 필터링

        ## Notes
        - 모든 사용자의 템플릿이 표시됨 (creator_id 필터 없음)
        - usage_count는 동적으로 계산됨
        - 페이지네이션 생략 시 최대 10000개까지 반환
        """
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
    """
        워크플로우 템플릿 상세 조회

        특정 템플릿의 상세 정보를 조회합니다. 템플릿의 전체 구조와 컴포넌트, 연결 정보를 포함합니다. 템플릿은 다른 사용자들이 복사하여 사용할 수 있는 재사용 가능한 워크플로우 구조입니다.

        ## Path Parameters
        - template_id (str): 조회할 템플릿 UUID
            - 템플릿 목록 조회 API(/workflows/templates)에서 확인 가능

        ## Notes
        - 템플릿은 실행할 수 없고 복사용으로만 사용 가능
        - 모든 사용자가 템플릿을 조회할 수 있음 (공개)
        - usage_count는 템플릿 복사 시 자동 증가
        - 템플릿으로부터 워크플로우 생성 시 /workflows/templates/{template_id}/clone API 사용
        """
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
    """
        워크플로우 템플릿 수정

        기존 워크플로우 템플릿의 정보를 수정합니다. workflow_definition이 제공되면 컴포넌트와 연결도 함께 업데이트됩니다. 템플릿은 서비스에 연결되지 않으므로 service_id는 수정할 수 없습니다.

        ## Path Parameters
        - template_id (str): 수정할 템플릿 UUID
            - 템플릿 목록 조회 API(/workflows/templates)에서 확인 가능

        ## Request Body (WorkflowTemplateUpdateRequest)
        - name (str, optional): 새 템플릿 이름
        - description (str, optional): 새 설명
        - category (str, optional): 새 카테고리
        - status (str, optional): 새 상태 (DRAFT/ACTIVE/ERROR)
            - 템플릿은 일반적으로 DRAFT 상태 유지 (실행 불가)
        - workflow_definition (WorkflowUpdateDefinition, optional): 새 템플릿 구조
            - components (List[ComponentUpdateRequest]): 컴포넌트 목록
                - name (str): 컴포넌트 이름
                - type (ComponentType): 타입 (START/END/MODEL/KNOWLEDGE_BASE)
                - model_id (int, optional): MODEL 타입인 경우 모델 ID
                - knowledge_base_id (int, optional): KNOWLEDGE_BASE 타입인 경우 Knowledge Base ID
                - prompt_id (int, optional): MODEL 타입인 경우 프롬프트 ID
            - connections (List[ConnectionUpdateRequest]): 연결 목록
                - source_component_type (ComponentType): 소스 컴포넌트 타입
                - target_component_type (ComponentType): 타겟 컴포넌트 타입

        ## Notes
        - 제공된 필드만 업데이트됨 (부분 업데이트 가능)
        - workflow_definition 제공 시 기존 컴포넌트/연결은 삭제 후 재생성됨
        - service_id는 템플릿에 포함되지 않음 (요청에서 제외, 항상 null로 유지)
        - 템플릿은 실행할 수 없고 복사용으로만 사용 가능
        - usage_count는 동적으로 계산됨 (파생된 워크플로우 수)
        - 일반 워크플로우 수정은 /workflows/{workflow_id} API 사용
        """
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
    """
        워크플로우 템플릿 삭제

        템플릿은 배포된 KServe InferenceService가 없으므로 즉시 DB에서 삭제됩니다. 파생된 워크플로우가 있으면 삭제 불가
        """
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
    """
        템플릿으로부터 워크플로우 생성

        기존 템플릿을 복사하여 새로운 워크플로우를 생성합니다. 템플릿의 모든 구조가 복사되며, 생성된 워크플로우는 즉시 실행 가능합니다.

        ## Path Parameters
        - template_id (str): 복사할 템플릿 UUID

        ## Query Parameters
        - workflow_name (str, required): 새로 생성할 워크플로우 이름
        - service_id (int, optional): 연결할 서비스 ID
            - 서비스와 연결시 모니터링 가능

        ## Notes
        - 템플릿의 모든 컴포넌트와 연결이 복사됨
        - 생성된 워크플로우는 템플릿과 독립적으로 동작
        - template_id가 자동으로 기록됨
        """
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
    """
        워크플로우 상세정보 조회

        특정 워크플로우의 상세 정보를 조회합니다. 컴포넌트, 연결, 배포 상태 등 모든 정보를 포함합니다. 워크플로우 실행 상태, 배포된 모델 정보, Kubeflow 파이프라인 실행 정보 등을 확인할 수 있습니다.

        ## Path Parameters
        - workflow_id (str): 조회할 워크플로우 UUID
            - 워크플로우 목록 조회 API(/workflows)에서 확인 가능

        ## Notes
        - public_url과 backend_api_url은 워크플로우 실행 후 배포가 완료되면 동적으로 생성됨
        - 템플릿인 경우 is_template=true (템플릿 조회 API 사용 권장)
        - kubeflow_run_id가 있으면 /workflows/{workflow_id}/status로 실행 상태 확인 가능
        - 배포된 모델 정보는 /workflows/{workflow_id}/models로 확인 가능
        - 워크플로우 실행은 /workflows/{workflow_id}/execute API 사용
        """
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
    """
        워크플로우 수정

        기존 워크플로우의 정보를 수정합니다. workflow_definition이 제공되면 컴포넌트와 연결도 함께 업데이트됩니다.

        ## Path Parameters
        - workflow_id (str): 수정할 워크플로우 UUID

        ## Request Body (WorkflowUpdateRequest)
        - name (str, optional): 새 워크플로우 이름
        - description (str, optional): 새 설명
        - category (str, optional): 새 카테고리
        - status (str, optional): 새 상태 (DRAFT/ACTIVE/ERROR)
            - "DRAFT": 임시저장 상태 (아직 실행되지 않음)
            - "ACTIVE": 활성 상태 (배포 완료, 실행 가능)
            - "ERROR": 오류 발생 상태 (실행 실패 또는 배포 오류)
        - service_id (str, optional): 연결할 서비스 ID
            - 모니터링 및 서비스 관리용 서비스 ID
            - null로 설정 시 서비스 연결 해제
        - workflow_definition (WorkflowUpdateDefinition, optional): 새 워크플로우 구조
            - components (List[ComponentUpdateRequest]): 컴포넌트 목록
                - name (str): 컴포넌트 이름
                - type (ComponentType): 타입 (START/END/MODEL/KNOWLEDGE_BASE)
                    - "START": 워크플로우 시작점
                    - "END": 워크플로우 종료점
                    - "MODEL": ML 모델 실행 노드
                    - "KNOWLEDGE_BASE": 지식 베이스 검색 노드
                - model_id (int, optional): MODEL 타입인 경우 모델 ID
                    - MODEL 타입인 경우 필수, 다른 타입은 null
                - knowledge_base_id (int, optional): KNOWLEDGE_BASE 타입인 경우 Knowledge Base ID
                    - KNOWLEDGE_BASE 타입인 경우 필수, 다른 타입은 null
                - prompt_id (int, optional): MODEL 타입인 경우 프롬프트 ID
                    - MODEL 타입인 경우 선택, 다른 타입은 null
            - connections (List[ConnectionUpdateRequest]): 연결 목록
                - source_component_type (ComponentType): 소스 컴포넌트 타입
                - target_component_type (ComponentType): 타겟 컴포넌트 타입

        ## Notes
        - 제공된 필드만 업데이트됨 (부분 업데이트 가능)
        - workflow_definition 제공 시 기존 컴포넌트/연결은 삭제 후 재생성됨
        - status를 ACTIVE로 변경해도 자동 배포되지 않음 (execute API 사용 필요)
        - service_id를 null로 설정하면 서비스 연결이 해제됨
        - 템플릿 수정은 /workflows/templates/{template_id} API 사용
        - 배포된 워크플로우의 구조 변경 시 재배포 필요
        """
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
    """
        워크플로우 삭제 시작 (2단계 프로세스)

        워크플로우 삭제를 시작합니다. KServe InferenceService를 정리하는 Kubeflow Pipeline을 실행하고 cleanup_run_id를 반환합니다. 실제 DB 삭제는 finalize-deletion API를 통해 완료 확인 후 수행됩니다.

        ## Path Parameters
        - workflow_id (str): 삭제할 워크플로우 UUID

        ## Deletion Process
        1. 현재 API 호출: 정리 파이프라인 시작
        2. Kubeflow Pipeline: KServe InferenceService 삭제
        3. finalize-deletion API: 완료 확인 및 DB 삭제

        ## Notes
        - 비동기 프로세스로 진행됨 (202 Accepted)
        - KServe 리소스 정리에 시간이 걸릴 수 있음
        - 템플릿은 바로 DB에서 삭제됨 (배포 리소스 없음)
        """
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
    """
        워크플로우 삭제 완료 처리

        KServe 리소스 정리가 완료되었는지 확인하고, 완료된 경우 DB에서 워크플로우를 삭제합니다.

        ## Path Parameters
        - workflow_id (str): 삭제할 워크플로우 UUID

        ## Query Parameters
        - run_id (str, required): Kubeflow Pipeline cleanup run ID
            - delete API에서 반환된 cleanup_run_id 사용

        ## Process
        1. Pipeline 상태 확인 (5초 타임아웃)
        2. 완료 시: DB에서 워크플로우 삭제
        3. 진행중: 진행 상태 반환
        4. 실패: 오류 메시지 반환

        ## Notes
        - 이미 삭제된 워크플로우 호출 시 "already deleted" 반환
        - Pipeline 상태 확인에 실패해도 DB 조회 시도
        - 삭제는 되돌릴 수 없는 작업
        """
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
    """
        워크플로우 실행 상태 조회

        워크플로우의 실행 상태와 배포된 모델들의 상태를 종합적으로 조회합니다. KServe 배포 상태와 Kubeflow 파이프라인 실행 상태를 모두 포함합니다.

        ## Path Parameters
        - workflow_id (str): 조회할 워크플로우 UUID

        ## Notes
        - 워크플로우가 실행되지 않았다면 kubeflow_run_id는 null
        - deployed_models는 MODEL 타입 컴포넌트가 있는 경우만 포함
        - 모든 조회는 DB 기반으로 수행되며, Kubernetes나 Kubeflow를 직접 조회하지 않음
        - 배포 상태는 kserve_deployments 테이블의 정보를 기반으로 함
        - deployed_models 조회 실패 시에도 에러를 발생시키지 않고 빈 리스트로 처리됨
        """
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
    컴포넌트의 KServe 배포 상태를 업데이트합니다.

    중요: 이 API는 Kubeflow Pipeline 내부에서만 호출되는 내부 API입니다. 프론트엔드나 외부 클라이언트에서는 사용하지 않아야 합니다.

    Kubeflow Pipeline 실행 중 컴포넌트의 KServe 배포가 완료되면, Pipeline 내부에서 자동으로 이 API를 호출하여 배포 상태를 업데이트합니다.
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
    """
        RAG 워크플로우 테스트

        Knowledge Base와 LLM 모델을 사용하는 RAG 워크플로우를 테스트합니다. 지식베이스가 있으면 검색 후 결과를 LLM 모델에 전달하여 추론하고, 지식베이스가 없으면 LLM 모델만 실행합니다.

        ## Path Parameters
        - workflow_id (str): 테스트할 워크플로우 UUID

        ## Request Body (Form Data)
        - text (str, required): 검색 쿼리 및 LLM 입력 텍스트

        ## Notes
        - 워크플로우는 배포되어 있어야 함 (ACTIVE 상태)
        - 워크플로우에 최소 하나의 LLM MODEL 컴포넌트 또는 KNOWLEDGE_BASE 컴포넌트가 있어야 함
        - Knowledge Base 컴포넌트는 선택 사항 (있으면 검색 후 결과를 LLM에 전달)
        - 지식베이스 검색 결과는 자동으로 LLM 모델의 context 파라미터로 전달됨
        - prompt_id가 설정된 경우:
            - prompt에 context 변수가 있으면: prompt의 {context} 또는 {{context}} 위치에 자동 치환
            - prompt에 context 변수가 없어도: [참고자료] 태그와 함께 별도의 system 메시지로 추가
            - prompt_id가 없는 경우: [참고자료] 태그와 함께 system 메시지로 추가
        - 각 컴포넌트의 실행 결과는 results 배열에 순서대로 포함됨
        - final_result는 최종 결과 문자열만 포함 (LLM 응답 또는 검색 결과)
        - 상세 정보 (total, search_method, full_response 등)는 results 배열의 각 컴포넌트 결과에서 확인 가능
        """
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
    """
        ML 워크플로우 테스트

        Object Detection Model을 사용하는 ML 워크플로우를 테스트합니다.

        ## Path Parameters
        - workflow_id (str): 테스트할 워크플로우 UUID

        ## Request Body (Form Data)
        - image (file, required): 이미지 파일 (ODM 추론용)
            - 지원 형식: JPEG, PNG, GIF, WebP
            - Base64로 인코딩되어 서버로 전송

        ## Notes
        - 워크플로우는 배포되어 있어야 함 (ACTIVE 상태)
        - 워크플로우에 최소 하나의 ODM MODEL 컴포넌트가 있어야 함
        - KNOWLEDGE_BASE 컴포넌트는 포함될 수 없음 (ML 워크플로우는 ODM만 지원)
        - 각 컴포넌트의 실행 결과는 results 배열에 순서대로 포함됨
        - final_result는 입력 이미지에 bbox와 label이 그려진 이미지를 base64로 인코딩한 문자열
        - bbox는 빨간색으로, label은 빨간 배경에 흰색 텍스트로 표시됨
        - 상세 정보 (predictions, image_info 등)는 results 배열의 각 컴포넌트 결과에서 확인 가능
        - 모든 추론 요청은 ServiceMonitoring 테이블에 자동 기록됨 (서비스와 연결된 경우)
        """
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
    """
        워크플로우에 배포된 모델 목록 조회

        워크플로우에서 배포된 모든 ML 모델의 상세 정보를 조회합니다. KServe InferenceService로 배포된 모델들의 엔드포인트와 상태를 포함합니다.

        ## Path Parameters
        - workflow_id (str): 조회할 워크플로우 UUID

        ## Notes
        - backend_api_url은 첫 번째 배포된 모델 기준으로 생성
        - 각 모델마다 고유한 service_name과 hostname을 가짐
        - 배포 상태가 DEPLOYED인 모델만 추론 가능
        """
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
    """
        워크플로우 리소스 정리 시작

        배포된 KServe InferenceService들을 정리합니다. 워크플로우 자체는 유지하면서 배포된 리소스만 제거합니다.

        ## Path Parameters
        - workflow_id (str): 정리할 워크플로우 UUID

        ## Process
        1. KServe InferenceService 삭제 파이프라인 시작
        2. cleanup_run_id 반환
        3. finalize-cleanup API로 완료 확인
        4. 워크플로우 상태를 DRAFT로 변경 (재실행 가능)

        ## Notes
        - 워크플로우는 삭제되지 않고 리소스만 정리
        - 비동기 프로세스 (202 Accepted)
        - 정리 후 워크플로우 재실행 가능
        """
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
    """
        워크플로우 정리 완료 처리

        KServe 리소스 정리가 완료되었는지 확인하고, 완료된 경우 워크플로우 상태를 업데이트합니다. 워크플로우는 삭제되지 않고 리소스만 정리되며, 정리 후 재실행이 가능합니다.

        ## Path Parameters
        - workflow_id (str): 정리할 워크플로우 UUID
            - 워크플로우 목록 조회 API(/workflows)에서 확인 가능

        ## Query Parameters
        - run_id (str, required): Kubeflow Pipeline cleanup run ID
            - cleanup API에서 반환된 cleanup_run_id 사용
            - 형식: Kubeflow Pipeline 실행 UUID

        ## Process
        1. 워크플로우 존재 여부 확인
        2. Pipeline 상태 확인 (5초 타임아웃)
        3. 완료 시:
            - 워크플로우 상태가 ERROR인 경우 DRAFT로 변경
            - KServe 배포 데이터(kserve_deployments) 삭제
            - 재실행 가능한 상태로 업데이트
        4. 진행중: 진행 상태 반환 (재호출 필요)
        5. 실패: 오류 메시지 반환

        ## Notes
        - 워크플로우는 삭제되지 않고 리소스만 정리됨
        - 정리 완료 후 워크플로우를 재실행할 수 있음
        - Pipeline 상태 확인은 짧은 타임아웃(5초)으로 즉시 확인
        - Pipeline이 아직 진행중이면 재호출하여 완료 확인 필요
        - ERROR 상태의 워크플로우는 정리 완료 시 DRAFT로 변경됨
        - 이미 DRAFT 상태인 워크플로우는 상태 변경 없음
        - cleanup API 호출 후 이 API를 호출하여 완료 확인 필요
        """
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