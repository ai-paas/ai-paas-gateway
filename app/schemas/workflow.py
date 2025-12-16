from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime


# ===== 외부 API 응답 스키마 =====

class ModelProviderSchema(BaseModel):
    """모델 제공자 정보"""
    id: int
    name: str
    description: str


class ModelTypeSchema(BaseModel):
    """모델 타입 정보"""
    id: int
    name: str
    description: str


class ModelFormatSchema(BaseModel):
    """모델 포맷 정보"""
    id: int
    name: str
    description: str


class ModelRegistrySchema(BaseModel):
    """모델 레지스트리 정보"""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    id: int
    artifact_path: str
    uri: str
    run_id: Optional[str] = None
    reference_model_id: int


class ModelDetailSchema(BaseModel):
    """모델 상세 정보"""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None
    id: int
    name: str
    description: Optional[str] = None
    repo_id: Optional[str] = None
    provider_info: ModelProviderSchema
    type_info: ModelTypeSchema
    format_info: ModelFormatSchema
    parent_model_id: Optional[int] = None
    registry: ModelRegistrySchema
    task: Optional[str] = None
    parameter: Optional[str] = None
    sample_code: Optional[str] = None


class ExternalComponentSchema(BaseModel):
    """외부 API 컴포넌트 스키마"""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None
    id: str
    workflow_id: str
    name: str
    type: str  # START, END, MODEL, KNOWLEDGE_BASE
    model_id: Optional[int] = None
    model: Optional[ModelDetailSchema] = None
    knowledge_base_id: Optional[int] = None
    prompt_id: Optional[int] = None


class ExternalConnectionSchema(BaseModel):
    """외부 API 연결 스키마"""
    id: str
    workflow_id: str
    source_component_id: str
    target_component_id: str
    source_component: ExternalComponentSchema
    target_component: ExternalComponentSchema
    created_at: Optional[datetime] = None


class ExternalWorkflowDetailResponse(BaseModel):
    """외부 API에서 반환되는 워크플로우 상세 응답"""
    id: str  # UUID
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    status: str  # DRAFT, ACTIVE, ERROR
    service_id: Optional[str] = None
    creator_id: int
    is_template: bool
    template_id: Optional[str] = None
    kubeflow_run_id: Optional[str] = None
    components: List[ExternalComponentSchema] = []
    component_connections: List[ExternalConnectionSchema] = []
    service_name: Optional[str] = None
    template_name: Optional[str] = None
    public_url: Optional[str] = None
    backend_api_url: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    deleted_by: Optional[str] = None


class ExternalWorkflowBriefResponse(BaseModel):
    """외부 API에서 반환되는 워크플로우 간략 응답 (목록용)"""
    id: str  # UUID
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    status: str
    service_id: Optional[str] = None
    creator_id: int
    is_template: bool
    template_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ===== 워크플로우 생성/수정 요청 =====

class ComponentCreateRequest(BaseModel):
    """컴포넌트 생성 요청"""
    name: str
    type: str  # START, END, MODEL, KNOWLEDGE_BASE
    model_id: Optional[int] = None
    knowledge_base_id: Optional[int] = None
    prompt_id: Optional[int] = None


class ConnectionCreateRequest(BaseModel):
    """연결 생성 요청"""
    source_component_type: str
    target_component_type: str


class WorkflowDefinition(BaseModel):
    """워크플로우 정의"""
    components: List[ComponentCreateRequest]
    connections: List[ConnectionCreateRequest]


class WorkflowCreateRequest(BaseModel):
    """워크플로우 생성 요청"""
    name: str = Field(..., description="워크플로우 이름")
    description: Optional[str] = Field(None, description="워크플로우 설명")
    category: Optional[str] = Field(None, description="카테고리")
    service_id: Optional[str] = Field(None, description="서비스 ID")
    workflow_definition: Optional[WorkflowDefinition] = Field(None, description="워크플로우 정의")


class WorkflowUpdateRequest(BaseModel):
    """워크플로우 수정 요청"""
    name: Optional[str] = Field(None, description="수정할 이름")
    description: Optional[str] = Field(None, description="수정할 설명")
    category: Optional[str] = Field(None, description="수정할 카테고리")
    status: Optional[str] = Field(None, description="수정할 상태")
    service_id: Optional[str] = Field(None, description="수정할 서비스 ID")
    workflow_definition: Optional[WorkflowDefinition] = Field(None, description="워크플로우 정의")


# ===== 우리 DB 응답 스키마 =====

class WorkflowResponse(BaseModel):
    """우리 DB 워크플로우 응답 (메타정보 + 외부 API 핵심 데이터)"""
    # DB 메타 정보
    id: int  # 우리 DB의 PK
    surro_workflow_id: str  # 외부 API의 ID (UUID)
    created_at: datetime
    updated_at: datetime
    created_by: str

    # 외부 API 핵심 데이터
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    status: str
    service_id: Optional[str] = None
    is_template: bool
    template_id: Optional[str] = None


class WorkflowDetailResponse(BaseModel):
    """워크플로우 상세 응답 (전체 정보)"""
    # DB 메타 정보 (필수)
    id: int
    surro_workflow_id: str
    created_at: datetime
    updated_at: datetime
    created_by: str

    # 외부 API 전체 데이터
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    status: str
    service_id: Optional[str] = None
    service_name: Optional[str] = None
    creator_id: int
    is_template: bool
    template_id: Optional[str] = None
    template_name: Optional[str] = None
    kubeflow_run_id: Optional[str] = None
    public_url: Optional[str] = None
    backend_api_url: Optional[str] = None
    components: List[ExternalComponentSchema] = []
    component_connections: List[ExternalConnectionSchema] = []


class WorkflowListResponse(BaseModel):
    """워크플로우 목록 응답"""
    data: List[WorkflowResponse]
    total: int
    page: Optional[int] = None
    size: Optional[int] = None


# ===== 워크플로우 실행 관련 =====

class WorkflowExecuteRequest(BaseModel):
    """워크플로우 실행 요청"""
    parameters: Optional[Dict[str, Any]] = Field(
        default_factory=dict,
        description="실행 파라미터 (커스텀 설정 값들을 전달)",
        example={"gpu_enabled": True, "replicas": 2}
    )


class WorkflowExecuteResponse(BaseModel):
    """워크플로우 실행 응답"""
    workflow_id: str = Field(..., description="실행된 워크플로우 UUID")
    kubeflow_run_id: str = Field(..., description="Kubeflow 파이프라인 실행 ID")
    status: str = Field(..., description="실행 상태 (PENDING/RUNNING/SUCCEEDED/FAILED)")
    message: str = Field(..., description="상태 메시지")


# ===== 워크플로우 테스트 관련 =====

class WorkflowTestRAGRequest(BaseModel):
    """RAG 워크플로우 테스트 요청"""
    text: str = Field(..., description="검색 쿼리 및 LLM 입력 텍스트")


class ComponentTestResult(BaseModel):
    """컴포넌트 테스트 결과"""
    component_id: str
    component_name: str
    component_type: str
    model_type: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class WorkflowTestResponse(BaseModel):
    """워크플로우 테스트 응답"""
    workflow_id: str
    execution_order: List[str]
    results: List[ComponentTestResult]
    final_result: Optional[str] = None


# ===== Template 관련 =====

class TemplateCreateRequest(BaseModel):
    """템플릿 생성 요청"""
    name: str = Field(..., description="템플릿 이름")
    description: Optional[str] = Field(None, description="템플릿 설명")
    category: Optional[str] = Field(None, description="카테고리")
    workflow_definition: Optional[WorkflowDefinition] = Field(None, description="워크플로우 정의")


class TemplateUpdateRequest(BaseModel):
    """템플릿 수정 요청"""
    name: Optional[str] = Field(None, description="수정할 이름")
    description: Optional[str] = Field(None, description="수정할 설명")
    category: Optional[str] = Field(None, description="수정할 카테고리")
    status: Optional[str] = Field(None, description="수정할 상태")
    workflow_definition: Optional[WorkflowDefinition] = Field(None, description="워크플로우 정의")


class TemplateResponse(BaseModel):
    """템플릿 응답"""
    id: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    status: str
    creator_id: int
    is_template: bool
    usage_count: int
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class TemplateListResponse(BaseModel):
    """템플릿 목록 응답"""
    data: List[TemplateResponse]
    total: int
    page: Optional[int] = None
    size: Optional[int] = None


# ===== Component Types =====

class ComponentTypeSchema(BaseModel):
    """컴포넌트 타입 스키마"""
    type: str
    component_id: str
    name: str
    description: str


class ComponentTypeListResponse(BaseModel):
    """컴포넌트 타입 목록 응답"""
    data: List[ComponentTypeSchema]