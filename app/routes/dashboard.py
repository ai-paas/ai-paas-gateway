"""관리자 대시보드 API.

권한: admin 전용 (`get_current_admin_user`).
응답: summary/top/infra/trends/api-metrics/providers는 단일 객체 (페이지네이션 wrapper 미적용),
events만 리스트 응답이라 public pagination 규약(`{data,total,page,size}`) 적용.
"""
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_admin_user
from app.database import get_db
from app.models.audit_log import AuditLog
from app.schemas.dashboard import (
    ApiMetricsPathItem,
    ApiMetricsResponse,
    AuditEventItem,
    AuditEventListResponse,
    DashboardSummary,
    DomainLiteral,
    InfraNodesResponse,
    InfraResourcesResponse,
    InfraStatusResponse,
    ProviderHealthHistoryPoint,
    ProviderHealthLatest,
    ProviderHealthResponse,
    ResourceTypeLiteral,
    TrendsRefreshResponse,
    TrendsResponse,
    UsersTopResponse,
)
from app.services import (
    api_metrics_service,
    dashboard_service,
    infra_adapter,
    provider_health_service,
    trends_service,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin/dashboard", tags=["Admin - Dashboard"])


# 공통 에러 응답 정의 — 관리자 보호 라우트
_ADMIN_ERRORS = {
    401: {"description": "토큰 누락/만료/무효"},
    403: {"description": "관리자 권한 필요 (`role != 'admin'`)"},
}
_ADMIN_ERRORS_WITH_422 = {
    **_ADMIN_ERRORS,
    422: {"description": "쿼리 파라미터 검증 실패 (잘못된 enum/범위 등)"},
}


# ============================================================
# 1. KPI 요약
# ============================================================

@router.get(
    "/summary",
    response_model=DashboardSummary,
    summary="대시보드 KPI 요약 일괄",
    responses=_ADMIN_ERRORS,
)
def get_dashboard_summary(
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """관리자 대시보드 첫 화면용 일괄 카운트.

    ## 응답 구성
    - **users** — 사용자 5종 카운트
        - `total`, `active`(`is_active=true`), `inactive`(`is_active=false`),
          `recent7d`(최근 7일 가입), `by_role`(`{admin: N, user: N}`)
    - **services / workflows / models / model_improvements / datasets / experiments
      / knowledge_bases / prompts** — 8개 자산 도메인의 `AssetCount`
    - **generated_at** — 응답 생성 시각 (UTC)

    ## AssetCount 의미
    - `total` = `active + inactive + deleted`
    - `active`   = `deleted_at IS NULL AND is_active IS TRUE` (soft-delete 없는 도메인은 = total)
    - `inactive` = `deleted_at IS NULL AND is_active IS FALSE` (없는 도메인은 0)
    - `deleted`  = `deleted_at IS NOT NULL` (없는 도메인은 0)

    > `service`, `workflow`는 soft-delete 컬럼이 없어 항상 `inactive=0, deleted=0`.

    ## 비고
    - 실시간 raw 집계 (캐시 없음). 응답 시간은 도메인 행 수에 비례하나 일반적으로 100ms 미만.
    - 본인 자산만 보려면 `GET /api/v1/me/dashboard/summary` 사용.
    """
    return dashboard_service.build_summary(db)


# ============================================================
# 2. 도메인별 상위 사용자
# ============================================================

@router.get(
    "/users/top",
    response_model=UsersTopResponse,
    summary="도메인별 자산 보유 상위 사용자",
    responses=_ADMIN_ERRORS_WITH_422,
)
def get_users_top(
    domain: DomainLiteral = Query(
        ...,
        description=(
            "자산 도메인. 허용 값: `service`, `workflow`, `model`, `model_improvement`, "
            "`dataset`, `experiment`, `knowledge_base`, `prompt`."
        ),
    ),
    size: int = Query(3, ge=1, le=10, description="상위 N명 (1~10)"),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """선택한 도메인에서 `created_by` 기준으로 자산을 가장 많이 보유한 사용자 N명.

    ## 응답 예시
    ```json
    {
      "domain": "model",
      "items": [
        { "member_id": "alice", "name": "앨리스", "count": 14 },
        { "member_id": "bob",   "name": "밥",     "count":  9 }
      ]
    }
    ```

    ## 비고
    - **soft-delete 도메인**은 active 자산만 카운트 (`deleted_at IS NULL AND is_active=true`).
    - 사용자 표시명(`name`)은 Member 테이블에서 join. 매칭 실패 시 `null`.
    - 결과는 `count` 내림차순. 동률 시 DB 정렬 의존(보장 없음).
    """
    items = dashboard_service.top_users_by_domain(db, domain, size)
    return UsersTopResponse(domain=domain, items=items)


# ============================================================
# 3. 인프라 — Any Cloud (현재 mock)
# ============================================================

@router.get(
    "/infra/status",
    response_model=InfraStatusResponse,
    summary="[MOCK] Any Cloud 클러스터 연결 상태",
    responses=_ADMIN_ERRORS,
)
async def get_infra_status(
    _: None = Depends(get_current_admin_user),
):
    """등록된 클러스터 목록과 각 연결 상태.

    ## 응답 필드
    - `clusters[]` — 클러스터 리스트
        - `name`, `last_checked_at`, `message`
        - `status` ∈ `connected | disconnected | error | unknown`
    - `has_data` — 등록된 클러스터가 1개라도 있으면 `true`. **false면 프론트는 empty state UI**.

    ## ⚠ Mock 안내
    현재 Any Cloud 실연동 전이라 **샘플 데이터**를 반환합니다(`any-cloud-dev`, `any-cloud-prod`).
    응답 구조는 실연동 후에도 동일합니다. 토글은 `app/services/infra_adapter.py::_USE_MOCK`.
    """
    return await infra_adapter.get_infra_status()


@router.get(
    "/infra/nodes",
    response_model=InfraNodesResponse,
    summary="[MOCK] 클러스터 내 노드 + 리소스",
    responses=_ADMIN_ERRORS_WITH_422,
)
async def get_infra_nodes(
    cluster: str = Query(..., description="클러스터 이름 (예: `any-cloud-dev`). `/infra/status` 응답의 `name`."),
    _: None = Depends(get_current_admin_user),
):
    """선택한 클러스터의 모든 노드와 각 노드의 CPU/메모리/파일시스템/가속기 리소스.

    ## 응답 구조 요약
    ```
    cluster: { name, status, last_checked_at, message }
    nodes: [{
      name,
      status,    # ready | warning | error | unknown
      resources: {
        cpu:    { total, used, unit: "core" },
        memory: { total, used, unit: "GiB" },
        filesystems: [{ mount, total, used, unit: "GiB" }],
        accelerators: [{
          kind,    # gpu | npu | tpu | other  (확장 안전한 단일 배열 구조)
          status,  # available | not_available | error
          vendor?, model?, total?, used?, unit: "device",
          metrics: { memory_used_gib?, memory_total_gib?, utilization_percent?, ... }
        }]
      }
    }]
    ```

    ## 가속기 처리 가이드
    - `accelerators[]`에 `kind`로 GPU/NPU/TPU 분기. 미래에 새 가속기가 추가되어도 응답 구조 변화 없음.
    - `status=not_available` 항목은 회색/숨김 처리 권장 (placeholder).
    - 공통 metrics 키는 `memory_used_gib`, `memory_total_gib`, `utilization_percent`,
      `temperature_celsius`. 가속기 고유 키도 같은 객체에 들어올 수 있음.

    ## ⚠ Mock 안내
    Any Cloud 실연동 전 — 샘플 노드(`master-1/2`, `worker-1/2`) 반환.
    """
    return await infra_adapter.get_infra_nodes(cluster)


@router.get(
    "/infra/resources",
    response_model=InfraResourcesResponse,
    summary="[MOCK] 노드별 단일 리소스 종류 추출",
    responses=_ADMIN_ERRORS_WITH_422,
)
async def get_infra_resources(
    cluster: str = Query(..., description="클러스터 이름"),
    resource_type: ResourceTypeLiteral = Query(
        ...,
        description=(
            "조회할 리소스 종류. 허용 값: `cpu`, `memory`, `filesystem`, `accelerator`. "
            "`accelerator` 한 번이면 GPU/NPU/TPU 전부 회수."
        ),
    ),
    _: None = Depends(get_current_admin_user),
):
    """`/infra/nodes`의 응답에서 특정 리소스 종류만 추려 가벼운 응답을 반환합니다.

    ## 응답 동작
    - `nodes[]`의 각 entry는 선택한 `resource_type`에 해당하는 필드만 채워지고 나머지는 `null`.
        - `resource_type=cpu` → `cpu` 채움, `memory/filesystems/accelerators` 모두 `null`
        - `resource_type=accelerator` → `accelerators` 채움 (가속기 미장착 노드는 빈 배열)

    ## 비고
    - upstream(Any Cloud)의 원본 `type/key` (예: `cpu/usage_namespace`)는 adapter 내부에서 변환되어
      public 응답에는 노출되지 않습니다 (CLAUDE.md §5).
    - Mock 상태에선 `/infra/nodes`와 동일한 샘플 데이터에서 추출.
    """
    return await infra_adapter.get_infra_resources(cluster, resource_type)


# ============================================================
# 4. 활동 로그
# ============================================================

@router.get(
    "/events",
    response_model=AuditEventListResponse,
    summary="활동 로그(audit_logs) 조회",
    responses=_ADMIN_ERRORS_WITH_422,
)
def get_dashboard_events(
    page: int = Query(1, ge=1, description="페이지 번호 (1부터)"),
    size: int = Query(20, ge=1, le=200, description="페이지 크기 (1~200)"),
    resource_type: Optional[str] = Query(
        None,
        description=(
            "resource_type 필터. 허용 값: `service`, `workflow`, `model`, `model_improvement`, "
            "`dataset`, `experiment`, `knowledge_base`, `prompt`, `member`."
        ),
    ),
    action: Optional[str] = Query(
        None,
        description=(
            "action 필터. 허용 값: `create`, `update`, `delete`, `restore`, "
            "`login`, `logout`, `status_change`, `permission_change`."
        ),
    ),
    actor: Optional[str] = Query(None, description="액션 수행자의 `member_id` 정확 일치"),
    since: Optional[datetime] = Query(None, description="이 시각(UTC) 이후 이벤트만. ISO 8601 형식."),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """자산 생성/수정/삭제 + 로그인/로그아웃/권한 변경 이벤트 시계열.

    ## 정렬 / 페이지네이션
    - 기본 정렬: `created_at DESC, id DESC` (최신순). 변경 불가.
    - public pagination 규약(`{data, total, page, size}`) 적용.

    ## 응답 필드
    각 `data[]` 항목:

    | 필드 | 타입 | 설명 |
    |---|---|---|
    | `id` | int | 내부 BigInt PK |
    | `action` | string | 위 `action` enum 중 하나 |
    | `resource_type` | string | 위 `resource_type` enum 중 하나 |
    | `resource_id` | string \\| null | gateway PK 또는 surro id 등 (도메인별 다름) |
    | `actor_member_id` | string | 액션 수행자 |
    | `target_member_id` | string \\| null | 다른 사용자 대상 액션 시 (예: `status_change`) |
    | `metadata` | object \\| null | 액션별 부가 JSON (예: `{"name":"..."}`, `{"from":true,"to":false}`) |
    | `request_id` | string \\| null | `X-Request-ID`와 일치 → access.log 추적 |
    | `ip` | string \\| null | 호출 클라이언트 IP |
    | `created_at` | datetime | 기록 시각 (UTC) |

    > 응답 키는 `metadata`이지만 게이트웨이 내부 ORM 속성은 `metadata_json`입니다
    > (SQLAlchemy `Base.metadata` 충돌 회피). 프론트는 `metadata`만 보면 됩니다.

    ## UI 처리 팁
    - `action`별 색상/아이콘 매핑 권장.
    - `metadata` 키는 자유 — 알려진 키만 가공하고 나머지는 raw 표시.
    """
    query = db.query(AuditLog)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor_member_id == actor)
    if since:
        query = query.filter(AuditLog.created_at >= since)

    total = query.count()
    rows = (
        query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset((page - 1) * size)
        .limit(size)
        .all()
    )

    items = [
        AuditEventItem(
            id=r.id,
            action=r.action,
            resource_type=r.resource_type,
            resource_id=r.resource_id,
            actor_member_id=r.actor_member_id,
            target_member_id=r.target_member_id,
            metadata_json=r.metadata_json,
            request_id=r.request_id,
            ip=r.ip,
            created_at=r.created_at,
        )
        for r in rows
    ]
    return AuditEventListResponse(data=items, total=total, page=page, size=size)


# ============================================================
# 5. 트렌드 / 시계열
# ============================================================

@router.get(
    "/trends",
    response_model=TrendsResponse,
    summary="자산 일별 생성/삭제 + 가입자 추이",
    responses=_ADMIN_ERRORS_WITH_422,
)
def get_dashboard_trends(
    days: int = Query(30, ge=1, le=365, description="과거 N일 (1~365, 기본 30)"),
    domain: Optional[str] = Query(
        None,
        description=(
            "단일 도메인 필터. 허용 값: 8개 자산 도메인(`service`/.../`prompt`) "
            "또는 회원 가입 추이용 의사 도메인 `signup`. 미지정 시 전체."
        ),
    ),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """선택한 기간의 일별 자산 생성/삭제 + 가입자 추이 (시계열 차트용).

    ## 응답 필드
    - `start`, `end` — 조회 범위 (포함, UTC date)
    - `days` — 요청한 days 그대로
    - `source` — 어느 저장소에서 가져왔는지
        - `daily_stats` — 스케줄러가 채운 캐시 테이블 (가장 빠름)
        - `materialized_view` — PG `mv_daily_trends` 폴백 (daily_stats가 비었을 때)
        - `live` — raw 집계 폴백 (SQLite/dev 또는 mv도 비었을 때)
    - `series[]` — `{ domain, metric, points: [{date, value}] }`
        - `metric` ∈ `created`(생성) / `deleted`(soft-delete 도메인만)
    - `generated_at` — 응답 생성 시각

    ## UI 처리 팁
    - 동일 `metric`끼리 묶거나 `created`/`deleted`를 양/음으로 표현 (stacked area 등).
    - 빈 날짜는 series에 포함되지 않음 → 클라이언트에서 0으로 채우는 게 시각화에 자연스러움.

    ## 에러
    - `422` — `domain`이 enum이 아닌 값
    """
    try:
        return trends_service.get_trends(db, days=days, domain=domain)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post(
    "/trends/refresh",
    response_model=TrendsRefreshResponse,
    summary="트렌드 수동 재계산 (daily_stats + mat view)",
    responses=_ADMIN_ERRORS,
)
def refresh_dashboard_trends(
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """raw 집계를 `daily_stats`에 upsert하고, PG에선 `mv_daily_trends`도 REFRESH.

    ## 동작
    - 모든 8개 자산 도메인의 `created_at`/`deleted_at` 기준으로 일별 카운트 재계산
    - **stale row 정리** — raw 집계 키 집합에 없는 기존 `daily_stats` row는 삭제
    - PostgreSQL: `REFRESH MATERIALIZED VIEW CONCURRENTLY mv_daily_trends` 실행
    - SQLite: mat view 없음 → `refreshed_materialized_view=false`

    ## 호출 시점
    - 스케줄러(`ENABLE_SCHEDULER=true`)가 도는 환경에선 보통 호출 불필요 (매일 0:05 UTC 자동).
    - 스케줄러 미사용 환경 또는 데이터 정합 의심 시 수동 호출.

    ## 응답
    ```json
    { "rows_upserted": 53, "refreshed_materialized_view": true, "finished_at": "..." }
    ```
    """
    rows = trends_service.refresh_daily_stats(db)
    refreshed_mv = db.bind.dialect.name == "postgresql"
    return TrendsRefreshResponse(
        rows_upserted=rows,
        refreshed_materialized_view=refreshed_mv,
        finished_at=datetime.utcnow(),
    )


# ============================================================
# 6. API 메트릭
# ============================================================

@router.get(
    "/api-metrics",
    response_model=ApiMetricsResponse,
    summary="API 응답시간 히스토그램 + p95 근사",
    responses=_ADMIN_ERRORS_WITH_422,
)
def get_dashboard_api_metrics(
    hours: int = Query(24, ge=1, le=168, description="최근 N시간 (1~168, 기본 24)"),
    path_pattern: Optional[str] = Query(
        None,
        description="경로 패턴 필터 (예: `/api/v1/models/{id}`). path-param은 `{id}`로 정규화되어 저장됨.",
    ),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """경로(path_pattern) × 응답코드 클래스(2xx/4xx/5xx)별 호출 수, 평균/최대/p95(근사) 응답시간.

    ## 수집 흐름
    1. `RequestLoggingMiddleware`가 모든 요청 끝에 `record(path, status, duration_ms)` 호출
    2. process-local in-memory buffer에 누적 (분 단위 bucket)
    3. 스케줄러 잡 `flush_api_metrics`가 매 분 buffer → `api_request_histograms` 테이블 upsert

    ## 응답 필드
    - `since` — 집계 시작 시각 (`now - hours`)
    - `generated_at` — 응답 생성 시각
    - `buckets_ms` — 히스토그램 bucket 경계 `[10, 50, 100, 250, 500, 1000, 5000, 999999]`
       (`999999`는 `+Inf` 의미)
    - `paths[]` — path × status_class별 통계

    각 `paths[]` 항목:

    | 필드 | 타입 | 설명 |
    |---|---|---|
    | `path_pattern` | string | path-param 정규화된 경로 |
    | `status_class` | string | `2xx`/`3xx`/`4xx`/`5xx` |
    | `count` | int | 호출 수 |
    | `avg_ms` | float \\| null | 평균 응답시간 |
    | `max_ms` | int | 실측 최댓값 |
    | `p95_ms` | int \\| null | 95th percentile. histogram 보간 근사, **항상 `max_ms` 이하로 capping** |

    ## 빈 응답 가능 조건
    - 스케줄러가 아직 한 번도 안 돌았을 때 → `POST /api-metrics/flush` 수동 호출
    - `SCHEDULER_INCLUDE_API_METRICS=false`인 별도 worker 환경에선 API 프로세스 측에서 별도 flush 필요
    """
    since = datetime.utcnow() - timedelta(hours=hours)
    raw = api_metrics_service.get_api_metrics(db, since=since, path_pattern=path_pattern)
    return ApiMetricsResponse(
        since=raw["since"],
        generated_at=raw["generated_at"],
        buckets_ms=raw["buckets_ms"],
        paths=[ApiMetricsPathItem(**p) for p in raw["paths"]],
    )


@router.post(
    "/api-metrics/flush",
    response_model=dict,
    summary="API 메트릭 in-memory buffer 즉시 flush",
    responses=_ADMIN_ERRORS,
)
def flush_dashboard_api_metrics(
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """스케줄러를 기다리지 않고 process-local buffer를 즉시 DB에 반영.

    ## 응답
    ```json
    { "flushed": 4 }
    ```
    `flushed`는 처리된 unique bucket 수 (path × status_class × le_bucket × bucket_ts).

    ## ⚠ 운영 분리 주의
    middleware의 `_buffer`는 **현재 호출이 도달한 그 프로세스 내부 메모리**입니다.
    별도 scheduler worker로 띄운 환경에서 이 endpoint를 호출하면 그 worker의 빈 버퍼만 비웁니다.
    실제 API 트래픽이 들어오는 프로세스에서 호출하세요.
    """
    n = api_metrics_service.flush_buffered_buckets(db)
    return {"flushed": n}


# ============================================================
# 7. Provider 헬스
# ============================================================

@router.get(
    "/providers/health",
    response_model=ProviderHealthResponse,
    summary="외부 provider 헬스 상태 + 시계열",
    responses=_ADMIN_ERRORS_WITH_422,
)
def get_dashboard_providers_health(
    history_minutes: int = Query(
        60, ge=1, le=1440,
        description="시계열 조회 범위(분, 1~1440=최대 1일). 기본 60.",
    ),
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """외부 provider(`mlops` / `hub_connect` / `any_cloud`)별 최신 헬스 + 최근 N분 시계열.

    ## 응답 구조
    - `providers[]` — provider별 **최신 1건** 스냅샷
        - `provider`, `latency_ms`, `error`, `last_checked_at`
        - `status` ∈ `healthy` | `unhealthy` | `disabled` | `error`
    - `history` — `{ provider: [{ts, status, latency_ms}] }` 시계열 (오름차순)
    - `generated_at` — 응답 생성 시각

    ## status 의미
    | 값 | 의미 |
    |---|---|
    | `healthy` | 2xx/3xx 응답 |
    | `unhealthy` | 4xx/5xx 응답 |
    | `disabled` | 설정에서 비활성 (`*_ENABLED=false`) — 호출 자체 안 함 |
    | `error` | timeout / 네트워크 오류 |

    ## 수집 흐름
    스케줄러 잡 `probe_providers`가 매 `SCHEDULER_PROVIDER_HEALTH_MINUTES`마다 호출 →
    `provider_health_snapshots` insert.

    ## UI 처리 팁
    - 상단 배너에 provider별 상태 배지. `disabled`는 회색, `healthy` 녹색, 그 외 빨강.
    - `history`로 sparkline 또는 최근 1시간 success rate 계산.
    """
    from app.models.api_metric import ProviderHealthSnapshot

    since = datetime.utcnow() - timedelta(minutes=history_minutes)

    # 각 provider별 최신 1건
    sub = (
        db.query(
            ProviderHealthSnapshot.provider,
            func.max(ProviderHealthSnapshot.ts).label("max_ts"),
        )
        .group_by(ProviderHealthSnapshot.provider)
        .subquery()
    )
    latest_rows = (
        db.query(ProviderHealthSnapshot)
        .join(
            sub,
            (ProviderHealthSnapshot.provider == sub.c.provider)
            & (ProviderHealthSnapshot.ts == sub.c.max_ts),
        )
        .all()
    )

    latest = [
        ProviderHealthLatest(
            provider=r.provider,
            status=r.status,  # type: ignore[arg-type]
            latency_ms=r.latency_ms,
            error=r.error,
            last_checked_at=r.ts,
        )
        for r in latest_rows
    ]

    # 시계열
    history_rows = (
        db.query(ProviderHealthSnapshot)
        .filter(ProviderHealthSnapshot.ts >= since)
        .order_by(ProviderHealthSnapshot.provider, ProviderHealthSnapshot.ts)
        .all()
    )
    history: Dict[str, List[ProviderHealthHistoryPoint]] = {}
    for r in history_rows:
        history.setdefault(r.provider, []).append(
            ProviderHealthHistoryPoint(ts=r.ts, status=r.status, latency_ms=r.latency_ms)
        )

    return ProviderHealthResponse(providers=latest, history=history, generated_at=datetime.utcnow())


@router.post(
    "/providers/health/probe",
    response_model=ProviderHealthResponse,
    summary="외부 provider 즉시 probe + 기록",
    responses=_ADMIN_ERRORS,
)
def trigger_provider_probe(
    db: Session = Depends(get_db),
    _: None = Depends(get_current_admin_user),
):
    """스케줄러를 기다리지 않고 즉시 provider 3종을 호출하여 snapshot 1건 기록.

    ## 동작
    - `mlops`, `hub_connect`, `any_cloud` 각각 GET 호출 → latency 측정 + status 결정
    - `*_ENABLED=false` provider는 호출 없이 `status=disabled` 기록
    - 각 provider별 `provider_health_snapshots`에 1건 insert
    - 응답은 `GET /providers/health`와 동일 형식 (단 `history`는 비어있음)

    ## 활용
    - 외부 시스템 장애 의심 시 즉시 상태 확인
    - 스케줄러 미사용 환경의 운영 안전망
    """
    results = provider_health_service.probe_all_and_record(db)
    latest = [
        ProviderHealthLatest(
            provider=r.provider,
            status=r.status,  # type: ignore[arg-type]
            latency_ms=r.latency_ms,
            error=r.error,
            last_checked_at=datetime.utcnow(),
        )
        for r in results
    ]
    return ProviderHealthResponse(providers=latest, history={}, generated_at=datetime.utcnow())
