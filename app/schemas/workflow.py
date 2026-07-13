from datetime import datetime
from typing import Optional, List, Any, Dict, Literal, Union

from pydantic import BaseModel, Field


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
    visibility: Optional[str] = None  # upstream inline 컴포넌트의 visibility 보존
    recommended_hparams: Dict[str, str] = Field(default_factory=dict)


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
    type: Literal["START", "END", "MODEL", "KNOWLEDGE_BASE"]
    description: Optional[str] = None
    model_id: Optional[int] = None
    model: Optional[ModelDetailSchema] = None
    knowledge_base_id: Optional[int] = None
    prompt_id: Optional[int] = None
    config: Optional[Dict[str, Any]] = None
    x: Optional[int] = Field(None, description="프론트 캔버스 x 좌표 (음수 허용)")
    y: Optional[int] = Field(None, description="프론트 캔버스 y 좌표 (음수 허용)")


class UserBriefSchema(BaseModel):
    """External API user response without password."""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    updated_by: Optional[str] = None
    id: int
    username: str
    name: str


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
    creator: Optional[UserBriefSchema] = None
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
    """컴포넌트 생성 요청 (MLOps v2)"""
    ref_id: str = Field(..., description="프론트엔드 생성 임시 참조 ID — Connection이 이 값으로 컴포넌트를 식별")
    name: str
    type: Literal["START", "END", "MODEL", "KNOWLEDGE_BASE"]
    description: Optional[str] = None
    model_id: Optional[int] = None
    knowledge_base_id: Optional[int] = None
    prompt_id: Optional[int] = None
    config: Optional[Dict[str, Any]] = None
    x: Optional[int] = Field(None, description="프론트 캔버스 x 좌표 (음수 허용)")
    y: Optional[int] = Field(None, description="프론트 캔버스 y 좌표 (음수 허용)")


class ConnectionCreateRequest(BaseModel):
    """연결 생성 요청 (MLOps v2 — ref_id 기반)"""
    source_ref_id: str = Field(..., description="소스 컴포넌트의 ref_id")
    target_ref_id: str = Field(..., description="타겟 컴포넌트의 ref_id")


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
    status: Optional[Literal["DRAFT", "ACTIVE", "ERROR"]] = Field(None, description="수정할 상태")
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
        description="호환성 유지용 실행 파라미터. 현재 실행 처리에는 사용되지 않습니다.",
        json_schema_extra={"example": {}}
    )


class WorkflowExecuteResponse(BaseModel):
    """워크플로우 실행 응답"""
    workflow_id: str = Field(..., description="실행된 워크플로우 UUID")
    kubeflow_run_id: str = Field(..., description="Kubeflow 파이프라인 실행 ID")
    status: str = Field(..., description="실행 상태 (PENDING/RUNNING/SUCCEEDED/FAILED)")
    message: str = Field(..., description="상태 메시지")


# ===== 워크플로우 정의 검증 (MLOps v2 신규) =====

class WorkflowValidateRequest(BaseModel):
    """워크플로우 정의 검증 요청 (MLOps v2)"""
    workflow_definition: WorkflowDefinition = Field(
        ..., description="검증할 워크플로우 정의 (생성 전 사전 검증용)"
    )


class ValidationCheckResponse(BaseModel):
    """검증 규칙 결과 한 항목"""
    rule: str = Field(..., description="검증 규칙 식별자")
    passed: bool = Field(..., description="해당 규칙 통과 여부")
    message: Optional[str] = Field(None, description="실패 시 상세 메시지")


class WorkflowValidateResponse(BaseModel):
    """워크플로우 정의 검증 응답 (MLOps v2)"""
    valid: bool = Field(..., description="모든 규칙 통과 여부")
    checks: List[ValidationCheckResponse] = Field(
        default_factory=list, description="규칙별 검증 결과 목록"
    )


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
    task: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class WorkflowTestResponse(BaseModel):
    """워크플로우 테스트 응답"""
    workflow_id: str
    execution_order: List[str]
    results: List[ComponentTestResult]
    final_result: Optional[str] = None


# ===== BFM(task 기반) 추론 요청/응답 (api-spec 2026-07-01) =====
# model_type=BFM 전용. task ↔ 엔드포인트 1:1.
# 공통 응답 봉투: {workflow_id, execution_order, results[]} (final_result 없음).

# --- 요청 ---

class WorkflowProteinClassificationTestRequest(BaseModel):
    """protein-classification(파인튜닝 ESM2 자식) 추론 요청 — TCR-Epitope 결합 이진 분류."""
    epitope: str = Field(..., description="단백질 epitope 서열")
    cdr3b: str = Field(..., description="TCR β-chain CDR3 서열")


class WorkflowFillMaskTestRequest(BaseModel):
    """fill-mask(base ESM2/ESMC · MolFormer · RNA-FM) 추론 요청."""
    sequence: str = Field(
        ..., description="마스크 토큰(`<mask>`)을 1개 이상 포함한 서열 (modality별 알파벳)"
    )
    top_k: int = Field(
        5, description="마스크 위치별 반환 top-k 후보 수 (기본 5, 권장 1–50; 범위 검증은 upstream)"
    )


class WorkflowProteinStructurePredictionTestRequest(BaseModel):
    """protein-structure-prediction(ESMFold2) 추론 요청 — 3D 구조 예측."""
    sequence: str = Field(..., description="단일 단백질 아미노산 서열")
    num_loops: int = Field(3, description="ESMFold2 recycling loop 수 (기본 3)")
    num_sampling_steps: int = Field(50, description="확산 샘플링 스텝 수 (기본 50)")


# --- 결과 세부 (task별) ---

class ProteinClassificationPrediction(BaseModel):
    """TCR-Epitope 결합 이진 분류 결과 1건."""
    label: int = Field(..., description="예측 라벨 (0 | 1)")
    score: float = Field(..., description="예측 라벨의 확률")
    probabilities: Dict[str, float] = Field(
        ..., description='클래스별 확률 {"0": p0, "1": p1}'
    )


class ModelProteinClassificationTestResult(BaseModel):
    predictions: List[ProteinClassificationPrediction]
    input_info: Optional[Dict[str, Any]] = Field(None, description="{epitope, cdr3b}")


class FillMaskTokenPrediction(BaseModel):
    """마스크 위치 후보 토큰 1건."""
    token: str = Field(..., description="후보 토큰 문자열")
    score: float = Field(..., description="후보 확률")


class FillMaskPositionPrediction(BaseModel):
    """마스크 위치별 예측 결과."""
    position: int = Field(..., description="서열 내 마스크 위치(토큰 인덱스)")
    predictions: List[FillMaskTokenPrediction] = Field(..., description="top-k 후보 목록")


class ModelFillMaskTestResult(BaseModel):
    predictions: List[FillMaskPositionPrediction]
    input_info: Optional[Dict[str, Any]] = Field(None, description="{sequence, top_k}")


class StructurePrediction(BaseModel):
    """예측된 3D 구조 1건."""
    pdb: str = Field(..., description="전원자 3D 구조 (PDB 문자열, ATOM 레코드 포함)")
    plddt_mean: Optional[float] = Field(None, description="평균 pLDDT (0–1 스케일)")
    ptm: Optional[float] = Field(None, description="pTM")
    iptm: Optional[float] = Field(None, description="ipTM (단일 사슬은 0)")


class ModelStructurePredictionTestResult(BaseModel):
    predictions: List[StructurePrediction]
    input_info: Optional[Dict[str, Any]] = Field(
        None, description="{sequence, num_loops, num_sampling_steps}"
    )


# --- 컴포넌트 결과 봉투 (task별) ---

class _BFMComponentResultBase(BaseModel):
    """성공한 BFM 컴포넌트 실행 결과 공통 필드."""
    component_id: str
    component_name: str
    component_type: str
    model_type: Literal["BFM"] = Field(..., description='모델 타입 고정값 "BFM"')


class BFMComponentErrorResult(BaseModel):
    """BFM 컴포넌트 실행 오류 결과."""
    component_id: str
    component_name: str
    component_type: str
    model_type: Optional[str] = Field(None, description="오류 발생 시 null 가능")
    error: str


class ProteinClassificationComponentResult(_BFMComponentResultBase):
    task: Literal["protein-classification"]
    result: ModelProteinClassificationTestResult


class FillMaskComponentResult(_BFMComponentResultBase):
    task: Literal["fill-mask"]
    result: ModelFillMaskTestResult


class StructurePredictionComponentResult(_BFMComponentResultBase):
    task: Literal["protein-structure-prediction"]
    result: ModelStructurePredictionTestResult


# --- 응답 봉투 (task별) ---

class WorkflowProteinClassificationTestResponse(BaseModel):
    """protein-classification 추론 응답 (BFM 전용)."""
    workflow_id: str
    execution_order: List[str]
    results: List[Union[ProteinClassificationComponentResult, BFMComponentErrorResult]]


class WorkflowFillMaskTestResponse(BaseModel):
    """fill-mask 추론 응답 (BFM 전용)."""
    workflow_id: str
    execution_order: List[str]
    results: List[Union[FillMaskComponentResult, BFMComponentErrorResult]]


class WorkflowProteinStructurePredictionTestResponse(BaseModel):
    """protein-structure-prediction 추론 응답 (BFM 전용)."""
    workflow_id: str
    execution_order: List[str]
    results: List[Union[StructurePredictionComponentResult, BFMComponentErrorResult]]


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
    status: Optional[Literal["DRAFT", "ACTIVE", "ERROR"]] = Field(None, description="수정할 상태")
    workflow_definition: Optional[WorkflowDefinition] = Field(None, description="워크플로우 정의")


class WorkflowComponentDeploymentStatusRequest(BaseModel):
    """내부 워크플로우 컴포넌트 배포 상태 업데이트 요청."""

    service_name: str
    service_hostname: str
    model_name: str
    status: str
    internal_url: Optional[str] = None
    error_message: Optional[str] = None


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
    type: Literal["START", "END", "MODEL", "KNOWLEDGE_BASE"]
    component_id: str
    name: str
    description: str


class ComponentTypeListResponse(BaseModel):
    """컴포넌트 타입 목록 응답"""
    data: List[ComponentTypeSchema]
