from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated, Any, Dict, List, Literal, Optional, Union


class AnyCloudResponse(BaseModel):
    """Any Cloud API 단일 조회 응답 래퍼"""
    model_config = ConfigDict(extra="allow")


class VmClusterSpec(BaseModel):
    """VM 프로비저닝 spec"""
    model_config = ConfigDict(extra="allow")
    provider: str = Field(
        ...,
        description='CSP — "aws" | "gcp" | "azure" | "alibaba" | "oci" | "digitalocean" | "openstack" | "proxmox"',
        examples=["aws"]
    )
    region: str = Field(..., description="리전", examples=["ap-northeast-2"])
    environment: Optional[str] = Field(None, description='환경 ("dev" | "stage" | "prod")', examples=["dev"])
    credentialId: Optional[str] = Field(
        None,
        description="사전 등록된 CSP 자격증명 ID",
        examples=["cred-aws-001"]
    )
    config: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="provider 설정 (값은 모두 문자열)",
        examples=[{"workerCount": "3", "instanceType": "t3.medium"}]
    )
    hasGpuNodes: Optional[bool] = Field(False, description="GPU 노드 포함 여부", examples=[False])
    useSpot: Optional[bool] = Field(
        False,
        description="Spot/preemptible 인스턴스 사용 (AWS/Azure/GCP)",
        examples=[False]
    )
    image: Optional[str] = Field(
        None,
        description="OS 이미지 (미지정 시 provider 기본값)",
        examples=[None]
    )


class RegisteredClusterSpec(BaseModel):
    """외부 클러스터 등록 spec"""
    model_config = ConfigDict(extra="allow")
    provider: str = Field(..., description="CSP", examples=["AWS"])
    clusterType: Optional[str] = Field(
        None,
        description='클러스터 타입 — "EKS" | "GKE" | "AKS" | "Self-managed" ...',
        examples=["EKS"]
    )
    description: Optional[str] = Field(None, description="설명", examples=["Production EKS cluster in Seoul"])
    hasGpuNodes: Optional[bool] = Field(False, description="GPU 노드 포함 여부", examples=[False])
    addons: Optional[List[Dict[str, Any]]] = Field(
        None,
        description="등록 직후 자동 설치할 애드온 목록",
        examples=[None]
    )


class VmCreateRequest(BaseModel):
    """VM source 클러스터 생성 요청"""
    source: Literal["vm"] = Field("vm", description='고정값 "vm"')
    clusterName: str = Field(
        ...,
        description="클러스터 이름 (RFC 1123 label)",
        examples=["demo-aws-01"]
    )
    spec: VmClusterSpec = Field(..., description="VM 프로비저닝 spec")


class RegisteredCreateRequest(BaseModel):
    """외부 클러스터 등록 요청"""
    source: Literal["registered"] = Field("registered", description='고정값 "registered"')
    clusterName: str = Field(
        ...,
        description="클러스터 이름 (RFC 1123 label)",
        examples=["imported-aws-01"]
    )
    spec: RegisteredClusterSpec = Field(..., description="외부 등록 spec")


# source 값에 따라 VM/등록 요청 스키마로 분기
ClusterCreateRequest = Annotated[
    Union[VmCreateRequest, RegisteredCreateRequest],
    Field(discriminator="source")
]


class HelmRepoCreateRequest(BaseModel):
    """헬름 저장소 등록 요청"""
    model_config = ConfigDict(extra="allow")
    name: str = Field(..., description="저장소 이름 (고유)", examples=["prometheus-community"])
    url: str = Field(
        ...,
        description="저장소 URL",
        examples=["https://prometheus-community.github.io/helm-charts"]
    )
    username: Optional[str] = Field(None, description="저장소 인증 사용자 ID")
    password: Optional[str] = Field(None, description="저장소 인증 비밀번호")
    insecureSkipTLSVerify: Optional[bool] = Field(
        False,
        description="TLS 검증 우회",
        examples=[False]
    )
    caFile: Optional[str] = Field(None, description="CA 인증서 (PEM)")
    source: Optional[str] = Field(
        "EXTERNAL",
        description='저장소 종류 — "INTERNAL" | "EXTERNAL"',
        examples=["EXTERNAL"]
    )
    tags: Optional[str] = Field(
        None,
        description="태그 (쉼표 구분)",
        examples=["monitoring,default"]
    )


class ClusterPatchSpec(BaseModel):
    """클러스터 수정 가능한 spec 항목"""
    model_config = ConfigDict(extra="allow")
    workerCount: Optional[int] = Field(
        None,
        ge=1,
        le=50,
        description="워커 노드 수 (1..50, VM source 만 지원)",
        examples=[5]
    )


class ClusterUpdateRequest(BaseModel):
    """클러스터 수정 요청"""
    spec: ClusterPatchSpec = Field(..., description="변경할 spec 필드")


class AnyCloudPagedResponse(BaseModel):
    """Any Cloud API 페이징 응답 래퍼"""
    data: List[Any] = Field(..., description="응답 데이터 목록")
    total: int = Field(..., description="전체 데이터 개수")
    page: int = Field(..., description="현재 페이지 번호")
    size: int = Field(..., description="페이지 크기")
    total_pages: int = Field(..., description="전체 페이지 수")
    nextPageToken: Optional[str] = Field(default=None, description="다음 페이지 토큰")

    @classmethod
    def create(cls, data: List[Any], total: int, page: int, size: int, next_page_token: Optional[str] = None):
        """페이징 응답 생성 헬퍼"""
        total_pages = (total + size - 1) // size if size > 0 else 0
        return cls(
            data=data,
            total=total,
            page=page,
            size=size,
            total_pages=total_pages,
            nextPageToken=next_page_token
        )


class CredentialCreateRequest(BaseModel):
    """CSP 자격증명 등록 요청

    sourceType=MANUAL 시 credentials 에 키/값 직접 입력, ENV 시 backend 환경변수 사용
    """
    model_config = ConfigDict(extra="allow")
    provider: str = Field(..., description="CSP 식별자 (대문자)", examples=["AWS"])
    name: str = Field(..., description="자격증명 이름", examples=["aws-dev-credential"])
    description: Optional[str] = Field(None, description="설명", examples=["AWS development account"])
    sourceType: Optional[str] = Field(
        None,
        description='저장 방식 — "MANUAL" | "ENV"',
        examples=["MANUAL"]
    )
    credentials: Optional[Dict[str, str]] = Field(
        None,
        description="MANUAL 시 키/값 (provider 별 키 이름)",
        examples=[{"AWS_ACCESS_KEY_ID": "AKIA...", "AWS_SECRET_ACCESS_KEY": "***"}]
    )


class ClusterValidationRequest(BaseModel):
    """VM 클러스터 생성 사전 검증 요청 (flat 구조, VM source 전용)"""
    model_config = ConfigDict(extra="allow")
    clusterProvider: str = Field(..., description="CSP 식별자 (대문자)", examples=["AWS"])
    clusterName: str = Field(..., description="검증할 클러스터 이름 (RFC 1123 label)", examples=["demo-aws-01"])
    description: Optional[str] = Field(None, description="클러스터 설명", examples=["AWS development cluster"])
    environment: str = Field(..., description='환경 ("dev" | "stage" | "prod")', examples=["dev"])
    region: str = Field(..., description="리전", examples=["ap-northeast-2"])
    credentialId: Optional[str] = Field(None, description="사전 등록된 CSP 자격증명 ID", examples=["cred-aws-001"])
    config: Optional[Dict[str, str]] = Field(
        default_factory=dict,
        description="provider 설정 (값은 모두 문자열)",
        examples=[{"workerCount": "3", "instanceType": "t3.medium"}]
    )
    hasGpuNodes: Optional[bool] = Field(False, description="GPU 노드 포함 여부")


class AddonInstallRequest(BaseModel):
    """애드온 설치 요청

    catalogId 만 지정하면 카탈로그 기본값으로 설치, null 이면 chartName 등으로 직접 지정
    """
    model_config = ConfigDict(extra="allow")
    type: str = Field(
        ...,
        description='애드온 타입 (예: "MONITORING", "INGRESS_NGINX", "CERT_MANAGER", "GPU_EXPORTER", "VELERO")',
        examples=["MONITORING"]
    )
    catalogId: Optional[str] = Field(
        None,
        description="카탈로그 ID. null 이면 직접 지정 모드 (chartName 필수)",
        examples=["kube-prometheus-stack"]
    )
    releaseName: Optional[str] = Field(None, description="Helm 릴리즈 이름")
    namespace: Optional[str] = Field(None, description="설치 네임스페이스", examples=["monitoring"])
    chartRepo: Optional[str] = Field(None, description="Helm 저장소 별칭")
    chartName: Optional[str] = Field(None, description="차트 이름 (직접 지정 모드 필수)")
    chartVersion: Optional[str] = Field(None, description="차트 버전")
    repoUrl: Optional[str] = Field(
        None,
        description="저장소 URL 직접 지정",
        examples=["https://prometheus-community.github.io/helm-charts"]
    )
    valuesYaml: Optional[str] = Field(None, description="values 오버라이드 (JSON 또는 YAML 문자열)")
    enabled: Optional[bool] = Field(True, description="false 면 자동 설치 비활성")


class OperationProgress(BaseModel):
    """작업 진행 정보"""
    currentStep: Optional[str] = Field(None, description="현재 단계", examples=["BOOTSTRAP"])
    stepIndex: Optional[int] = Field(None, description="현재 단계 번호 (1-based)", examples=[2])
    totalSteps: Optional[int] = Field(None, description="총 단계 수", examples=[3])
    percent: Optional[int] = Field(None, description="진행률 (0..100)", examples=[66])


class OperationResponse(BaseModel):
    """작업 상태 응답"""
    id: Optional[str] = Field(None, description="작업 ID", examples=["op-7f3a8c2e1b4d"])
    type: Optional[str] = Field(
        None,
        description="작업 종류 (CREATE_CLUSTER, SCALE_CLUSTER, DELETE_CLUSTER, HELM_INSTALL 등)",
        examples=["SCALE_CLUSTER"]
    )
    resourceType: Optional[str] = Field(None, description="대상 리소스 타입", examples=["cluster"])
    resourceId: Optional[str] = Field(None, description="대상 리소스 식별자", examples=["demo-aws-01"])
    state: Optional[str] = Field(
        None,
        description="상태 — PENDING / RUNNING / SUCCEEDED / FAILED / CANCELLED",
        examples=["RUNNING"]
    )
    progress: Optional[OperationProgress] = Field(None, description="진행 정보")
    errorMessage: Optional[str] = Field(None, description="에러 메시지 (실패 시)")
    startedAt: Optional[str] = Field(None, description="시작 시각")
    endedAt: Optional[str] = Field(None, description="종료 시각")
    createdAt: Optional[str] = Field(None, description="생성 시각")


class ClusterWorkflowProgress(BaseModel):
    """VM 클러스터 workflow 단계 진행"""
    currentStep: Optional[str] = Field(
        None,
        description='현재 단계 — "PROVISION" | "BOOTSTRAP" | "VERIFY" | "DESTROY"',
        examples=["PROVISION"]
    )
    lastSuccessfulStep: Optional[str] = Field(None, description="마지막 완료 단계", examples=["PROVISION"])
    percent: Optional[int] = Field(
        None,
        description="전체 진행률 (0~100)",
        examples=[33]
    )
    stepStartedAt: Optional[str] = Field(None, description="현재 단계 시작 시각")
    retryCount: Optional[int] = Field(None, description="재시도 횟수")


class UnifiedClusterResponse(BaseModel):
    """클러스터 통합 응답"""
    model_config = ConfigDict(extra="allow")
    source: Optional[str] = Field(None, description='"vm" | "registered"', examples=["vm"])
    clusterName: Optional[str] = Field(None, description="클러스터 이름", examples=["demo-aws-01"])
    provider: Optional[str] = Field(None, description="CSP", examples=["AWS"])
    region: Optional[str] = Field(None, description="리전", examples=["ap-northeast-2"])
    environment: Optional[str] = Field(None, description="환경", examples=["dev"])
    status: Optional[str] = Field(
        None,
        description="상태 — PROVISIONING / READY / FAILED / BLOCKED / DELETING / DELETED / IMPORTED",
        examples=["READY"]
    )
    workerCount: Optional[int] = Field(None, description="워커 수 (VM source 만)")
    createdAt: Optional[str] = Field(None, description="생성 시각")
    readyAt: Optional[str] = Field(None, description="준비 완료 시각")
    lastError: Optional[str] = Field(None, description="마지막 에러")
    hasGpuNodes: Optional[bool] = Field(None, description="GPU 노드 포함 여부")
    agentConnectivity: Optional[str] = Field(
        None,
        description="에이전트 연결 상태 — CONNECTED / DEGRADED / DISCONNECTED / NOT_REGISTERED",
        examples=["CONNECTED"]
    )
    agentHeartbeatSecondsAgo: Optional[int] = Field(None, description="마지막 heartbeat 으로부터 경과 초")
    agentHealthSummary: Optional[str] = Field(None, description="에이전트 상태 요약")
    workflowProgress: Optional[ClusterWorkflowProgress] = Field(
        None,
        description="VM workflow 진행 (VM source 만)"
    )


class HelmReleaseInstallRequest(BaseModel):
    """Helm 릴리즈 설치 요청 (JSON body)

    values 와 valuesYaml 은 동시 지정 불가
    """
    model_config = ConfigDict(extra="allow")
    releaseName: str = Field(..., description="릴리즈 이름", examples=["ingress"])
    chart: str = Field(
        ...,
        description='차트 참조 — "<repo>/<chart>" 형식',
        examples=["bitnami/nginx"]
    )
    version: Optional[str] = Field(None, description="차트 버전 (미지정 시 최신)", examples=["15.3.0"])
    namespace: Optional[str] = Field("default", description="설치 네임스페이스", examples=["web"])
    values: Optional[Dict[str, Any]] = Field(
        None,
        description="values 객체 (JSON)",
        examples=[{"replicaCount": 3, "image": {"repository": "nginx"}}]
    )
    valuesYaml: Optional[str] = Field(
        None,
        description="values.yaml 문자열 (최대 1MB)"
    )
