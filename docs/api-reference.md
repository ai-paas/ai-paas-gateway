# API 레퍼런스

> **이 파일은 `scripts/gen_api_docs.py`가 생성합니다. 직접 고치지 마세요.**
> 라우트를 바꿨으면 `python scripts/gen_api_docs.py`를 다시 돌리세요.

전체 231개 — 공개 4 · 인증 150 · 관리자 77.

권한 열의 의미는 [api-conventions.md](api-conventions.md#인증--인가)를 참조하세요.
요청/응답 스키마는 실행 중인 서버의 Swagger UI(`/docs`)가 단일 소스입니다.

## 인증 (7)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| POST | `/auth/login` | 로그인 | 공개 |
| POST | `/auth/token` | Swagger OAuth2 password flow login. `username` 필드에 member_id를 입력 | 공개 |
| POST | `/auth/refresh` | 토큰 갱신 | 공개 |
| POST | `/auth/logout` | 로그아웃 | 공개 |
| GET | `/auth/me` | 현재 로그인한 사용자 정보 조회 | 인증 |
| POST | `/auth/change-password` | 비밀번호 변경 | 인증 |
| POST | `/auth/validate-token` | 토큰 유효성 검증 | 인증 |

## 회원 (6)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| POST | `/members/` | 멤버 생성 | 관리자 |
| GET | `/members/` | 멤버 목록 조회 (검색 및 필터링 포함) | 관리자 |
| GET | `/members/{member_id}` | 멤버 기본 정보 조회 (관리자는 비활성 회원도 조회 가능) | 인증 |
| PUT | `/members/{member_id}` | member_id로 멤버 정보 수정 (본인 또는 관리자만 가능) | 인증 |
| DELETE | `/members/{member_id}` | member_id로 멤버 삭제 (하드 삭제) | 인증 |
| PATCH | `/members/{member_id}/status` | 멤버 활성/비활성 상태 변경 | 관리자 |

## 서비스 (6)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| POST | `/services/` | 새로운 서비스 생성 | 인증 |
| GET | `/services/` | 서비스 목록 조회 | 인증 |
| GET | `/services/{surro_service_id}` | 서비스 상세정보 조회 | 인증 |
| GET | `/services/{surro_service_id}/resource-usages` | 서비스 리소스 사용량 조회 | 인증 |
| PUT | `/services/{surro_service_id}` | 서비스 정보 수정 | 인증 |
| DELETE | `/services/{surro_service_id}` | 서비스 삭제 | 인증 |

## 워크플로우 (26)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/workflows/component-types` | 사용 가능한 컴포넌트 타입 조회 | 인증 |
| POST | `/workflows/validate` | 워크플로우 정의 사전 검증 | 인증 |
| POST | `/workflows/` | 새로운 워크플로우 생성 (직접 생성) | 인증 |
| GET | `/workflows/` | 워크플로우 목록 조회 (템플릿 제외) | 인증 |
| POST | `/workflows/templates` | 워크플로우 템플릿 생성 | 인증 |
| GET | `/workflows/templates` | 워크플로우 템플릿 목록 조회 | 인증 |
| GET | `/workflows/templates/{template_id}` | 워크플로우 템플릿 상세 조회 | 인증 |
| PUT | `/workflows/templates/{template_id}` | 워크플로우 템플릿 수정 | 인증 |
| DELETE | `/workflows/templates/{template_id}` | 워크플로우 템플릿 삭제 | 인증 |
| POST | `/workflows/templates/{template_id}/clone` | 템플릿으로부터 워크플로우 생성 | 인증 |
| GET | `/workflows/{surro_workflow_id}` | 워크플로우 상세정보 조회 | 인증 |
| PUT | `/workflows/{surro_workflow_id}` | 워크플로우 수정 | 인증 |
| DELETE | `/workflows/{surro_workflow_id}` | 워크플로우 삭제 시작 (2단계 프로세스) | 인증 |
| POST | `/workflows/{surro_workflow_id}/finalize-deletion` | 워크플로우 삭제 완료 처리 | 인증 |
| POST | `/workflows/{surro_workflow_id}/execute` | 워크플로우 실행 (서빙 배포 + Kubeflow 파이프라인) | 인증 |
| GET | `/workflows/{surro_workflow_id}/status` | 워크플로우 실행 상태 조회 | 인증 |
| POST | `/workflows/{surro_workflow_id}/components/{component_id}/deployment-status` | 컴포넌트의 워크플로 서빙 배포 상태를 업데이트합니다 | 관리자 |
| POST | `/workflows/{surro_workflow_id}/test/rag` | RAG 워크플로우 테스트 | 인증 |
| POST | `/workflows/{surro_workflow_id}/test/ml` | ML 워크플로우 테스트 | 인증 |
| POST | `/workflows/{surro_workflow_id}/test/protein-classification` | 단백질 분류(protein-classification) 워크플로우 테스트 | 인증 |
| POST | `/workflows/{surro_workflow_id}/test/fill-mask` | 마스크 채우기(fill-mask) 워크플로우 테스트 — **BFM 전용** | 인증 |
| POST | `/workflows/{surro_workflow_id}/test/protein-structure-prediction` | 단백질 구조 예측(protein-structure-prediction) 워크플로우 테스트 | 인증 |
| POST | `/workflows/{surro_workflow_id}/models/{component_id}/inference` | **(deprecated)** 배포된 모델에 추론 요청 — **MLOps v2에서 제거됨 (410 Gone)** | 인증 |
| GET | `/workflows/{surro_workflow_id}/models` | 워크플로우에 배포된 모델 목록 조회 | 인증 |
| POST | `/workflows/{surro_workflow_id}/cleanup` | 워크플로우 리소스 정리 시작 | 인증 |
| POST | `/workflows/{surro_workflow_id}/finalize-cleanup` | 워크플로우 정리 완료 처리 | 인증 |

## 모델 (13)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| POST | `/models` | 모델 등록 | 인증 |
| GET | `/models` | 모델 목록 조회 | 인증 |
| GET | `/models/custom-models` | 내 커스텀 모델 목록 조회 (게이트웨이 확장) | 인증 |
| GET | `/models/model-catalog` | 카탈로그 모델 목록 조회 (게이트웨이 확장) | 인증 |
| GET | `/models/providers` | 모델 제공자 조회 | 인증 |
| GET | `/models/types` | 모델 타입 조회 | 인증 |
| GET | `/models/formats` | 모델 포맷 조회 | 인증 |
| POST | `/models/auto-generate` | 사전 정의 모델 자동 등록 | 인증 |
| PUT | `/models/base-deployments/{model_id}/status` | 모델 기본 배포 상태 업데이트 (백엔드 서버 내부 전용 API) | 관리자 |
| GET | `/models/{model_id}/files/download-url` | 모델 파일 다운로드 URL 발급 | 인증 |
| GET | `/models/{model_id}/files` | 모델 저장 파일 목록 조회 | 인증 |
| GET | `/models/{model_id}` | 모델 상세정보 조회 | 인증 |
| DELETE | `/models/{model_id}` | 모델 삭제 | 인증 |

## 모델 개선 (3)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| POST | `/model-improvements` | 모델 최적화/경량화 task 생성 | 인증 |
| GET | `/model-improvements/status` | 모델 최적화/경량화 task 상태 조회 | 인증 |
| GET | `/model-improvements/task-types` | 최적화/경량화 task_type 목록 조회 | 인증 |

## 데이터셋 (7)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/datasets` | 데이터셋 목록 조회 | 인증 |
| GET | `/datasets/kinds` | 데이터셋 분류 카탈로그 조회 | 인증 |
| GET | `/datasets/{dataset_id}` | 데이터셋 상세정보 조회 | 인증 |
| PUT | `/datasets/{dataset_id}` | 데이터셋 정보 수정 | 인증 |
| DELETE | `/datasets/{dataset_id}` | 데이터셋 삭제 | 인증 |
| POST | `/datasets/validate` | 데이터셋 파일 유효성 검증 | 인증 |
| POST | `/datasets` | 데이터셋 등록 | 인증 |

## 학습 (8)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/learning` | List Learning | 인증 |
| POST | `/learning/training` | Submit Training | 인증 |
| POST | `/learning/model/registration` | Register Model | 인증 |
| GET | `/learning/{experiment_id}/status` | **(deprecated)** Get Training Status | 인증 |
| PATCH | `/learning/{experiment_id}/internal-access` | Update Learning Internal | 관리자 |
| GET | `/learning/{experiment_id}` | Get Learning | 인증 |
| PATCH | `/learning/{experiment_id}` | Update Learning | 인증 |
| DELETE | `/learning/{experiment_id}` | Delete Learning | 인증 |

## 프롬프트 (6)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/prompts/variable-types` | 프롬프트 변수 가능한 타입 목록 조회 | 인증 |
| POST | `/prompts/` | 프롬프트 생성 | 인증 |
| GET | `/prompts/` | 프롬프트 목록 조회 | 인증 |
| GET | `/prompts/{surro_prompt_id}` | 프롬프트 상세 조회 | 인증 |
| PUT | `/prompts/{surro_prompt_id}` | 프롬프트 수정 | 인증 |
| DELETE | `/prompts/{surro_prompt_id}` | 프롬프트 삭제 | 인증 |

## 지식베이스 (12)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/knowledge-bases/chunk-types` | Get Chunk Types | 인증 |
| GET | `/knowledge-bases/languages` | Get Languages | 인증 |
| GET | `/knowledge-bases/search-methods` | Get Search Methods | 인증 |
| POST | `/knowledge-bases` | Create Knowledge Base | 인증 |
| GET | `/knowledge-bases` | Get Knowledge Bases | 인증 |
| GET | `/knowledge-bases/{surro_knowledge_id}` | Get Knowledge Base | 인증 |
| PUT | `/knowledge-bases/{surro_knowledge_id}` | Update Knowledge Base | 인증 |
| DELETE | `/knowledge-bases/{surro_knowledge_id}` | Delete Knowledge Base | 인증 |
| POST | `/knowledge-bases/{surro_knowledge_id}/files` | Add File To Knowledge Base | 인증 |
| DELETE | `/knowledge-bases/{surro_knowledge_id}/files/{file_id}` | Delete File From Knowledge Base | 인증 |
| POST | `/knowledge-bases/{surro_knowledge_id}/search` | Search Knowledge Base | 인증 |
| GET | `/knowledge-bases/{surro_knowledge_id}/search-records` | Get Knowledge Base Search Records | 인증 |

## Hub Connect (12)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/hub-connect/models` | 모델 목록 조회 | 인증 |
| GET | `/hub-connect/models/{model_id:path}/files` | 모델 파일 목록 조회 | 인증 |
| GET | `/hub-connect/models/{model_id:path}/download` | 모델 파일 다운로드 | 인증 |
| GET | `/hub-connect/models/{model_id:path}` | 모델 상세 조회 | 인증 |
| GET | `/hub-connect/tags` | 전체 태그 그룹 조회 | 인증 |
| GET | `/hub-connect/tags/{group}/all` | 특정 태그 그룹 전체 조회 | 인증 |
| GET | `/hub-connect/tags/{group}` | 특정 태그 그룹 조회 | 인증 |
| GET | `/hub-connect/datasets/` | 데이터셋 목록 조회 | 인증 |
| GET | `/hub-connect/datasets/{repo_id:path}/info` | 데이터셋 상세 조회 | 인증 |
| GET | `/hub-connect/datasets/{repo_id:path}/files` | 데이터셋 파일 목록 조회 | 인증 |
| GET | `/hub-connect/datasets/{repo_id:path}/download/{filename:path}` | 데이터셋 파일 단건 다운로드 | 인증 |
| GET | `/hub-connect/datasets/{repo_id:path}/download` | 데이터셋 스냅샷 다운로드 | 인증 |

## Any Cloud — 클러스터 (19)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/any-cloud/system/clusters` | 클러스터 전체 목록을 조회합니다 | 인증 |
| GET | `/any-cloud/system/cluster/exists` | 클러스터 존재 여부를 확인합니다 | 인증 |
| GET | `/any-cloud/system/cluster/{cluster_id}` | 클러스터 상세 (VM/Registered 통합 스키마) | 인증 |
| GET | `/any-cloud/system/cluster/{cluster_id}/test-connection` | 클러스터 연결 상태를 테스트합니다 | 인증 |
| PUT | `/any-cloud/system/cluster/{cluster_id}` | 클러스터 수정 (현재 워커 수 변경만 지원) | 관리자 |
| POST | `/any-cloud/system/cluster` | 클러스터 등록 (외부 K8s cluster 만) | 관리자 |
| POST | `/any-cloud/system/cluster/{cluster_id}/refresh` | 클러스터 상태를 강제로 업데이트합니다 | 관리자 |
| DELETE | `/any-cloud/system/cluster/{cluster_id}` | 클러스터를 삭제합니다 | 관리자 |
| POST | `/any-cloud/system/cluster-validations` | VM 클러스터 생성 사전 검증 (정적 검증만, 실제 자원 생성 X) | 관리자 |
| POST | `/any-cloud/system/cluster-validations/preview` | VM 클러스터 생성 미리보기 — 실제 생성될 자원 계획만 반환 (실제 생성 X) | 관리자 |
| GET | `/any-cloud/system/cluster/{cluster_name}/kubeconfig` | 클러스터 kubeconfig 다운로드 (YAML) | 관리자 |
| GET | `/any-cloud/system/cluster/{cluster_name}/agent-bootstrap` | Cluster-agent bootstrap 정보 (helmInstallCommand / kubectlApplyCommand / token / expiresAt) | 관리자 |
| GET | `/any-cloud/system/cluster/{cluster_name}/agent-manifest` | 클러스터 agent install manifest 다운로드 (YAML) | 관리자 |
| GET | `/any-cloud/system/cluster/{cluster_name}/health` | 클러스터 종합 health 조회 | 인증 |
| GET | `/any-cloud/system/agents/health` | 모든 클러스터의 에이전트 health 요약 | 관리자 |
| GET | `/any-cloud/system/cluster/{cluster_name}/operations` | 특정 클러스터의 작업 이력 조회 | 인증 |
| GET | `/any-cloud/system/cluster/{cluster_name}/state-history` | VM 클러스터 workflow state 변경 이력 | 인증 |
| POST | `/any-cloud/system/cluster/{cluster_name}/ssh-key` | VM 클러스터 SSH 키 발급/조회 | 관리자 |
| GET | `/any-cloud/system/cluster/{cluster_name}/resource-kinds` | 클러스터가 지원하는 K8s kind 목록 (CRD 포함) | 인증 |

## Any Cloud — VM 인프라 (11)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/any-cloud/vms` | VM 인프라 목록 | 인증 |
| GET | `/any-cloud/vms/{vm_name}` | VM 상세 (workflow / stack outputs / 진행 상태) | 인증 |
| POST | `/any-cloud/vms` | VM 생성 (Pulumi provision) — 202 + Operation | 관리자 |
| PATCH | `/any-cloud/vms/{vm_name}` | VM scale (workerCount 변경) — 202 + Operation | 관리자 |
| DELETE | `/any-cloud/vms/{vm_name}` | VM 삭제 (Pulumi destroy) — 202 + Operation | 관리자 |
| GET | `/any-cloud/vms/{vm_name}/operations` | 이 VM 의 operation 이력 | 인증 |
| POST | `/any-cloud/vms/{vm_name}/operations` | VM 액션 (retryWorkflow / retryRegistration / refreshStatus) | 관리자 |
| GET | `/any-cloud/vms/{vm_name}/state-history` | VM workflow state transition 이력 | 인증 |
| GET | `/any-cloud/vms/{vm_name}/nodes` | VM 노드 목록 (role / publicIp / privateIp + SSH 사용자) | 인증 |
| POST | `/any-cloud/vms/{vm_name}/ssh-key` | VM SSH private key 발급. format=pem 이면 raw PEM 파일로 내려간다 | 관리자 |
| GET | `/any-cloud/vms/{vm_name}/kubeconfig` | VM 의 kubeconfig YAML 다운로드 (단기 SA token) | 관리자 |

## Any Cloud — Kubernetes (10)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| WEBSOCKET | `/any-cloud/kubernetes/clusters/{cluster_name}/pods/{namespace}/{pod_name}/exec` | Pod exec WebSocket proxy (admin 전용) | 관리자 |
| GET | `/any-cloud/kubernetes/test-connection` | 클러스터 K8s API 연결 상태 확인 | 인증 |
| GET | `/any-cloud/kubernetes/{resource_type}` | 리소스 목록 (cursor 페이지네이션) | 인증 |
| GET | `/any-cloud/kubernetes/{resource_type}/{resource_name}` | 리소스 단건 조회 | 인증 |
| GET | `/any-cloud/kubernetes/{resource_type}/{resource_name}/events` | 지정 리소스에 연관된 K8s Event 목록 (involvedObject.kind/name 으로 fieldSelector 필터링) | 인증 |
| POST | `/any-cloud/kubernetes/{resource_type}/{resource_name}/restart` | 리소스 재시작 | 관리자 |
| POST | `/any-cloud/kubernetes/{resource_type}/{resource_name}/scale` | replicas 변경. deployments/replicasets/statefulsets 만 지원. 그 외 kind 는 400 | 관리자 |
| DELETE | `/any-cloud/kubernetes/{resource_type}/{resource_name}` | 쿠버네티스 특정 리소스를 삭제합니다 | 관리자 |
| GET | `/any-cloud/kubernetes/pods/{pod_name}/logs` | 파드 로그 (text/plain — SSE 아닌 단일 조회) | 인증 |
| POST | `/any-cloud/kubernetes/{resource_type}` | 쿠버네티스 리소스 생성 (JSON 또는 YAML 객체 형태) | 관리자 |

## Any Cloud — Helm 저장소 · 카탈로그 (14)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/any-cloud/helm-repos` | 헬름 저장소 전체 목록을 조회합니다 | 인증 |
| GET | `/any-cloud/helm-repos/{helm_repo_name}/exists` | 헬름 저장소 존재 여부를 확인합니다 | 인증 |
| GET | `/any-cloud/helm-repos/{helm_repo_name}` | 헬름 저장소 상세 정보를 조회합니다 | 인증 |
| POST | `/any-cloud/helm-repos` | 헬름 저장소 등록 | 관리자 |
| DELETE | `/any-cloud/helm-repos/{helm_repo_name}` | 헬름 저장소를 삭제합니다 | 관리자 |
| GET | `/any-cloud/catalog/releases` | 클러스터의 Helm 릴리즈 목록 | 인증 |
| GET | `/any-cloud/catalog/{repoName}` | 저장소의 차트 목록 | 인증 |
| GET | `/any-cloud/catalog/{repoName}/{chartName}/detail` | 차트 상세 | 인증 |
| GET | `/any-cloud/catalog/{repoName}/{chartName}/readme` | 차트 README | 인증 |
| GET | `/any-cloud/catalog/{repoName}/{chartName}/status` | 릴리즈 배포 상태 | 인증 |
| GET | `/any-cloud/catalog/{repoName}/{chartName}/values` | 차트 기본 values.yaml | 인증 |
| GET | `/any-cloud/catalog/releases/{releaseName}/resources` | 릴리즈가 만든 리소스 목록 | 인증 |
| POST | `/any-cloud/catalog/{repoName}/{chartName}/deploy` | 차트 배포 (values.yaml 파일 업로드 가능) | 관리자 |
| POST | `/any-cloud/clusters/{cluster_name}/helm-releases` | Helm 릴리즈 설치 (JSON body) | 관리자 |

## Any Cloud — 모니터링 · 관측 (17)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/any-cloud/monit/{cluster_name}/query` | Prometheus instant query | 인증 |
| POST | `/any-cloud/monit/{cluster_name}/multi-query` | Prometheus N PromQL 병렬 fan-out | 인증 |
| GET | `/any-cloud/monit/{cluster_name}/query_range` | Prometheus range query | 인증 |
| GET | `/any-cloud/monit/{cluster_name}/standard/{metric}` | Prometheus 표준 metric — 사전 정의된 query 묶음 | 인증 |
| GET | `/any-cloud/monit/nodeStatus/{cluster_name}` | **(deprecated)** 클러스터 노드 상태 조회 | 인증 |
| GET | `/any-cloud/clusters/{cluster_name}/observability/targets` | Prometheus scrape target 상태 | 인증 |
| GET | `/any-cloud/clusters/{cluster_name}/observability/alerts` | 발생 중 alert 목록 | 인증 |
| GET | `/any-cloud/clusters/{cluster_name}/observability/alert-silences` | alert silence 목록 | 인증 |
| POST | `/any-cloud/clusters/{cluster_name}/observability/alert-silences` | alert silence 생성 | 관리자 |
| DELETE | `/any-cloud/clusters/{cluster_name}/observability/alert-silences/{silence_id}` | alert silence 제거 | 관리자 |
| GET | `/any-cloud/observability/alert-rules` | alert rule 카탈로그 (전역) | 인증 |
| POST | `/any-cloud/clusters/{cluster_name}/observability/alert-rules/install-all` | alert rule 전체 설치 | 관리자 |
| POST | `/any-cloud/clusters/{cluster_name}/observability/alert-rules/{rule_set_id}` | alert rule set 설치 | 관리자 |
| DELETE | `/any-cloud/clusters/{cluster_name}/observability/alert-rules/{rule_set_id}` | alert rule set 제거 | 관리자 |
| GET | `/any-cloud/clusters/{cluster_name}/observability/dashboard` | 클러스터 대시보드 메타 | 인증 |
| GET | `/any-cloud/observability/standard-queries` | 표준 query 카탈로그 (전역) | 인증 |
| GET | `/any-cloud/observability/aggregate` | 다 클러스터 통합 지표 | 인증 |

## Any Cloud — 프로바이더 · 자격증명 · 애드온 (15)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/any-cloud/providers` | 지원 CSP 목록 조회 | 인증 |
| GET | `/any-cloud/providers/{provider}/regions` | CSP 별 region 목록 조회 | 인증 |
| GET | `/any-cloud/providers/{provider}/specs` | CSP 별 VM spec 목록 | 인증 |
| GET | `/any-cloud/providers/{provider}/config-schema` | CSP 별 클러스터 설정 스키마 조회 | 인증 |
| GET | `/any-cloud/providers/{provider}/images` | CSP 별 OS 이미지 목록 조회 | 인증 |
| GET | `/any-cloud/credentials` | CSP 자격증명 목록 조회 | 관리자 |
| GET | `/any-cloud/credentials/{credential_id}` | CSP 자격증명 단건 조회 (secret 은 마스킹 처리됨) | 관리자 |
| POST | `/any-cloud/credentials` | CSP 자격증명 등록 | 관리자 |
| DELETE | `/any-cloud/credentials/{credential_id}` | CSP 자격증명 삭제 | 관리자 |
| GET | `/any-cloud/addons` | 설치 가능한 애드온 카탈로그 목록 | 인증 |
| GET | `/any-cloud/clusters/{cluster_name}/addons` | 클러스터에 설치된 애드온 목록 조회 | 인증 |
| GET | `/any-cloud/clusters/{cluster_name}/addons/{addon_id}` | 애드온 단건 조회 | 인증 |
| POST | `/any-cloud/clusters/{cluster_name}/addons` | 애드온 설치 요청 | 관리자 |
| DELETE | `/any-cloud/clusters/{cluster_name}/addons/{addon_id}` | 애드온 제거 요청 | 관리자 |
| POST | `/any-cloud/clusters/{cluster_name}/addons/{addon_id}/retry` | 실패한 애드온 재시도 | 관리자 |

## Any Cloud — 작업 · 워크플로 (6)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/any-cloud/operations` | 작업 이력 목록 조회 | 인증 |
| GET | `/any-cloud/operations/{operation_id}` | 작업 단건 조회 | 인증 |
| POST | `/any-cloud/operations/{operation_id}/cancel` | 진행 중 작업 취소 요청 | 관리자 |
| GET | `/any-cloud/workflow/queues` | 워크플로우 큐 상태 | 관리자 |
| GET | `/any-cloud/workflow/dead-letter-messages` | DLQ 메시지 목록 | 관리자 |
| POST | `/any-cloud/workflow/dead-letter-messages/{message_id}/operations` | DLQ 메시지 처리 (재시도 / 폐기) | 관리자 |

## Any Cloud — 관리자 전용 (17)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/any-cloud/audit-logs` | 감사 로그 조회 | 관리자 |
| DELETE | `/any-cloud/admin/clusters/{cluster_name}/force` | 클러스터 강제 삭제 | 관리자 |
| DELETE | `/any-cloud/admin/clusters/{stack_name}/orphan-state` | 오펀 Pulumi state 삭제 | 관리자 |
| GET | `/any-cloud/admin/clusters/{cluster_name}/drift` | 클러스터 drift 조회 | 관리자 |
| POST | `/any-cloud/admin/clusters/{cluster_name}/refresh-state` | 클러스터 state 강제 갱신 | 관리자 |
| GET | `/any-cloud/admin/agents` | cluster-agent 전체 목록 | 관리자 |
| GET | `/any-cloud/admin/agent/heartbeat-staleness` | 에이전트 heartbeat 정체 상태 | 관리자 |
| POST | `/any-cloud/admin/agent/heartbeat-staleness` | heartbeat 정체 처리 실행 | 관리자 |
| GET | `/any-cloud/admin/agent/policy/preview` | 에이전트 정책 미리보기 | 관리자 |
| GET | `/any-cloud/admin/agent/policy/audit` | 에이전트 정책 audit | 관리자 |
| PUT | `/any-cloud/admin/clusters/{cluster_name}/agent-policy` | 클러스터 에이전트 정책 적용 | 관리자 |
| PATCH | `/any-cloud/admin/clusters/{cluster_name}/agent-policy` | 클러스터 에이전트 정책 부분 변경 | 관리자 |
| POST | `/any-cloud/admin/clusters/{cluster_name}/agent/reinstall` | 클러스터 에이전트 재설치 | 관리자 |
| GET | `/any-cloud/fleet/upgrade/preview` | fleet upgrade 미리보기 | 관리자 |
| GET | `/any-cloud/fleet/upgrade/runs` | fleet upgrade 실행 이력 | 관리자 |
| PUT | `/any-cloud/clusters/{cluster_name}/upgrade-wave` | 클러스터 upgrade wave 변경 | 관리자 |
| POST | `/any-cloud/clusters/{cluster_name}/upgrade` | 클러스터 upgrade 실행 | 관리자 |

## 관리자 대시보드 (12)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/admin/dashboard/summary` | 대시보드 KPI 요약 일괄 | 관리자 |
| GET | `/admin/dashboard/users/top` | 도메인별 자산 보유 상위 사용자 | 관리자 |
| GET | `/admin/dashboard/infra/status` | [MOCK] Any Cloud 클러스터 연결 상태 | 관리자 |
| GET | `/admin/dashboard/infra/nodes` | [MOCK] 클러스터 내 노드 + 리소스 | 관리자 |
| GET | `/admin/dashboard/infra/resources` | [MOCK] 노드별 단일 리소스 종류 추출 | 관리자 |
| GET | `/admin/dashboard/events` | 활동 로그(audit_logs) 조회 | 관리자 |
| GET | `/admin/dashboard/trends` | 자산 일별 생성/삭제 + 가입자 추이 | 관리자 |
| POST | `/admin/dashboard/trends/refresh` | 트렌드 수동 재계산 (daily_stats + mat view) | 관리자 |
| GET | `/admin/dashboard/api-metrics` | API 응답시간 히스토그램 + p95 근사 | 관리자 |
| POST | `/admin/dashboard/api-metrics/flush` | API 메트릭 in-memory buffer 즉시 flush | 관리자 |
| GET | `/admin/dashboard/providers/health` | 외부 provider 헬스 상태 + 시계열 | 관리자 |
| POST | `/admin/dashboard/providers/health/probe` | 외부 provider 즉시 probe + 기록 | 관리자 |

## 개인 대시보드 (4)

| Method | Path | 설명 | 권한 |
|---|---|---|---|
| GET | `/me/dashboard/summary` | 내 대시보드 KPI 요약 (본인 자산만) | 인증 |
| GET | `/me/dashboard/services` | 내 서비스 현황 카드 (워크플로우 수 / 사용 모델 수) | 인증 |
| GET | `/me/dashboard/monitoring` | 내 서비스 모니터링 (메시지/사용자/토큰/상호작용, 1h·1d·1w) | 인증 |
| GET | `/me/dashboard/activities` | 내 작업 이력 (서비스/워크플로우 생성·수정·삭제·상태변경 등) | 인증 |
