"""개인사용자 대시보드 API.

권한: 일반 사용자 본인 (`get_current_user`).
인프라/타 사용자 정보 제외, 본인 `created_by` 자산만 집계.
"""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models import Member
from app.schemas.dashboard import (
    MyActivityItem,
    MyActivityListResponse,
    MyServiceCardsResponse,
    MyServiceMonitoringResponse,
    PersonalDashboardSummary,
)
from app.services import dashboard_service, me_dashboard_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me/dashboard", tags=["My - Dashboard"])


_USER_ERRORS = {
    401: {"description": "토큰 누락/만료/무효"},
}
_USER_ERRORS_WITH_422 = {
    **_USER_ERRORS,
    422: {"description": "쿼리 파라미터 검증 실패 (잘못된 범위/형식 등)"},
}


@router.get(
    "/summary",
    response_model=PersonalDashboardSummary,
    summary="내 대시보드 KPI 요약 (본인 자산만)",
    responses=_USER_ERRORS,
)
def get_my_dashboard_summary(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """현재 로그인 사용자가 만든 8개 도메인 자산 카운트.

    ## 응답 구성
    - `member_id` — 현재 사용자 식별자
    - **services / workflows / models / model_improvements / datasets / experiments
      / knowledge_bases / prompts** — 본인 `created_by` 자산만 집계한 `AssetCount`
    - `generated_at` — 응답 생성 시각 (UTC)

    ## 관리자 대시보드와의 차이
    - **본인 자산만** — admin이라도 이 endpoint는 본인 `created_by` 자산만 응답.
      전체 조회는 `GET /api/v1/admin/dashboard/summary` 사용.
    - `users` 섹션 없음 — 사용자 카운트는 admin 전용.
    - `infra` 섹션 없음 — 인프라는 admin 전용.

    ## AssetCount 의미
    - `active`   = `deleted_at IS NULL AND is_active IS TRUE` (soft-delete 없는 도메인은 = total)
    - `inactive` = `deleted_at IS NULL AND is_active IS FALSE`
    - `deleted`  = `deleted_at IS NOT NULL`
    - `total` = `active + inactive + deleted`

    > `service`, `workflow`는 soft-delete가 없어 항상 `inactive=0, deleted=0`.
    """
    return dashboard_service.build_summary_for_member(db, current_user.member_id)


# ============================================================
# 서비스 현황 카드 (이미지 ① 서비스 현황)
# ============================================================

@router.get(
    "/services",
    response_model=MyServiceCardsResponse,
    summary="내 서비스 현황 카드 (워크플로우 수 / 사용 모델 수)",
    responses=_USER_ERRORS,
)
async def get_my_service_cards(
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """본인이 만든 서비스별 현황 카드.

    ## 응답 `services[]` 항목
    | 필드 | 출처 | 설명 |
    |---|---|---|
    | `surro_service_id` | gateway DB | MLOps 서비스 UUID |
    | `name` / `description` | gateway DB (실시간) | 서비스 이름/설명 |
    | `workflow_count` | MLOps 캐시 | 연결 워크플로우 수 |
    | `model_count` | MLOps 캐시 | 사용 모델 distinct 수. 미집계 시 `null` (`DASHBOARD_INCLUDE_MODEL_COUNT=false`) |

    ## 캐싱 동작
    - 카드 수치(`workflow_count`/`model_count`)는 MLOps 호출이 필요해 **스냅샷 캐시**에서 제공.
    - 캐시가 없거나 `DASHBOARD_CACHE_TTL_MINUTES` 초과면 **이번 요청에서 본인 서비스만 즉시 집계**(`source=live`) 후 응답.
    - `source` ∈ `cache`(스냅샷) / `live`(즉시 집계) / `empty`(보유 서비스 없음).

    > 이름/설명은 항상 gateway DB 실시간 값. 캐시는 수치만 보관.
    """
    return await me_dashboard_service.get_my_cards(db, current_user)


# ============================================================
# 서비스 모니터링 (이미지 ② 서비스 모니터링 — 1h/1d/1w 전체)
# ============================================================

@router.get(
    "/monitoring",
    response_model=MyServiceMonitoringResponse,
    summary="내 서비스 모니터링 (메시지/사용자/토큰/상호작용, 1h·1d·1w)",
    responses=_USER_ERRORS_WITH_422,
)
async def get_my_service_monitoring(
    top_n: int = Query(5, ge=1, le=20, description="기간별 메트릭 순위 항목 수 (1~20, 기본 5)"),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """본인 서비스의 기간별(1h/1d/1w) 모니터링 메트릭 + 메트릭별 Top N 순위.

    ## 응답 구성
    - `services[]` — 서비스별 전체 기간 메트릭
        - `metrics` — `{ "1h": {...}, "1d": {...}, "1w": {...} }`
            - 각 기간: `message_count`, `active_users`, `token_usage`, `avg_interaction_count`,
              `response_time_ms`(null 가능), `error_count`, `success_rate`(null 가능)
        - `aggregated_at` — MLOps 집계 기준 끝점
    - `top` — 기간별 Top N 순위 (이미지의 4개 위젯에 대응)
        - `top["1d"].message_count` = 1일 기준 총 메시지 수 상위 N개 `[{surro_service_id, name, value}, ...]`
        - 메트릭: `message_count` / `active_users` / `token_usage` / `avg_interaction_count`
    - `source` ∈ `cache` / `live` / `empty`

    ## 캐싱 동작
    메트릭은 MLOps 서비스 detail(서비스 수만큼 N+1)에서 오므로 **스냅샷 캐시** 우선.
    캐시 미스/`DASHBOARD_CACHE_TTL_MINUTES` 초과 시 본인 서비스만 즉시 집계 후 응답.

    ## 비고
    - 데이터 없는 서비스/기간은 0으로 채워져 순위 하단에 포함됩니다 (서비스 누락 방지).
    - 값의 신뢰성은 MLOps 집계 파이프라인 상태에 의존합니다.
    """
    return await me_dashboard_service.get_my_monitoring(db, current_user, top_n=top_n)


# ============================================================
# 활동 히스토리 (이미지 ④ 이벤트 대체 — 사용자 작업 이력)
# ============================================================

@router.get(
    "/activities",
    response_model=MyActivityListResponse,
    summary="내 작업 이력 (서비스/워크플로우 생성·수정·삭제·상태변경 등)",
    responses=_USER_ERRORS_WITH_422,
)
def get_my_activities(
    page: int = Query(1, ge=1, description="페이지 번호 (1부터)"),
    size: int = Query(20, ge=1, le=200, description="페이지 크기 (1~200)"),
    resource_type: Optional[str] = Query(
        None,
        description=(
            "대상 도메인 필터. 허용 값: `service`, `workflow`, `model`, `model_improvement`, "
            "`dataset`, `experiment`, `knowledge_base`, `prompt`. 미지정 시 전체."
        ),
    ),
    action: Optional[str] = Query(
        None,
        description="액션 필터. 허용 값: `create`, `update`, `delete`, `restore`, `status_change` 등. 미지정 시 전체.",
    ),
    since: Optional[datetime] = Query(None, description="이 시각(UTC) 이후만. ISO 8601."),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    """본인이 UI에서 수행한 작업(서비스/워크플로우 등 생성·수정·삭제·상태변경) 시계열.

    k8s pod 이벤트(인프라) 대신, 사용자 관점의 대표 작업 이력을 제공합니다.

    ## 정렬 / 페이지네이션
    - 정렬: `created_at DESC, id DESC` (최신순). 변경 불가.
    - public pagination 규약 `{ data, total, page, size }`.

    ## 응답 `data[]` 항목
    | 필드 | 타입 | 설명 |
    |---|---|---|
    | `id` | int | 내부 PK |
    | `action` | string | `create`/`update`/`delete`/`restore`/`status_change` 등 |
    | `resource_type` | string | `service`/`workflow`/... 대상 도메인 |
    | `resource_id` | string \\| null | gateway PK 또는 surro id |
    | `metadata` | object \\| null | 액션별 부가 JSON (예: `{"name":"..."}`, 상태변경 시 `{"from":...,"to":...}`) |
    | `created_at` | datetime | 작업 시각 (UTC) |

    ## UI 처리 팁
    - 상태변경(`status_change`)의 `metadata.from/to`로 "배포/중단/종료" 등을 라벨링.
    - `action`별 색상/아이콘 매핑 권장.
    """
    rows, total = me_dashboard_service.get_my_activities(
        db,
        current_user.member_id,
        page=page,
        size=size,
        resource_type=resource_type,
        action=action,
        since=since,
    )
    items = [MyActivityItem.model_validate(r) for r in rows]
    return MyActivityListResponse(data=items, total=total, page=page, size=size)
