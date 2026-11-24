# 아키텍처

## 모듈 계층

```
app/
├── main.py            # 앱 부트 · 미들웨어 · 라우터 등록 · lifespan(scheduler)
├── config.py          # 환경변수 로딩 + 기동 시 필수값 검증
├── database.py        # SQLAlchemy engine / SessionLocal / get_db
├── auth.py            # JWT 발급·검증, get_current_user / get_current_admin_user
├── middleware.py      # RequestLoggingMiddleware (access log + API 메트릭 수집)
├── logging_config.py  # 파일/JSON 로깅, 로테이션
├── scheduler.py       # 대시보드·정합성 배경 작업
├── routes/            # 도메인 라우터 (public contract 경계)
├── services/          # 외부 provider 통합 (httpx, OAuth2 토큰 캐시)
├── cruds/             # 게이트웨이 DB CRUD (매핑·soft delete)
├── schemas/           # Pydantic 요청/응답
├── models/            # SQLAlchemy ORM
└── common/sort.py     # 공용 정렬 파서 (sort=-field,field2)
```

## 요청 흐름

```
Client
  └─ CORS → RequestLoggingMiddleware (X-Request-ID 부여, 응답시간 기록)
      └─ route: Depends(get_current_user | get_current_admin_user), Depends(get_db)
          ├─ cruds/*      : 게이트웨이 DB 매핑 조회 → 소유자/역할 검증
          ├─ services/*   : httpx AsyncClient로 upstream 호출
          │                  · OAuth2 password grant 토큰을 asyncio.Lock으로 캐시·갱신
          │                  · 사용자 컨텍스트를 X-User-ID / X-User-Role / X-User-Name-B64로 전달
          └─ audit_service: 생성/수정/삭제/로그인 이벤트를 audit_logs에 best-effort 기록
```

## 외부 provider 매핑

| Provider | 담당 도메인 | 환경변수 prefix | 인증 |
|---|---|---|---|
| MLOps / Surro | service, workflow, dataset, learning, model, prompt, knowledge_base, model_improvement | `PROXY_*`, `EXTERNAL_API_*` | `{PROXY_TARGET_BASE_URL}/api/v1/authentications/token` (password grant) |
| Hub Connect | hub_connect (HuggingFace 등 모델/데이터셋 허브) | `HUB_CONNECT_*` | provider 계정 설정 |
| Any Cloud | any_cloud (클러스터 · VM 프로비저닝 · Kubernetes · Helm/카탈로그 · Prometheus 모니터링 · 관측/alert · CSP 자격증명 · 애드온 · 에이전트/fleet) | `ANY_CLOUD_*` | 없음 (신뢰망 전제, 사용자 컨텍스트 헤더만 전달) |

## 데이터 모델

ORM 테이블 18개. 상세 정보는 provider에서 실시간 조회하고, 게이트웨이 DB는 **매핑 + 소유자 + 캐시**만 보관한다.

### 매핑 테이블 (soft delete: `deleted_at` / `deleted_by` / `is_active`)

| 테이블 | 용도 | 외부 키 |
|---|---|---|
| `services` | 서비스 매핑 | `surro_service_id` |
| `workflows` | 워크플로우 매핑 (템플릿 포함) | `surro_workflow_id` |
| `models` | 모델 매핑 (+ `is_catalog` visibility 캐시) | `surro_model_id` |
| `datasets` | 데이터셋 매핑 | `surro_dataset_id` |
| `prompts` | 프롬프트 매핑 | `surro_prompt_id` |
| `knowledge_bases` | 지식베이스 매핑 | `surro_knowledge_id` |
| `experiments` | 학습(실험/파이프라인) 매핑 | `surro_experiment_id` |
| `model_improvements` | 모델 최적화/경량화 task 매핑 | 외부 task ID |

### 사용자 / 인프라 / 관측

| 테이블 | 용도 |
|---|---|
| `members` | 사용자 계정, 역할(`admin`/`user`), 활성 상태, 마지막 로그인 |
| `hub_connections` | 모델 허브 연결 설정 (허브 URL/타입/인증 방식/기본 허브 여부) |
| `any_cloud_data` | Any Cloud 요청·응답 원본 기록 (JSON) |
| `any_cloud_cache` | Any Cloud 응답 캐시 (`cache_key`, `expires_at`, hit count) |
| `audit_logs` | 활동 로그 (create/update/delete/restore/login/logout/permission_change) |
| `daily_stats` | 일별 자산 생성/삭제 + 가입자 집계 (PG에서는 `mv_daily_trends` materialized view 병행) |
| `api_request_histograms` | API 응답시간 히스토그램 (경로 × 상태코드 클래스) |
| `provider_health_snapshots` | 외부 provider 헬스 probe 스냅샷 |
| `service_card_snapshots` | 개인 대시보드 서비스 카드 캐시 |
| `service_metric_snapshots` | 개인 대시보드 모니터링 메트릭 캐시 |

마이그레이션은 `alembic/versions/` (현재 14개 revision).
