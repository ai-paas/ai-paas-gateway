from fastapi import APIRouter, Depends, HTTPException, Query, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.cruds.workflow import workflow_crud
from app.models.member import Member
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

    워크플로우 구성에 사용할 수 있는 컴포넌트 타입 목록을 조회합니다.
    각 타입별로 고유한 component_id와 설명을 제공하여 워크플로우 정의 시 활용할 수 있습니다.

    ## Response (List[ComponentTypeInfo])
    각 항목은 다음 필드를 포함:
    - **type** (str): 컴포넌트 타입
        - "START": 워크플로우 시작점
        - "END": 워크플로우 종료점
        - "MODEL": ML 모델 실행 노드
        - "KNOWLEDGE_BASE": 지식 베이스 검색 노드
    - **component_id** (str): 컴포넌트 식별자
        - 워크플로우 정의 시 사용할 고유 ID
        - 일반적으로 type과 동일 (예: "START", "END", "MODEL", "KNOWLEDGE_BASE")
    - **name** (str): 타입 표시명 (한글)
        - "시작 노드", "종료 노드", "모델 노드", "지식 베이스 노드" 등
    - **description** (str): 타입 설명
        - 각 컴포넌트 타입의 역할과 용도 설명

    게이트웨이는 MLOps 응답을 `{ "data": [...] }` 형태로 래핑하여 반환합니다.

    ## Notes
    - 고정된 타입 목록 반환 (동적 변경 없음)
    - 워크플로우는 반드시 START로 시작하고 END로 종료
    - MODEL 타입은 model_id 필수, prompt_id 선택
    - KNOWLEDGE_BASE 타입은 knowledge_base_id 필수

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류
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

    워크플로우를 직접 정의하여 생성합니다.
    템플릿으로부터 생성하려면 `/workflows/templates/{template_id}/clone` API를 사용하세요.
    생성된 워크플로우는 DRAFT 상태로 시작하며, execute API를 통해 실행할 수 있습니다.

    ## Request Body (WorkflowCreateRequest)
    - **name** (str, required): 워크플로우 이름
    - **description** (str, optional): 워크플로우 설명
    - **category** (str, optional): 카테고리 (분류용)
    - **service_id** (str, optional): 연결할 서비스 ID
    - **workflow_definition** (WorkflowDefinition, optional): 워크플로우 정의
        - components (List[ComponentCreateRequest]): 컴포넌트 목록
            - name (str): 컴포넌트 이름
            - type (ComponentType): 타입 (START/END/MODEL/KNOWLEDGE_BASE)
            - model_id (int, optional): MODEL 타입인 경우 모델 ID
            - knowledge_base_id (int, optional): KNOWLEDGE_BASE 타입인 경우 Knowledge Base ID
            - prompt_id (int, optional): MODEL 타입인 경우 프롬프트 ID
        - connections (List[ConnectionCreateRequest]): 연결 목록
            - source_component_type (ComponentType): 소스 컴포넌트 타입
            - target_component_type (ComponentType): 타겟 컴포넌트 타입

    ## Response (WorkflowResponse)
    - **id** (int): 게이트웨이 DB PK
    - **surro_workflow_id** (str): MLOps 워크플로우 UUID
    - **created_at** (datetime): 게이트웨이 DB 기준 생성 시각
    - **updated_at** (datetime): 게이트웨이 DB 기준 수정 시각
    - **created_by** (str): 게이트웨이 사용자 member_id
    - **name** (str): 워크플로우 이름
    - **description** (str): 워크플로우 설명
    - **category** (str): 워크플로우 카테고리
    - **status** (str): 워크플로우 상태
        - "DRAFT": 임시저장 상태 (아직 실행되지 않음)
        - "ACTIVE": 활성 상태 (배포 완료, 실행 가능)
        - "ERROR": 오류 발생 상태 (실행 실패 또는 배포 오류)
    - **service_id** (str): 연결된 서비스 ID
        - 모니터링 및 서비스 관리용 서비스 ID
        - null 가능 (서비스 연결 없이도 워크플로우 생성 가능)
    - **is_template** (bool): 템플릿 여부
        - false: 일반 워크플로우
        - true: 템플릿 (템플릿 조회 API 사용 권장)
    - **template_id** (str): 원본 템플릿 ID
        - 직접 생성한 경우 항상 null
        - 템플릿으로부터 생성된 경우 `/workflows/templates/{template_id}/clone` API 사용

    (MLOps 원본 응답의 `creator_id`(int)는 MLOps 슈퍼어드민 ID로, 게이트웨이에서는
     사용자 매핑을 위해 DB의 `created_by`(member_id, str)로 대체하여 반환)

    ## Notes
    - 템플릿으로부터 생성하려면 `/workflows/templates/{template_id}/clone` API 사용
    - MODEL 컴포넌트는 유효한 model_id 필요, prompt_id는 선택
    - KNOWLEDGE_BASE 컴포넌트는 유효한 knowledge_base_id 필요
    - 생성 직후 상태는 DRAFT
    - is_template은 항상 false로 설정됨 (템플릿 생성은 `/workflows/templates` API 사용)
    - 상세 정보(components, connections, creator 등)는 `GET /workflows/{workflow_id}`로 조회 가능

    ## Errors
    - **400**: 잘못된 요청 (정의 오류 등)
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류 (MLOps에는 생성됐으나 게이트웨이 DB 저장 실패 포함)
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
        size: Optional[int] = Query(None, ge=1, le=1000, description="페이지당 항목 수 (1-1000)"),
        search: Optional[str] = Query(None, description="이름/설명 검색어 (게이트웨이 확장)"),
        creator_id: Optional[str] = Query(None, description="생성자 member_id 필터 (게이트웨이 DB 기준)"),
        service_id: Optional[str] = Query(None, description="서비스 ID 필터 (UUID)"),
        status: Optional[str] = Query(None, description="상태 필터 (DRAFT/ACTIVE/ERROR)"),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    워크플로우 목록 조회 (템플릿 제외)

    생성된 워크플로우 목록을 조회합니다. 템플릿은 포함되지 않으며, 페이지네이션과 다양한 필터 옵션을 제공합니다.

    ## Query Parameters
    - page (int, optional): 페이지 번호 (1부터 시작)
    - size (int, optional): 페이지당 항목 수 (1-1000)
        - 페이지 파라미터 생략 시 전체 데이터 반환 (최대 10000개)
        - MLOps 원본의 `page_size`에 대응 — 게이트웨이-프론트 계약에 따라 `size`로 노출
    - search (str, optional): 이름/설명 검색어 (게이트웨이 DB 기준 확장 기능, MLOps 원본에는 없음)
    - creator_id (str, optional): 특정 사용자가 생성한 워크플로우만 필터
        - MLOps 원본은 `int`이지만 MLOps는 슈퍼어드민 단일 계정으로 동작하므로,
          게이트웨이 DB의 `created_by` (member_id, str) 기준으로 필터링
    - service_id (str, optional): 특정 서비스에 연결된 워크플로우만 필터 (UUID, MLOps 필터)
    - status (str, optional): 워크플로우 상태 필터 (MLOps 필터)
        - "DRAFT": 임시저장 상태
        - "ACTIVE": 활성 상태 (배포됨)
        - "ERROR": 오류 상태

    ## Response (WorkflowListResponse)
    - total (int): 필터 조건에 맞는 전체 워크플로우 수
    - page (int | null), size (int | null): 요청한 페이지네이션 값
    - data (List[WorkflowResponse]): 워크플로우 목록
        - id (int): 게이트웨이 DB PK
        - surro_workflow_id (str): MLOps 워크플로우 UUID
        - created_at (datetime): 게이트웨이 DB 기준 생성 시각
        - updated_at (datetime): 게이트웨이 DB 기준 수정 시각
        - created_by (str): 게이트웨이 사용자 member_id
        - name (str): 워크플로우 이름
        - description (str): 설명
        - category (str): 카테고리
        - status (str): 상태 (DRAFT/ACTIVE/ERROR)
        - service_id (str): 연결된 서비스 ID
        - is_template (bool): 템플릿 여부 (항상 false — 템플릿은 별도 API)
        - template_id (str): 원본 템플릿 ID (복제된 경우)

    ## Notes
    - 템플릿을 조회하려면 `/workflows/templates` API 사용
    - 페이지네이션 생략 시 최대 10000개까지 반환

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류
    """
    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    # 1) MLOps 전체 목록 조회 (service_id, status 필터는 MLOps에서 처리)
    #    - 페이지네이션은 동기화 + DB 필터 이후 게이트웨이에서 적용하므로 전체 조회
    #    - creator_id는 MLOps 의미 없음(슈퍼어드민 단일) → 게이트웨이 DB에서 필터
    external_list = await workflow_service.get_workflows(
        page=None,
        page_size=None,
        creator_id=None,
        service_id=service_id,
        status=status,
        user_info=user_info,
    )

    # 템플릿 제외 (이 엔드포인트는 템플릿 반환 안 함)
    external_list = [w for w in external_list if not w.is_template]
    external_by_id = {w.id: w for w in external_list}

    # 2) DB ↔ MLOps 동기화
    db_all, _ = workflow_crud.get_workflows(
        db=db, skip=None, limit=None,
        search=None, creator_id=None, status=None
    )
    db_surro_ids = {w.surro_workflow_id for w in db_all}

    # 2a) MLOps에서 사라진 워크플로우는 DB에서 제거
    #     (Workflow 모델에 soft-delete 컬럼이 없어 현재는 hard-delete)
    for dbw in db_all:
        if dbw.surro_workflow_id not in external_by_id:
            try:
                workflow_crud.delete_workflow_by_surro_id(
                    db=db, surro_workflow_id=dbw.surro_workflow_id
                )
                logger.info(
                    f"Removed orphan workflow from DB (not in MLOps): "
                    f"surro_id={dbw.surro_workflow_id}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to remove orphan workflow {dbw.surro_workflow_id}: {e}"
                )

    # 2b) MLOps에만 있는 워크플로우는 admin 소유로 등록
    missing = [w for w in external_list if w.id not in db_surro_ids]
    if missing:
        admin = db.query(Member).filter(
            Member.role == "admin", Member.is_active == True
        ).first()
        if not admin:
            logger.warning(
                f"No active admin member found — skipping auto-registration "
                f"for {len(missing)} workflow(s) discovered in MLOps"
            )
        else:
            for m in missing:
                try:
                    workflow_crud.create_workflow(
                        db=db,
                        name=m.name,
                        description=m.description,
                        created_by=admin.member_id,
                        surro_workflow_id=m.id,
                    )
                    logger.info(
                        f"Registered missing workflow under admin "
                        f"({admin.member_id}): surro_id={m.id}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to auto-register workflow {m.id}: {e}"
                    )

    # 3) 게이트웨이 DB 기준 필터 (creator_id, search)
    db_filtered, _ = workflow_crud.get_workflows(
        db=db,
        skip=None, limit=None,
        search=search,
        creator_id=creator_id,
        status=None,
    )

    # 4) MLOps 상세 데이터와 병합 (MLOps 응답에 없는 것은 제외 — status/service_id 필터 반영)
    merged = []
    for dbw in db_filtered:
        ext = external_by_id.get(dbw.surro_workflow_id)
        if not ext:
            continue
        merged.append(
            WorkflowResponse(
                id=dbw.id,
                surro_workflow_id=dbw.surro_workflow_id,
                created_at=dbw.created_at,
                updated_at=dbw.updated_at,
                created_by=dbw.created_by,
                name=ext.name,
                description=ext.description,
                category=ext.category,
                status=ext.status,
                service_id=ext.service_id,
                is_template=ext.is_template,
                template_id=ext.template_id,
            )
        )

    total = len(merged)

    # 5) 게이트웨이 레벨 페이지네이션
    if page is not None and size is not None:
        start = (page - 1) * size
        merged = merged[start:start + size]
    else:
        merged = merged[:10000]

    return WorkflowListResponse(
        data=merged,
        total=total,
        page=page,
        size=size,
    )

# ===== Template 관련 =====

@router.post("/templates", status_code=status.HTTP_201_CREATED)
async def create_template(
        template_create: WorkflowCreateRequest,
        current_user=Depends(get_current_user)
):
    """
    워크플로우 템플릿 생성

    재사용 가능한 워크플로우 템플릿을 생성합니다.
    템플릿은 다른 사용자들이 복사하여 사용할 수 있는 기본 워크플로우 구조입니다.

    ## Request Body (WorkflowTemplateCreateRequest)
    - **name** (str, required): 템플릿 이름
    - **description** (str, optional): 템플릿 설명
    - **category** (str, optional): 템플릿 카테고리
    - **workflow_definition** (WorkflowDefinition, required): 템플릿 구조
        - components (List[ComponentCreateRequest]): 컴포넌트 정의
            - name (str): 컴포넌트 이름
            - type (str): 타입 (START/END/MODEL/KNOWLEDGE_BASE)
            - model_id (int, optional): MODEL 타입인 경우 모델 ID
            - knowledge_base_id (int, optional): KNOWLEDGE_BASE 타입인 경우 Knowledge Base ID
            - prompt_id (int, optional): MODEL 타입인 경우 프롬프트 ID
        - connections (List[ConnectionCreateRequest]): 연결 정의
            - source_component_id (str): 소스 컴포넌트 ID
            - target_component_id (str): 타겟 컴포넌트 ID

    ## Response (WorkflowTemplateBriefSchema)
    - **id** (str): 템플릿 UUID
    - **name** (str): 템플릿 이름
    - **description** (str): 템플릿 설명
    - **category** (str): 템플릿 카테고리
    - **status** (str): 템플릿 상태 (DRAFT)
    - **service_id** (str): 기본 서비스 ID
    - **creator_id** (int): 템플릿 생성자 ID
    - **creator** (UserSchema): 생성자 정보
        - id (int): 사용자 ID
        - username (str): 사용자명
        - name (str): 사용자 이름
        - password (str): 비밀번호 (해시된 값)
        - created_at (datetime): 계정 생성 시각
        - updated_at (datetime): 계정 정보 수정 시각
        - created_by (str, optional): 계정 생성자
        - updated_by (str, optional): 계정 정보 수정자
    - **is_template** (bool): 템플릿 여부 (항상 true)
    - **template_id** (str): 원본 템플릿 ID (null)
    - **usage_count** (int): 템플릿 사용 횟수
        - 템플릿을 복사하여 생성된 워크플로우의 총 개수
        - 동적으로 계산됨 (실시간 반영)
        - 생성 직후는 0
    - **created_at** (datetime): 생성 시각
    - **updated_at** (datetime): 수정 시각

    (템플릿은 게이트웨이 DB에 매핑을 저장하지 않고 MLOps 응답을 그대로 전달합니다)

    ## Notes
    - 템플릿은 실행할 수 없고 복사용만 가능
    - 모든 사용자가 템플릿을 볼 수 있음
    - is_template은 항상 true로 설정됨
    - service_id는 항상 null로 설정됨 (템플릿은 서비스에 연결되지 않음)
    - usage_count는 0으로 시작
    - 상세 정보(components, connections 등)는 `GET /workflows/templates/{template_id}`로 조회 가능

    ## Errors
    - **400**: 잘못된 워크플로우 정의
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류
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

    사용 가능한 모든 워크플로우 템플릿을 조회합니다.
    템플릿은 모든 사용자가 확인하고 복사하여 사용할 수 있습니다.

    ## Query Parameters
    - **page** (int, optional): 페이지 번호 (1부터 시작)
    - **size** (int, optional): 페이지당 항목 수 (1-1000)
        - 페이지 파라미터 생략 시 전체 데이터 반환
        - MLOps 원본의 `page_size`에 대응 — 게이트웨이-프론트 계약에 따라 `size`로 노출
    - **category** (str, optional): 템플릿 카테고리 필터
        - 특정 카테고리의 템플릿만 필터링

    ## Response (WorkflowTemplateListSchema)
    - **total** (int): 필터 조건에 맞는 전체 템플릿 수
    - **items** (List[WorkflowTemplateBriefSchema]): 템플릿 목록
        - id (str): 템플릿 UUID
        - name (str): 템플릿 이름
        - description (str): 템플릿 설명
        - category (str): 템플릿 카테고리
        - status (str): 템플릿 상태 (DRAFT)
        - service_id (str): 기본 서비스 ID
        - creator_id (int): 템플릿 생성자 ID
        - creator (UserSchema): 생성자 정보
            - id (int): 사용자 ID
            - username (str): 사용자명
            - name (str): 사용자 이름
            - password (str): 비밀번호 (해시된 값)
            - created_at (datetime): 계정 생성 시각
            - updated_at (datetime): 계정 정보 수정 시각
            - created_by (str, optional): 계정 생성자
            - updated_by (str, optional): 계정 정보 수정자
        - is_template (bool): 템플릿 여부 (항상 true)
        - template_id (str): 원본 템플릿 ID (null)
        - usage_count (int): 해당 템플릿으로 생성된 워크플로우 수
        - created_at (datetime): 생성 시각
        - updated_at (datetime): 수정 시각

    (게이트웨이는 MLOps 응답을 그대로 전달합니다)

    ## Notes
    - 모든 사용자의 템플릿이 표시됨 (creator_id 필터 없음)
    - usage_count는 동적으로 계산됨
    - 페이지네이션 생략 시 최대 10000개까지 반환

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **500**: 서버 내부 오류
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

    특정 템플릿의 상세 정보를 조회합니다.
    템플릿의 전체 구조와 컴포넌트, 연결 정보를 포함합니다.
    템플릿은 다른 사용자들이 복사하여 사용할 수 있는 재사용 가능한 워크플로우 구조입니다.

    ## Path Parameters
    - **template_id** (str): 조회할 템플릿 UUID
        - 템플릿 목록 조회 API(`/workflows/templates`)에서 확인 가능

    ## Response (WorkflowTemplateReadSchema)
    - **id** (str): 템플릿 UUID
    - **name** (str): 템플릿 이름
    - **description** (str): 템플릿 설명
        - 템플릿의 용도와 사용 방법에 대한 설명
    - **category** (str): 템플릿 카테고리
        - 템플릿 분류를 위한 카테고리 (예: "Object Detection", "Classification")
    - **status** (str): 템플릿 상태
        - "DRAFT": 템플릿은 항상 DRAFT 상태 (실행 불가)
    - **service_id** (str): 기본 서비스 ID
        - 템플릿으로부터 워크플로우 생성 시 기본으로 연결될 서비스 ID
        - null 가능 (서비스 연결 없이 생성 가능)
    - **creator_id** (int): 템플릿 생성자 ID
    - **creator** (UserSchema): 생성자 정보
        - id (int): 사용자 ID
        - username (str): 사용자명
        - name (str): 사용자 이름
        - password (str): 비밀번호 (해시된 값)
        - created_at (datetime): 계정 생성 시각
        - updated_at (datetime): 계정 정보 수정 시각
        - created_by (str, optional): 계정 생성자
        - updated_by (str, optional): 계정 정보 수정자
    - **is_template** (bool): 템플릿 여부 (항상 true)
    - **components** (List[ComponentReadSchema]): 컴포넌트 상세 정보
        - id (str): 컴포넌트 UUID (workflow_component 테이블의 PK)
        - workflow_id (str): 소속 워크플로우 ID (템플릿 ID)
        - component_id (str): 컴포넌트 식별자
            - 워크플로우 내에서 고유한 식별자 (예: "START", "END", "MODEL-1")
        - name (str): 컴포넌트 이름
        - type (ComponentType): 컴포넌트 타입
            - "START": 워크플로우 시작점
            - "END": 워크플로우 종료점
            - "MODEL": ML 모델 실행 노드
            - "KNOWLEDGE_BASE": 지식 베이스 검색 노드
        - model_id (int, optional): 연결된 모델 ID
        - knowledge_base_id (int, optional): 연결된 Knowledge Base ID
        - prompt_id (int, optional): 연결된 프롬프트 ID
        - model (ModelBriefReadSchema, optional): 모델 상세 정보 (MODEL 타입인 경우)
            - id (int): 모델 ID
            - name (str): 모델 이름
            - description (str): 모델 설명
            - provider_info (ModelProviderReadSchema): 모델 제공자 정보
            - type_info (ModelTypeReadSchema): 모델 타입 정보
            - format_info (ModelFormatReadSchema): 모델 포맷 정보
            - parent_model_id (int, optional): 부모 모델 ID (파인튜닝인 경우 원본 모델)
            - registry (ModelRegistryReadSchema): 모델 레지스트리 정보
                - id (int): 레지스트리 ID
                - artifact_path (str): 아티팩트 경로
                - uri (str): 모델 URI
                - run_id (str, optional): MLflow 실행 ID
                - reference_model_id (int): 참조 모델 ID
                - created_at / updated_at (datetime)
            - created_at / updated_at (datetime)
        - created_at / updated_at (datetime)
    - **component_connections** (List[ConnectionReadSchema]): 연결 정보
        - id (str): 연결 UUID (workflow_component_connection 테이블의 PK)
        - workflow_id (str): 소속 워크플로우 ID (템플릿 ID)
        - source_component_id (str): 소스 컴포넌트 ID
        - target_component_id (str): 타겟 컴포넌트 ID
        - source_component (ComponentReadSchema): 소스 컴포넌트 상세 정보
        - target_component (ComponentReadSchema): 타겟 컴포넌트 상세 정보
        - created_at (datetime): 연결 생성 시각
    - **usage_count** (int): 해당 템플릿으로 생성된 워크플로우 수
        - 템플릿을 복사하여 생성된 워크플로우의 총 개수
        - 동적으로 계산됨 (실시간 반영)
    - **created_at** (datetime): 템플릿 생성 시각
    - **updated_at** (datetime): 템플릿 수정 시각

    (게이트웨이는 MLOps 응답을 그대로 전달합니다)

    ## Notes
    - 템플릿은 실행할 수 없고 복사용으로만 사용 가능
    - 모든 사용자가 템플릿을 조회할 수 있음 (공개)
    - usage_count는 템플릿 복사 시 자동 증가
    - 템플릿으로부터 워크플로우 생성 시 `/workflows/templates/{template_id}/clone` API 사용

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 템플릿을 찾을 수 없음
        - template_id가 존재하지 않거나 삭제된 경우
    - **500**: 서버 내부 오류
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

    기존 워크플로우 템플릿의 정보를 수정합니다.
    workflow_definition이 제공되면 컴포넌트와 연결도 함께 업데이트됩니다.
    템플릿은 서비스에 연결되지 않으므로 service_id는 수정할 수 없습니다.

    ## Path Parameters
    - **template_id** (str): 수정할 템플릿 UUID
        - 템플릿 목록 조회 API(`/workflows/templates`)에서 확인 가능

    ## Request Body (WorkflowTemplateUpdateRequest)
    - **name** (str, optional): 새 템플릿 이름
    - **description** (str, optional): 새 설명
    - **category** (str, optional): 새 카테고리
    - **status** (str, optional): 새 상태 (DRAFT/ACTIVE/ERROR)
        - 템플릿은 일반적으로 DRAFT 상태 유지 (실행 불가)
    - **workflow_definition** (WorkflowUpdateDefinition, optional): 새 템플릿 구조
        - components (List[ComponentUpdateRequest]): 컴포넌트 목록
            - name (str): 컴포넌트 이름
            - type (ComponentType): 타입 (START/END/MODEL/KNOWLEDGE_BASE)
            - model_id (int, optional): MODEL 타입인 경우 모델 ID
            - knowledge_base_id (int, optional): KNOWLEDGE_BASE 타입인 경우 Knowledge Base ID
            - prompt_id (int, optional): MODEL 타입인 경우 프롬프트 ID
        - connections (List[ConnectionUpdateRequest]): 연결 목록
            - source_component_type (ComponentType): 소스 컴포넌트 타입
            - target_component_type (ComponentType): 타겟 컴포넌트 타입

    ## Response (WorkflowTemplateReadSchema)
    - **id** (str): 템플릿 UUID
    - **name** (str): 템플릿 이름
    - **description** (str): 템플릿 설명
    - **category** (str): 템플릿 카테고리
    - **status** (str): 템플릿 상태 (DRAFT)
    - **service_id** (str): 기본 서비스 ID (항상 null)
    - **creator_id** (int): 템플릿 생성자 ID
    - **creator** (UserSchema): 생성자 정보
    - **is_template** (bool): 템플릿 여부 (항상 true)
    - **template_id** (str): 원본 템플릿 ID (항상 null)
    - **components** (List[ComponentReadSchema]): 컴포넌트 상세 정보
    - **component_connections** (List[ConnectionReadSchema]): 연결 정보
    - **usage_count** (int): 해당 템플릿으로 생성된 워크플로우 수
        - 템플릿을 복사하여 생성된 워크플로우의 총 개수
        - 동적으로 계산됨 (실시간 반영)
    - **created_at** (datetime): 템플릿 생성 시각
    - **updated_at** (datetime): 템플릿 수정 시각

    (게이트웨이는 MLOps 응답을 그대로 전달합니다)

    ## Notes
    - 제공된 필드만 업데이트됨 (부분 업데이트 가능)
    - workflow_definition 제공 시 기존 컴포넌트/연결은 삭제 후 재생성됨
    - service_id는 템플릿에 포함되지 않음 (요청에서 제외, 항상 null로 유지)
    - 템플릿은 실행할 수 없고 복사용으로만 사용 가능
    - usage_count는 동적으로 계산됨 (파생된 워크플로우 수)
    - 일반 워크플로우 수정은 `/workflows/{workflow_id}` API 사용

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 템플릿을 찾을 수 없음
        - template_id가 존재하지 않거나 템플릿이 아닌 경우
    - **500**: 서버 내부 오류
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

    템플릿은 배포된 KServe InferenceService가 없으므로 즉시 DB에서 삭제됩니다.
    파생된 워크플로우가 있으면 삭제 불가.

    ## Path Parameters
    - **template_id** (str): 삭제할 템플릿 UUID

    ## Response
    - **204 No Content**: 삭제 성공 (응답 바디 없음)

    ## Notes
    - 템플릿은 배포된 리소스가 없어 즉시 삭제됨
    - 해당 템플릿으로부터 복제된 워크플로우(파생된 워크플로우)가 존재하면 삭제 불가
    - 삭제는 되돌릴 수 없는 작업

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 템플릿을 찾을 수 없음
    - **409**: 파생된 워크플로우가 있어 삭제 불가
    - **500**: 서버 내부 오류
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

    기존 템플릿을 복사하여 새로운 워크플로우를 생성합니다.
    템플릿의 모든 구조가 복사되며, 생성된 워크플로우는 즉시 실행 가능합니다.

    ## Path Parameters
    - **template_id** (str): 복사할 템플릿 UUID

    ## Query Parameters
    - **workflow_name** (str, required): 새로 생성할 워크플로우 이름
    - **service_id** (int, optional): 연결할 서비스 ID
        - 서비스와 연결시 모니터링 가능
        - (MLOps 원본은 UUID str이나, 게이트웨이는 내부 서비스 매핑을 위해 int로 노출)

    ## Response (WorkflowReadSchema)
    - **id** (str): 생성된 워크플로우 UUID
    - **name** (str): 워크플로우 이름
    - **description** (str): 워크플로우 설명 (템플릿에서 복사)
    - **category** (str): 카테고리 (템플릿에서 복사)
    - **status** (str): 상태 (DRAFT로 시작)
    - **service_id** (str): 연결된 서비스 ID
    - **service_name** (str): 연결된 서비스 이름
    - **creator_id** (int): 생성자 ID (현재 사용자, MLOps 기준)
    - **creator** (UserSchema): 생성자 정보
    - **is_template** (bool): 템플릿 여부 (false)
    - **template_id** (str): 원본 템플릿 ID
    - **template_name** (str): 원본 템플릿 이름
    - **kubeflow_run_id** (str): Kubeflow 실행 ID (null)
    - **components** (List[ComponentReadSchema]): 복사된 컴포넌트
    - **component_connections** (List[ConnectionReadSchema]): 복사된 연결
    - **created_at** (datetime): 생성 시각
    - **updated_at** (datetime): 수정 시각

    게이트웨이 추가 필드 (응답에 함께 포함):
    - **db_id** (int): 게이트웨이 DB PK
    - **db_created_at** (str): 게이트웨이 DB 생성 시각 (ISO 8601)
    - **db_created_by** (str): 게이트웨이 사용자 member_id

    ## Notes
    - 템플릿의 모든 컴포넌트와 연결이 복사됨
    - 생성된 워크플로우는 템플릿과 독립적으로 동작
    - template_id가 자동으로 기록됨
    - MLOps에는 복제되었으나 게이트웨이 DB 저장에 실패하는 경우 경고만 기록하고 MLOps 응답은 그대로 반환

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 템플릿을 찾을 수 없음
    - **500**: 서버 내부 오류
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

    특정 워크플로우의 상세 정보를 조회합니다.
    컴포넌트, 연결, 배포 상태 등 모든 정보를 포함합니다.
    워크플로우 실행 상태, 배포된 모델 정보, Kubeflow 파이프라인 실행 정보 등을 확인할 수 있습니다.

    ## Path Parameters
    - **workflow_id** (str): 조회할 워크플로우 UUID (MLOps 기준)
        - 워크플로우 목록 조회 API(`/workflows`)에서 확인 가능
        - 게이트웨이에서는 `surro_workflow_id`로도 참조

    ## Response (WorkflowDetailResponse)
    - **id** (int): 게이트웨이 DB PK
    - **surro_workflow_id** (str): MLOps 워크플로우 UUID
    - **created_at** (datetime): 게이트웨이 DB 기준 생성 시각
    - **updated_at** (datetime): 게이트웨이 DB 기준 수정 시각
    - **created_by** (str): 게이트웨이 사용자 member_id
    - **name** (str): 워크플로우 이름
    - **description** (str): 워크플로우 설명
        - 워크플로우의 용도와 목적에 대한 설명
    - **category** (str): 워크플로우 카테고리
        - 워크플로우 분류를 위한 카테고리 (예: "Object Detection", "Classification")
    - **status** (str): 워크플로우 상태
        - "DRAFT": 임시저장 상태 (아직 실행되지 않음)
        - "ACTIVE": 활성 상태 (배포 완료, 실행 가능)
        - "ERROR": 오류 발생 상태 (실행 실패 또는 배포 오류)
    - **service_id** (str): 연결된 서비스 ID
        - 모니터링 및 서비스 관리용 서비스 ID
        - null 가능 (서비스 연결 없이도 워크플로우 생성 가능)
    - **service_name** (str): 연결된 서비스 이름
        - service_id로부터 동적으로 조회된 서비스 이름
        - service_id가 null이면 null
    - **creator_id** (int): MLOps 기준 생성자 ID
    - **is_template** (bool): 템플릿 여부
        - false: 일반 워크플로우
        - true: 템플릿 (템플릿 조회 API 사용 권장)
    - **template_id** (str): 원본 템플릿 ID
        - 템플릿으로부터 생성된 경우 원본 템플릿 ID
        - 직접 생성한 경우 null
    - **template_name** (str): 원본 템플릿 이름
    - **kubeflow_run_id** (str): Kubeflow 파이프라인 실행 ID
        - 워크플로우 실행 시 생성된 Kubeflow Pipeline 실행 ID
        - 실행 전이면 null
    - **public_url** (str): KServe 공개 엔드포인트 URL
        - 배포 후 동적으로 생성되는 공개 접근 URL
        - 배포 전이면 null
        - 형식: `{gateway_url}/v2/models/{model_name}/infer`
    - **backend_api_url** (str): 백엔드 API URL
        - 배포 후 동적으로 생성되는 백엔드 API URL
        - 배포 전이면 null
    - **components** (List[ComponentReadSchema]): 컴포넌트 목록
        - id / workflow_id / component_id / name / type (START|END|MODEL|KNOWLEDGE_BASE)
        - model_id / knowledge_base_id / prompt_id (optional)
        - model (ModelBriefReadSchema, optional): MODEL 타입인 경우 상세 정보
            - id / name / description
            - provider_info / type_info / format_info
            - parent_model_id / registry / created_at / updated_at
        - created_at / updated_at
    - **component_connections** (List[ConnectionReadSchema]): 연결 정보
        - id / workflow_id / source_component_id / target_component_id
        - source_component / target_component (ComponentReadSchema 전체)
        - created_at

    (MLOps 원본의 `creator`(UserSchema)는 MLOps 슈퍼어드민 정보라 게이트웨이에서는
     별도로 반환하지 않고, 대신 `created_by`(member_id)를 제공)

    ## Notes
    - public_url과 backend_api_url은 워크플로우 실행 후 배포가 완료되면 동적으로 생성됨
    - 템플릿인 경우 is_template=true (템플릿 조회 API 사용 권장)
    - kubeflow_run_id가 있으면 `/workflows/{workflow_id}/status`로 실행 상태 확인 가능
    - 배포된 모델 정보는 `/workflows/{workflow_id}/models`로 확인 가능
    - 워크플로우 실행은 `/workflows/{workflow_id}/execute` API 사용

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 워크플로우를 찾을 수 없음
        - 게이트웨이 DB 또는 MLOps 어느 한 쪽에서 찾지 못한 경우
    - **500**: 서버 내부 오류
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

    기존 워크플로우의 정보를 수정합니다.
    workflow_definition이 제공되면 컴포넌트와 연결도 함께 업데이트됩니다.

    ## Path Parameters
    - **workflow_id** (str): 수정할 워크플로우 UUID

    ## Request Body (WorkflowUpdateRequest)
    - **name** (str, optional): 새 워크플로우 이름
    - **description** (str, optional): 새 설명
    - **category** (str, optional): 새 카테고리
    - **status** (str, optional): 새 상태 (DRAFT/ACTIVE/ERROR)
        - "DRAFT": 임시저장 상태 (아직 실행되지 않음)
        - "ACTIVE": 활성 상태 (배포 완료, 실행 가능)
        - "ERROR": 오류 발생 상태 (실행 실패 또는 배포 오류)
    - **service_id** (str, optional): 연결할 서비스 ID
        - 모니터링 및 서비스 관리용 서비스 ID
        - null로 설정 시 서비스 연결 해제
    - **workflow_definition** (WorkflowUpdateDefinition, optional): 새 워크플로우 구조
        - components (List[ComponentUpdateRequest]): 컴포넌트 목록
            - name (str): 컴포넌트 이름
            - type (ComponentType): 타입 (START/END/MODEL/KNOWLEDGE_BASE)
                - "START": 워크플로우 시작점
                - "END": 워크플로우 종료점
                - "MODEL": ML 모델 실행 노드
                - "KNOWLEDGE_BASE": 지식 베이스 검색 노드
            - model_id (int, optional): MODEL 타입인 경우 모델 ID
            - knowledge_base_id (int, optional): KNOWLEDGE_BASE 타입인 경우 Knowledge Base ID
            - prompt_id (int, optional): MODEL 타입인 경우 프롬프트 ID (선택)
        - connections (List[ConnectionUpdateRequest]): 연결 목록
            - source_component_type (ComponentType): 소스 컴포넌트 타입
            - target_component_type (ComponentType): 타겟 컴포넌트 타입

    ## Response (WorkflowResponse)
    - **id** (int): 게이트웨이 DB PK
    - **surro_workflow_id** (str): MLOps 워크플로우 UUID
    - **created_at** / **updated_at** (datetime): 게이트웨이 DB 메타
    - **created_by** (str): 게이트웨이 사용자 member_id
    - **name** (str): 워크플로우 이름
    - **description** (str): 워크플로우 설명
    - **category** (str): 워크플로우 카테고리
    - **status** (str): 워크플로우 상태 (DRAFT/ACTIVE/ERROR)
    - **service_id** (str): 연결된 서비스 ID
    - **is_template** (bool): 템플릿 여부 (false)
    - **template_id** (str): 원본 템플릿 ID

    (MLOps 원본 응답의 `creator` / `components` / `component_connections` / `kubeflow_run_id` /
     `public_url` / `backend_api_url` 등 상세 정보는 `GET /workflows/{workflow_id}`로 별도 조회)

    ## Notes
    - 제공된 필드만 업데이트됨 (부분 업데이트 가능)
    - workflow_definition 제공 시 기존 컴포넌트/연결은 삭제 후 재생성됨
    - status를 ACTIVE로 변경해도 자동 배포되지 않음 (execute API 사용 필요)
    - service_id를 null로 설정하면 서비스 연결이 해제됨
    - 템플릿 수정은 `/workflows/templates/{template_id}` API 사용
    - 배포된 워크플로우의 구조 변경 시 재배포 필요
    - 게이트웨이 권한 검사: admin 이거나 해당 워크플로우의 `created_by` 사용자만 수정 가능

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **403**: 권한 없음 (본인 소유가 아니며 admin도 아님)
    - **404**: 워크플로우를 찾을 수 없음
    - **500**: 서버 내부 오류
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

    워크플로우 삭제를 시작합니다. KServe InferenceService를 정리하는
    Kubeflow Pipeline을 실행하고 cleanup_run_id를 반환합니다.
    실제 DB 삭제는 `finalize-deletion` API를 통해 완료 확인 후 수행됩니다.

    ## Path Parameters
    - **workflow_id** (str): 삭제할 워크플로우 UUID

    ## Response (202 Accepted)
    - **message** (str): 상태 메시지 "Workflow deletion started"
    - **workflow_id** (str): 워크플로우 UUID
    - **cleanup_run_id** (str): 정리 파이프라인 실행 ID
    - **status** (str): 현재 상태 "cleanup_in_progress"
    - **next_step** (str): 다음 단계 API 안내
        - 형식: "Call /workflows/{workflow_id}/finalize-deletion to complete deletion"

    ## Deletion Process
    1. 현재 API 호출: 정리 파이프라인 시작
    2. Kubeflow Pipeline: KServe InferenceService 삭제
    3. `finalize-deletion` API 호출: Kubernetes 리소스 직접 확인 및 DB 삭제

    ## Notes
    - 비동기 프로세스로 진행됨 (202 Accepted)
    - KServe 리소스 정리에 시간이 걸릴 수 있음
    - 템플릿은 바로 DB에서 삭제됨 (배포 리소스 없음)
    - 게이트웨이 권한 검사: admin 이거나 해당 워크플로우의 `created_by` 사용자만 삭제 가능

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **403**: 권한 없음 (본인 소유가 아니며 admin도 아님)
    - **404**: 워크플로우를 찾을 수 없음
    - **500**: 정리 파이프라인 시작 실패
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

    Kubernetes 클러스터를 직접 조회하여 리소스가 실제로 삭제되었는지 확인하고,
    확인된 경우 DB에서 워크플로우를 삭제합니다.

    ## Path Parameters
    - **workflow_id** (str): 삭제할 워크플로우 UUID

    ## Query Parameters
    - **run_id** (str, required): Kubeflow Pipeline cleanup run ID
        - `DELETE /workflows/{workflow_id}` 응답의 `cleanup_run_id` 사용

    ## Response
    - **workflow_id** (str): 워크플로우 UUID
    - **status** (str): 삭제 상태
        - "completed": 삭제 완료
            - Kubernetes 리소스가 실제로 삭제되어 확인됨
            - DB에서 워크플로우가 삭제됨
        - "in_progress": 아직 진행중
            - Kubernetes에 리소스가 아직 존재함
            - 완료될 때까지 대기 후 재호출 필요
        - "failed": 삭제 실패
            - Kubernetes 리소스 확인 중 오류 발생
            - error_message에 상세 오류 정보 포함
    - **deleted_from_db** (bool): DB에서 삭제 여부
        - true: 완전히 삭제됨
        - false: 아직 삭제되지 않음
    - **message** (str): 상태 메시지

    게이트웨이는 `status == "completed"` 이면서 `deleted_from_db == true` 일 때
    게이트웨이 DB의 매핑 레코드(workflows 테이블)도 함께 삭제합니다.

    ## Process
    1. 워크플로우 존재 여부 확인
    2. Kubernetes 클러스터에서 리소스 직접 조회
       - InferenceService 조회
       - Ollama Deployment/Service 조회
    3. 리소스가 모두 삭제된 경우: MLOps DB + 게이트웨이 DB에서 워크플로우 삭제
    4. 리소스가 아직 존재하는 경우: 진행중 상태 반환 (재호출 필요)
    5. 확인 중 오류 발생: 실패 상태 반환

    ## Notes
    - 이미 삭제된 워크플로우 호출 시 "already deleted" 반환
    - Kubernetes 리소스 확인에 실패해도 DB 조회 시도
    - 삭제는 되돌릴 수 없는 작업
    - 리소스가 아직 존재하면 재호출하여 완료 확인 필요

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **500**: 삭제 처리 중 오류 발생
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

    워크플로우를 실행하여 ML 모델을 배포합니다.
    Kubeflow 파이프라인을 통해 KServe InferenceService를 생성하고,
    모델 서빙 엔드포인트를 활성화합니다.

    ## Path Parameters
    - **workflow_id** (str): 실행할 워크플로우 UUID

    ## Request Body (WorkflowExecuteRequest)
    - **parameters** (Dict[str, Any], optional): 실행 파라미터
        - 커스텀 설정 값들을 전달할 수 있음
        - 예: `{"gpus": 1, "replicas": 2}`

    ## Response (WorkflowExecuteResponse)
    - **workflow_id** (str): 실행된 워크플로우 UUID
    - **kubeflow_run_id** (str): Kubeflow 파이프라인 실행 ID
    - **status** (str): 실행 상태
        - "PENDING": 대기중
        - "RUNNING": 실행중
        - "SUCCEEDED": 성공
        - "FAILED": 실패
    - **message** (str): 상태 메시지

    ## Process
    1. 지식베이스가 모델 앞에 있는지 검증
    2. MODEL 컴포넌트를 KServe InferenceService로 배포
    3. 워크플로우를 Kubeflow 파이프라인으로 변환
    4. 파이프라인 실행 및 모니터링 시작
    5. KServeDeployment 테이블에 배포 정보 기록

    ## Notes
    - 워크플로우 상태가 ERROR인 경우만 실행 불가
    - DRAFT 상태에서도 실행 가능 (파이프라인 완료 시 자동으로 ACTIVE로 변경됨)
    - 지식베이스 컴포넌트는 모델 컴포넌트보다 앞에 있어야 함
    - 배포된 모델은 `/workflows/{workflow_id}/models`로 확인
    - 실행 상태는 `/workflows/{workflow_id}/status`로 모니터링
    - 파이프라인 완료 시 워크플로우 상태가 자동으로 ACTIVE로 변경됨

    ## Errors
    - **400**: 워크플로우가 ERROR 상태이거나 지식베이스가 모델 뒤에 있음
    - **401**: 인증되지 않은 사용자
    - **404**: 워크플로우를 찾을 수 없음
    - **500**: 실행 중 오류 발생
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

    워크플로우의 실행 상태와 배포된 모델들의 상태를 종합적으로 조회합니다.
    KServe 배포 상태와 Kubeflow 파이프라인 실행 상태를 모두 포함합니다.

    ## Path Parameters
    - **workflow_id** (str): 조회할 워크플로우 UUID

    ## Response
    - **workflow_id** (str): 워크플로우 UUID
        - `str(workflow.id)`로 변환된 값
    - **status** (str): 워크플로우 상태
        - "DRAFT": 임시저장 상태 (아직 실행되지 않음)
        - "ACTIVE": 활성 상태 (배포 완료, 실행 가능)
        - "ERROR": 오류 발생 상태 (실행 실패 또는 배포 오류)
    - **kubeflow_run_id** (str, optional): Kubeflow 파이프라인 실행 ID
        - 워크플로우가 실행된 경우에만 포함
        - 실행 전이면 null
        - 참조용으로만 포함되며, 실제 파이프라인 상태는 조회하지 않음
    - **deployed_models** (List[dict]): 배포된 모델 목록
        - **component_id** (str): 컴포넌트 UUID
        - **service_name** (str): KServe InferenceService 이름 (DNS 1035 규칙 준수)
        - **service_hostname** (str): KServe 서비스 호스트명
            - Istio Virtual Service 라우팅에 사용
            - 형식: `{service_name}.{namespace}.example.com`
        - **model_name** (str): 컴포넌트 이름 (사용자가 지정한 이름)
        - **sanitized_model_name** (str): 정제된 모델 이름
            - DNS 규칙에 맞게 변환된 모델 이름 (슬래시가 하이픈으로 변경됨)
            - KServe 엔드포인트에서 실제로 사용되는 이름
        - **model_id** (int, optional): 모델 ID (MODEL 타입 컴포넌트인 경우)
        - **internal_url** (str, optional): 내부 접근 URL
            - 형식: `http://{service_name}.{namespace}.svc.cluster.local`
        - **gateway_url** (str): 외부에서 접근 가능한 KServe Gateway 엔드포인트 URL
        - **status** (str): 배포 상태
            - "DEPLOYING": 배포 중
            - "DEPLOYED": 배포 완료
            - "FAILED": 배포 실패
            - "DELETED": 삭제됨
        - **deployed_at** (str, optional): 배포 시각 (ISO 8601)
        - **error_message** (str, optional): 배포 실패 시 오류 내용
    - **error** (str, optional): 상태 조회 실패 시 오류 메시지

    ## Notes
    - 워크플로우가 실행되지 않았다면 `kubeflow_run_id`는 null
    - `deployed_models`는 MODEL 타입 컴포넌트가 있는 경우만 포함
    - 모든 조회는 DB 기반으로 수행되며, Kubernetes나 Kubeflow를 직접 조회하지 않음
    - 배포 상태는 `kserve_deployments` 테이블의 정보를 기반으로 함
    - `deployed_models` 조회 실패 시에도 에러를 발생시키지 않고 빈 리스트로 처리됨

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 워크플로우를 찾을 수 없음
    - **500**: 상태 조회 중 오류 발생 (응답에 `error` 필드가 포함될 수 있음)
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

    **중요**: 이 API는 Kubeflow Pipeline 내부에서만 호출되는 내부 API입니다.
    프론트엔드나 외부 클라이언트에서는 사용하지 않아야 합니다.

    Kubeflow Pipeline 실행 중 컴포넌트의 KServe 배포가 완료되면,
    Pipeline 내부에서 자동으로 이 API를 호출하여 배포 상태를 업데이트합니다.

    ## Path Parameters
    - **workflow_id** (str): 워크플로우 ID
    - **component_id** (str): 컴포넌트 UUID

    ## Request Body (Form Data)
    - **service_name** (str, required): KServe 서비스 이름
    - **service_hostname** (str, required): KServe 서비스 호스트명
    - **model_name** (str, required): 배포된 모델 이름
    - **status** (str, required): 배포 상태 (예: "ready", "failed")
    - **internal_url** (str, optional): 내부 서비스 URL
    - **error_message** (str, optional): 배포 실패 시 에러 메시지

    ## Response
    - **message** (str): 업데이트 결과 메시지
    - **deployment_info** (dict): 배포 정보
        - service_name (str): 서비스 이름
        - service_hostname (str): 서비스 호스트명
        - model_name (str): 모델 이름
        - status (str): 배포 상태
        - internal_url (str, optional): 내부 서비스 URL

    ## Notes
    - 이 API는 Kubeflow Pipeline의 컴포넌트 내부에서만 호출됩니다
    - 프론트엔드나 사용자 애플리케이션에서는 직접 호출하지 않아야 합니다
    - 배포 상태는 Pipeline 실행 중 자동으로 업데이트됩니다

    ## Errors
    - **404**: 워크플로우를 찾을 수 없음
    - **500**: 배포 상태 업데이트 중 서버 내부 오류
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

    Knowledge Base와 LLM 모델을 사용하는 RAG 워크플로우를 테스트합니다.
    지식베이스가 있으면 검색 후 결과를 LLM 모델에 전달하여 추론하고,
    지식베이스가 없으면 LLM 모델만 실행합니다.

    ## Path Parameters
    - **workflow_id** (str): 테스트할 워크플로우 UUID

    ## Request Body (Form Data)
    - **text** (str, required): 검색 쿼리 및 LLM 입력 텍스트

    ## Response (WorkflowTestResponse)
    - **workflow_id** (str): 워크플로우 UUID
    - **execution_order** (List[str]): 실행된 컴포넌트 ID 순서 (워크플로우 실행 순서)
    - **results** (List[ComponentTestResult]): 각 컴포넌트 실행 결과 목록
        - 각 항목은 다음 중 하나의 타입:

        **KnowledgeBaseComponentTestResult** (지식베이스 컴포넌트인 경우):
        - **component_id** (str): 컴포넌트 UUID
        - **component_name** (str): 컴포넌트 이름
        - **component_type** (str): "KNOWLEDGE_BASE"
        - **model_type** (str): "embedding"
        - **result** (KnowledgeBaseTestResult): 검색 결과
            - **search_result** (str): 검색 결과 문자열 (LLM 프롬프트에 사용 가능한 형식)
            - **total** (int): 검색 결과 총 개수
            - **search_method** (str): 검색 방법 (예: "similarity", "keyword")

        **ModelComponentTestResult** (LLM 모델 컴포넌트인 경우):
        - **component_id** (str): 컴포넌트 UUID
        - **component_name** (str): 컴포넌트 이름
        - **component_type** (str): "MODEL"
        - **model_type** (str): "LLM"
        - **result** (ModelLLMTestResult): LLM 추론 결과
            - **response** (str): LLM 응답 텍스트
            - **full_response** (dict, optional): Ollama API 전체 응답 (디버깅용)

        **ComponentTestErrorResult** (오류 발생 시):
        - **component_id** (str): 컴포넌트 UUID
        - **component_name** (str): 컴포넌트 이름
        - **component_type** (str): "KNOWLEDGE_BASE" 또는 "MODEL"
        - **model_type** (str, optional): 모델 타입 (오류 발생 시 null 가능)
        - **error** (str): 오류 메시지

    - **final_result** (str, optional): 최종 결과 문자열
        - 우선순위: 마지막 LLM MODEL 컴포넌트의 응답 > 마지막 KNOWLEDGE_BASE 컴포넌트의 검색 결과
        - MODEL 컴포넌트가 있으면: LLM 응답 텍스트 (response)
        - MODEL 컴포넌트가 없고 KNOWLEDGE_BASE만 있으면: 검색 결과 문자열 (search_result)
        - 상세 정보는 results 배열의 각 컴포넌트 결과에서 확인 가능

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

    ## Errors
    - **400**: 잘못된 요청 (RAG 워크플로우가 아님, 필수 파라미터 누락 등)
    - **401**: 인증되지 않은 사용자
    - **404**: 워크플로우를 찾을 수 없음
    - **503**: 모델 서비스가 준비되지 않음
    - **500**: 서버 내부 오류
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
    - **workflow_id** (str): 테스트할 워크플로우 UUID

    ## Request Body (Form Data)
    - **image** (file, required): 이미지 파일 (ODM 추론용)
        - 지원 형식: JPEG, PNG, GIF, WebP
        - Base64로 인코딩되어 서버로 전송

    ## Response (WorkflowTestResponse)
    - **workflow_id** (str): 워크플로우 UUID
    - **execution_order** (List[str]): 실행된 컴포넌트 ID 순서 (워크플로우 실행 순서)
    - **results** (List[ComponentTestResult]): 각 컴포넌트 실행 결과 목록
        - 각 항목은 다음 중 하나의 타입:

        **ModelComponentTestResult** (ODM 모델 컴포넌트인 경우):
        - **component_id** (str): 컴포넌트 UUID
        - **component_name** (str): 컴포넌트 이름
        - **component_type** (str): "MODEL"
        - **model_type** (str): "ODM"
        - **result** (ModelODMTestResult): ODM 추론 결과
            - **predictions** (List[dict]): 추론 결과 목록
                - 각 항목은 다음 필드를 포함:
                    - **score** (float): 객체 감지 신뢰도 점수 (0.0 ~ 1.0)
                    - **label** (str): 감지된 객체의 레이블 (예: "person", "laptop")
                    - **box** (List[float]): 바운딩 박스 좌표 [x1, y1, x2, y2]
            - **image_info** (dict, optional): 이미지 메타데이터
                - **original_size** (dict): 원본 이미지 크기
                - **model_input_size** (dict): 모델 입력 크기

        **ComponentTestErrorResult** (오류 발생 시):
        - **component_id** (str): 컴포넌트 UUID
        - **component_name** (str): 컴포넌트 이름
        - **component_type** (str): "MODEL"
        - **model_type** (str, optional): "ODM" (오류 발생 시 null 가능)
        - **error** (str): 오류 메시지

    - **final_result** (str, optional): 최종 결과 이미지 (base64 인코딩)
        - 입력 이미지에 마지막 ODM MODEL 컴포넌트의 predictions를 이용해 bbox와 label을 그린 이미지
        - base64로 인코딩된 JPEG 이미지 문자열
        - predictions가 없거나 에러 발생 시 원본 이미지를 base64로 인코딩하여 반환
        - 상세 정보 (predictions, image_info 등)는 results 배열의 각 컴포넌트 결과에서 확인 가능

    ## Notes
    - 워크플로우는 배포되어 있어야 함 (ACTIVE 상태)
    - 워크플로우에 최소 하나의 ODM MODEL 컴포넌트가 있어야 함
    - KNOWLEDGE_BASE 컴포넌트는 포함될 수 없음 (ML 워크플로우는 ODM만 지원)
    - 각 컴포넌트의 실행 결과는 results 배열에 순서대로 포함됨
    - final_result는 입력 이미지에 bbox와 label이 그려진 이미지를 base64로 인코딩한 문자열
    - bbox는 빨간색으로, label은 빨간 배경에 흰색 텍스트로 표시됨
    - 상세 정보 (predictions, image_info 등)는 results 배열의 각 컴포넌트 결과에서 확인 가능
    - 모든 추론 요청은 ServiceMonitoring 테이블에 자동 기록됨 (서비스와 연결된 경우)

    ## Errors
    - **400**: 잘못된 요청 (ML 워크플로우가 아님, 필수 파라미터 누락 등)
    - **401**: 인증되지 않은 사용자
    - **404**: 워크플로우를 찾을 수 없음
    - **503**: 모델 서비스가 준비되지 않음
    - **500**: 서버 내부 오류
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

# ===== Workflow 모델 추론 (Deprecated) =====

@router.post(
    "/{surro_workflow_id}/models/{component_id}/inference",
    deprecated=True,
)
async def inference_workflow_model(
        surro_workflow_id: str,
        component_id: str,
        image: Optional[UploadFile] = File(None),
        text: Optional[str] = Form(None),
        search_text: Optional[str] = Form(None),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    배포된 모델에 추론 요청 (Deprecated)

    ⚠️ 이 API는 deprecated 되었습니다. 대신 다음 API를 사용하세요:
    - RAG 워크플로우: `POST /api/v1/workflows/{workflow_id}/test/rag`
    - ML 워크플로우: `POST /api/v1/workflows/{workflow_id}/test/ml`

    워크플로우에서 배포된 특정 모델 컴포넌트에 추론을 수행합니다.
    - KServe 모델: KServe V2 프로토콜을 사용하며, Object Detection 모델을 지원합니다.
    - Ollama 모델: Ollama 채팅 API(`/api/chat`)를 사용하며, LLM 모델을 지원합니다.

    게이트웨이는 호환성 유지를 위해 MLOps로 요청을 그대로 전달(프록시)합니다.
    신규 연동에서는 위의 test API를 사용하세요.

    ## Path Parameters
    - **workflow_id** (str): 워크플로우 UUID
    - **component_id** (str): 컴포넌트 UUID (WorkflowComponent.id)
        - 컴포넌트 ID 조회 방법:
          1. 워크플로우 상세 조회: `GET /api/v1/workflows/{workflow_id}`
             - 응답의 `components` 배열에서 `id` 필드 확인
             - `type`이 "MODEL"인 컴포넌트의 `id` 사용
          2. 배포된 모델 목록 조회: `GET /api/v1/workflows/{workflow_id}/models`
             - 응답의 `deployed_models` 배열에서 `component_id` 필드 확인
             - 배포된 모델만 조회 가능 (DEPLOYED 상태)

    ## Request Body (Form Data)
    - **image** (file, optional): 분석할 이미지 파일
        - KServe 모델인 경우 필수
        - Ollama 모델인 경우 선택 (텍스트와 함께 사용 가능)
        - 지원 형식: JPEG, PNG, GIF, WebP
        - Base64로 인코딩되어 서버로 전송
    - **text** (str, optional): 텍스트 입력
        - Ollama 모델인 경우 필수 (image가 없는 경우)
        - KServe 모델인 경우 사용하지 않음
    - **search_text** (str, optional): Knowledge Base 검색 결과 텍스트
        - Knowledge Base 컴포넌트에서 검색된 결과를 전달하는 파라미터
        - Ollama 모델인 경우에만 사용됨
        - prompt_id가 설정된 경우: prompt의 context 변수에 자동 치환
        - prompt_id가 없는 경우: [참고자료] 태그와 함께 system 메시지로 추가

    ## Response (통일된 형식)
    - **workflow_id** (str): 워크플로우 UUID
    - **component_id** (str): 컴포넌트 UUID
    - **model_info** (dict): 모델 정보
        - component_id (str): 컴포넌트 ID
        - service_name (str): 서비스 이름
        - sanitized_model_name (str): 정제된 모델 이름 (DNS 규칙 준수)
        - model_id (int, optional): 모델 ID
        - original_model_name (str, optional): 원본 모델 이름
        - model_type (str, optional): 모델 타입 (예: "ODM", "LLM")
        - model_format (str, optional): 모델 포맷 (예: "pytorch", "gguf")
    - **result** (dict): 추론 결과
        - **model_type** (str): 모델 타입 ("KServe" 또는 "Ollama")
        - KServe 모델인 경우:
            - **predictions** (List[dict]): 추론 결과 목록
                - 각 항목은 다음 필드를 포함:
                    - **score** (float): 객체 감지 신뢰도 점수 (0.0 ~ 1.0)
                    - **label** (str): 감지된 객체의 레이블 (예: "person", "laptop")
                    - **box** (List[float]): 바운딩 박스 좌표 [x1, y1, x2, y2]
            - **image_info** (dict, optional): 이미지 메타데이터
                - **original_size** (dict): 원본 이미지 크기
                - **model_input_size** (dict): 모델 입력 크기
        - Ollama 모델인 경우:
            - **response** (str): LLM 응답 텍스트
            - **full_response** (dict, optional): Ollama API 전체 응답
    - **raw_response** (dict, optional): 원본 응답 (예상치 못한 형식인 경우에만 포함)

    ## Monitoring
    - 모든 추론 요청은 ServiceMonitoring 테이블에 자동 기록
    - 응답 시간, 성공/실패 여부, 사용자 정보 포함
    - 서비스와 연결된 경우만 모니터링 데이터 저장

    ## Notes
    ### KServe 모델
    - Istio Gateway를 통해 KServe InferenceService에 접근
    - V2 프로토콜 엔드포인트: `/v2/models/{model_name}/infer`
    - Host 헤더로 Istio 라우팅 제어

    ### Ollama 모델
    - internal_url을 통해 Ollama 서비스에 직접 접근 (예: `http://localhost:11434`)
    - 채팅 API 엔드포인트: `/api/chat`
    - model 필드에 repo_id 사용 (예: "gemma3", "ahmgam/medllama3-v20")
    - 이미지는 base64로 인코딩되어 메시지에 포함됨

    ## Errors
    - **400**: 잘못된 요청
        - Ollama 모델인 경우: text 인자가 없으면 에러
        - KServe 모델인 경우: image 인자가 없으면 에러
        - 잘못된 이미지 파일
    - **401**: 인증되지 않은 사용자
    - **404**: 워크플로우나 컴포넌트를 찾을 수 없음
    - **503**: 모델 서비스가 준비되지 않음
    - **504**: 추론 요청 타임아웃
    """
    existing_workflow = workflow_crud.get_workflow_by_surro_id(
        db=db,
        surro_workflow_id=surro_workflow_id
    )
    if not existing_workflow:
        raise HTTPException(status_code=404, detail="Workflow not found")

    user_info = {
        'member_id': current_user.member_id,
        'role': current_user.role,
        'name': current_user.name
    }

    return await workflow_service.inference_workflow_model(
        workflow_id=surro_workflow_id,
        component_id=component_id,
        image=image,
        text=text,
        search_text=search_text,
        user_info=user_info,
    )


# ===== Workflow 상태 및 모델 조회 =====

@router.get("/{surro_workflow_id}/models")
async def get_workflow_models(
        surro_workflow_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user)
):
    """
    워크플로우에 배포된 모델 목록 조회

    워크플로우에서 배포된 모든 ML 모델의 상세 정보를 조회합니다.
    KServe InferenceService로 배포된 모델들의 엔드포인트와 상태를 포함합니다.

    ## Path Parameters
    - **workflow_id** (str): 조회할 워크플로우 UUID

    ## Response
    - **workflow_id** (str): 워크플로우 UUID
    - **backend_api_url** (str): 추론 API URL (첫 번째 모델 기준)
        - 형식: `{gateway_url}/v2/models/{model_name}/infer`
    - **deployed_models** (List[dict]): 배포된 모델 목록
        - workflow_id (str): 소속 워크플로우 ID
        - component_id (str): 컴포넌트 ID
        - component_name (str): 컴포넌트 이름
        - model_id (int): 모델 ID
        - model_name (str): 원본 모델 이름
        - sanitized_model_name (str): DNS 규칙에 맞게 변환된 모델 이름
        - service_name (str): KServe 서비스 이름
        - service_hostname (str): KServe 서비스 호스트명
        - status (str): 배포 상태
            - "PENDING": 배포 대기중
            - "DEPLOYED": 배포 완료
            - "FAILED": 배포 실패
            - "DELETED": 삭제됨
        - internal_url (str): 내부 접근 URL
        - gateway_url (str): 외부 게이트웨이 URL
        - deployed_at (datetime): 배포 시각
        - deleted_at (datetime): 삭제 시각 (삭제된 경우)
        - error_message (str): 오류 메시지 (실패 시)
        - created_at (datetime): 레코드 생성 시각
        - updated_at (datetime): 레코드 업데이트 시각
    - **total** (int): 배포된 모델 총 개수

    ## Notes
    - backend_api_url은 첫 번째 배포된 모델 기준으로 생성
    - 각 모델마다 고유한 service_name과 hostname을 가짐
    - 배포 상태가 DEPLOYED인 모델만 추론 가능

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 워크플로우를 찾을 수 없음
    - **500**: 서버 내부 오류
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

    배포된 KServe InferenceService들을 정리합니다.
    워크플로우 자체는 유지하면서 배포된 리소스만 제거합니다.

    ## Path Parameters
    - **workflow_id** (str): 정리할 워크플로우 UUID

    ## Response (202 Accepted)
    - **message** (str): 상태 메시지 "Cleanup started"
    - **workflow_id** (str): 워크플로우 UUID
    - **cleanup_run_id** (str): 정리 파이프라인 실행 ID
    - **status** (str): 현재 상태 "cleanup_in_progress"
    - **next_step** (str): 다음 단계 API 안내
        - 형식: "Call /workflows/{workflow_id}/finalize-cleanup to check completion"

    ## Use Cases
    - 비용 절감을 위해 배포된 리소스 정리
    - 오류 발생 후 재배포 준비
    - 워크플로우 구조 변경 전 리소스 정리

    ## Process
    1. KServe InferenceService 삭제 파이프라인 시작
    2. cleanup_run_id 반환
    3. `finalize-cleanup` API로 완료 확인
    4. 워크플로우 상태를 DRAFT로 변경 (재실행 가능)

    ## Notes
    - 워크플로우는 삭제되지 않고 리소스만 정리
    - 비동기 프로세스 (202 Accepted)
    - 정리 후 워크플로우 재실행 가능
    - 게이트웨이 권한 검사: admin 이거나 해당 워크플로우의 `created_by` 사용자만 정리 가능

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **403**: 권한 없음
    - **404**: 워크플로우를 찾을 수 없음
    - **500**: 정리 파이프라인 시작 실패
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

    Kubernetes 클러스터를 직접 조회하여 리소스가 실제로 삭제되었는지 확인하고,
    확인된 경우 워크플로우 상태를 업데이트합니다.
    워크플로우는 삭제되지 않고 리소스만 정리되며, 정리 후 재실행이 가능합니다.

    ## Path Parameters
    - **workflow_id** (str): 정리할 워크플로우 UUID
        - 워크플로우 목록 조회 API(`/workflows`)에서 확인 가능

    ## Query Parameters
    - **run_id** (str, required): Kubeflow Pipeline cleanup run ID
        - cleanup API에서 반환된 cleanup_run_id 사용
        - 형식: Kubeflow Pipeline 실행 UUID

    ## Response
    - **workflow_id** (str): 워크플로우 UUID
    - **status** (str): 정리 상태
        - "completed": 정리 완료
            - Kubernetes 리소스가 실제로 삭제되어 확인됨
            - 워크플로우 상태가 업데이트됨 (ERROR → DRAFT)
        - "in_progress": 아직 진행중
            - Kubernetes에 리소스가 아직 존재함
            - 완료될 때까지 대기 후 재호출 필요
        - "failed": 정리 실패
            - Kubernetes 리소스 확인 중 오류 발생
            - error_message에 상세 오류 정보 포함
    - **workflow_updated** (bool): 워크플로우 상태 업데이트 여부
        - true: 워크플로우 상태가 성공적으로 업데이트됨
            - ERROR 상태였던 경우 DRAFT로 변경됨
            - 재실행 가능한 상태로 변경됨
        - false: 워크플로우 상태가 업데이트되지 않음
            - 리소스가 아직 삭제되지 않았거나 실패한 경우
            - 또는 워크플로우가 이미 DRAFT 상태인 경우
    - **message** (str): 상태 메시지
        - 정리 완료: "Cleanup completed and workflow state updated"
        - 진행중: "Resources still exist in Kubernetes, waiting for cleanup"
        - 실패: "Failed to check Kubernetes resources: {error}"

    ## Process
    1. 워크플로우 존재 여부 확인
    2. Kubernetes 클러스터에서 리소스 직접 조회
       - InferenceService 조회
       - Ollama Deployment/Service 조회
    3. 리소스가 모두 삭제된 경우:
       - 워크플로우 상태가 ERROR인 경우 DRAFT로 변경
       - KServe 배포 데이터(kserve_deployments) 삭제
       - 재실행 가능한 상태로 업데이트
    4. 리소스가 아직 존재하는 경우: 진행중 상태 반환 (재호출 필요)
    5. 확인 중 오류 발생: 실패 상태 반환

    ## Notes
    - 워크플로우는 삭제되지 않고 리소스만 정리됨
    - 정리 완료 후 워크플로우를 재실행할 수 있음
    - Kubernetes 리소스 확인은 즉시 수행됨
    - 리소스가 아직 존재하면 재호출하여 완료 확인 필요
    - ERROR 상태의 워크플로우는 정리 완료 시 DRAFT로 변경됨
    - 이미 DRAFT 상태인 워크플로우는 상태 변경 없음
    - cleanup API 호출 후 이 API를 호출하여 완료 확인 필요

    ## Errors
    - **401**: 인증되지 않은 사용자
    - **404**: 워크플로우를 찾을 수 없음
        - workflow_id가 존재하지 않거나 삭제된 경우
    - **500**: 정리 처리 중 오류 발생
        - Kubernetes 리소스 확인 실패 또는 워크플로우 상태 업데이트 실패
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
