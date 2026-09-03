# 환경 설정

## 환경 변수

전체 목록과 주석은 `.env.example` 참조. 주요 항목만 정리한다.

### 필수

| 변수 | 설명 |
|---|---|
| `DATABASE_URL` | PostgreSQL 접속 URL (`postgresql://<user>:<pw>@<host>:5432/<db>`) |
| `JWT_SECRET_KEY` | JWT 서명 키 (32자 이상 권장) |

### API / 로깅 / CORS

| 변수 | 기본값 | 설명 |
|---|---|---|
| `API_V1_STR` | `/api/v1` | API prefix |
| `HOST` / `PORT` | `0.0.0.0` / `8000` | 바인딩 |
| `DEBUG` | `false` | reload 여부 |
| `LOG_LEVEL` | `info` | 로그 레벨 |
| `LOG_DIR` | `var/log` | 로그 파일 경로 |
| `LOG_FILE_ENABLED` / `LOG_ACCESS_ENABLED` | `true` / `true` | 파일 로그 / access 로그 |
| `LOG_JSON_FORMAT` | `false` | JSON 라인 포맷 |
| `LOG_ROTATION_MAX_BYTES` / `LOG_ROTATION_BACKUP_COUNT` | `10485760` / `10` | 로테이션 |
| `LOG_ACCESS_MASK_PATHS` | auth 3종 | member_id·query 마스킹 경로 |
| `CORS_ALLOW_ORIGINS` | `*` | `*` / 쉼표 구분 / JSON 배열 지원 |
| `CORS_ALLOW_ORIGIN_REGEX` | (없음) | IP 대역 등 패턴 허용 |

### 인증

| 변수 | 기본값 |
|---|---|
| `JWT_ALGORITHM` | `HS256` |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | `30` |
| `JWT_REFRESH_TOKEN_EXPIRE_DAYS` | `7` |
| `AUTH_REFRESH_COOKIE_NAME` | `refresh_token` |
| `AUTH_REFRESH_COOKIE_HTTPONLY` / `_SECURE` | `true` / `false` |
| `AUTH_REFRESH_COOKIE_SAMESITE` | `lax` (`lax`/`strict`/`none`) |
| `AUTH_REFRESH_COOKIE_DOMAIN` / `_PATH` / `_MAX_AGE` | (없음) / `/api/v1/auth` / `604800` |

### Provider

| 변수 | 기본값 | 설명 |
|---|---|---|
| `PROXY_ENABLED` | `false` | MLOps/Surro 연동 스위치 |
| `PROXY_TARGET_BASE_URL` | (없음) | MLOps base URL (활성 시 필수) |
| `PROXY_TARGET_PATH_PREFIX` | `/api/v1` | upstream prefix |
| `EXTERNAL_API_USERNAME` / `_PASSWORD` | (없음) | MLOps 계정 (활성 시 필수) |
| `PROXY_TIMEOUT` / `PROXY_CONNECT_TIMEOUT` | `30.0` / `5.0` | 타임아웃(초) |
| `PROXY_STRUCTURE_PREDICTION_TIMEOUT` | `300.0` | 단백질 구조 예측 전용 타임아웃 |
| `PROXY_UPLOAD_TIMEOUT` | `300.0` | 대용량 업로드 타임아웃 |
| `MAX_DATASET_FILE_SIZE` | `1073741824` | 데이터셋 업로드 최대 크기(1GB) |
| `PROXY_MAX_CONNECTIONS` / `_MAX_KEEPALIVE_CONNECTIONS` | `100` / `20` | httpx 풀 |
| `HUB_CONNECT_ENABLED` | `false` | Hub Connect 스위치 |
| `HUB_CONNECT_TARGET_BASE_URL` / `_TARGET_PATH_PREFIX` | (없음) / `/api/v1` | Hub Connect endpoint |
| `HUB_CONNECT_API_USERNAME` / `_PASSWORD` | (없음) | Hub Connect 계정 (활성 시 필수) |
| `ANY_CLOUD_ENABLED` | `false` | Any Cloud 스위치. `false`면 `/api/v1/any-cloud/*` 전체가 503 |
| `ANY_CLOUD_TARGET_BASE_URL` | (없음) | Any Cloud endpoint (활성 시 필수) |
| `ANY_CLOUD_TARGET_WS_URL` | (없음) | pod exec WebSocket 대상. 비우면 `TARGET_BASE_URL`의 scheme만 `ws`/`wss`로 치환 |
| `ANY_CLOUD_TIMEOUT` / `_CONNECT_TIMEOUT` | `30.0` / `5.0` | 타임아웃(초) |
| `ANY_CLOUD_MAX_CONNECTIONS` / `_MAX_KEEPALIVE_CONNECTIONS` | `100` / `20` | httpx 풀 |

### 대시보드 / 스케줄러

| 변수 | 기본값 | 설명 |
|---|---|---|
| `ENABLE_SCHEDULER` | `false` | in-process 스케줄러 기동 여부 |
| `SCHEDULER_TRENDS_HOUR` | `0` | `daily_stats` 재계산 시각(UTC) |
| `SCHEDULER_MV_REFRESH_MINUTES` | `30` | materialized view 갱신 주기 |
| `SCHEDULER_API_METRICS_FLUSH_MINUTES` | `1` | API 메트릭 flush 주기 |
| `SCHEDULER_INCLUDE_API_METRICS` | `true` | flush 잡 포함 여부 (API 프로세스에서만 켤 것) |
| `SCHEDULER_PROVIDER_HEALTH_MINUTES` | `1` | provider probe 주기 |
| `SCHEDULER_INCLUDE_DASHBOARD` | `false` | 전체 서비스 카드 pre-warm 잡 |
| `SCHEDULER_DASHBOARD_REFRESH_MINUTES` | `10` | pre-warm 주기 |
| `SCHEDULER_INCLUDE_MODEL_VISIBILITY` | `false` | 모델 visibility reconcile 잡 |
| `SCHEDULER_MODEL_VISIBILITY_MINUTES` | `30` | reconcile 주기 |
| `SCHEDULER_INCLUDE_WORKFLOW_RECONCILE` | `false` | stale 워크플로우 매핑 soft-delete 잡 |
| `SCHEDULER_WORKFLOW_RECONCILE_MINUTES` | `30` | reconcile 주기 |
| `DASHBOARD_CACHE_TTL_MINUTES` | `10` | 개인 대시보드 캐시 TTL (0이면 무한, 스케줄러만 갱신) |
| `DASHBOARD_INCLUDE_MODEL_COUNT` | `true` | 사용 모델 distinct 집계 (워크플로우 detail fan-out 비용 큼) |

## 백그라운드 스케줄러

`app/scheduler.py` — APScheduler `BackgroundScheduler`. `ENABLE_SCHEDULER=false`면 no-op.

| 잡 | 트리거 | 조건 |
|---|---|---|
| `job_refresh_daily_stats` | 매일 `SCHEDULER_TRENDS_HOUR`:05 | 항상 |
| materialized view refresh | `SCHEDULER_MV_REFRESH_MINUTES` 간격 | 항상 (PG 아니면 무시) |
| `job_flush_api_metrics` | `SCHEDULER_API_METRICS_FLUSH_MINUTES` 간격 | `SCHEDULER_INCLUDE_API_METRICS` |
| `job_probe_providers` | `SCHEDULER_PROVIDER_HEALTH_MINUTES` 간격 | 항상 |
| `job_refresh_dashboard_services` | `SCHEDULER_DASHBOARD_REFRESH_MINUTES` 간격 | `SCHEDULER_INCLUDE_DASHBOARD` |
| `job_reconcile_model_visibility` | `SCHEDULER_MODEL_VISIBILITY_MINUTES` 간격 | `SCHEDULER_INCLUDE_MODEL_VISIBILITY` |
| `job_reconcile_workflow_mappings` | `SCHEDULER_WORKFLOW_RECONCILE_MINUTES` 간격 | `SCHEDULER_INCLUDE_WORKFLOW_RECONCILE` |

운영 주의:

- API 메트릭 flush 잡은 미들웨어의 **프로세스 로컬 버퍼**에 의존한다. 스케줄러를 별도 worker로 분리하면 `SCHEDULER_INCLUDE_API_METRICS=false`로 두고, API 프로세스 측에서 flush하거나 `POST /admin/dashboard/api-metrics/flush`를 사용한다.
- 멀티 워커 환경에서는 `ENABLE_SCHEDULER=false`로 두고 스케줄러 전용 프로세스를 별도로 띄우는 것을 권장한다.
- 워크플로우 매핑 reconcile은 목록 조회가 수행하지 않는다(원격 장애·필터로 정상 매핑을 지울 위험). 이 잡에만 위임하며, upstream 응답이 비어 있으면 전체 삭제로 해석하지 않고 skip한다.
