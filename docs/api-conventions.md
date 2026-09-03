# API 규약

## 인증 / 인가

- **토큰**: HS256 JWT. Access Token(기본 30분) + Refresh Token(기본 7일).
- **Refresh Token 전달**: 응답 본문 + httpOnly 쿠키(`AUTH_REFRESH_COOKIE_*`로 name/secure/samesite/path 제어).
- **Swagger 로그인**: `POST /api/v1/auth/token` (OAuth2 password flow, `username` 필드에 `member_id` 입력).
- **로그아웃**: 프로세스 로컬 blacklist(`app/auth.py`의 `TOKEN_BLACKLIST`)에 토큰 등록 + refresh 쿠키 삭제.
- **역할**: `members.role` = `admin` | `user` (기본 `user`).

| 권한 유형 | 판정 방식 |
|---|---|
| 공개 | `/`, `/health`, `/api/v1/auth/login`, `/auth/token`, `/auth/refresh`, `/auth/logout` |
| 인증 | `Depends(get_current_user)` — 유효한 access token 필요 |
| 관리자 | `Depends(get_current_admin_user)` — `role == "admin"` |
| 소유자 (403) | 라우트 내부에서 `current_user.role != "admin" and 리소스.created_by != current_user.member_id` → 403. 관리자는 우회. services, workflows, knowledge_bases |
| 소유자 (404) | CRUD 소유권 조회(`check_*_ownership`)가 실패하면 존재 여부를 숨기고 404 `"not found or access denied"`. 관리자 우회 없음. datasets, models, learning |
| upstream 위임 | 게이트웨이는 소유권을 검사하지 않고 사용자 컨텍스트 헤더만 전달해 upstream 판정을 따른다. prompts 상세/수정/삭제, workflow 템플릿 상세/수정/삭제 |
| 본인 또는 관리자 | `check_member_access(current_user, member_id)` — members 도메인 |
| WebSocket | `Depends(get_ws_admin_user)` — 핸드셰이크 단계에서 검증. 브라우저는 헤더를 못 붙이므로 `new WebSocket(url, ["bearer", accessToken])` 서브프로토콜, 서버-서버는 `Authorization: Bearer`. 토큰을 query string에 싣지 않는다 |

> `learning`은 관리자 요청 시 상세/삭제 전에 `_sync_external_experiments_for_admin()`으로 미매핑 upstream 실험을 admin 소유로 동기화한 뒤 소유권을 검사한다. 모델도 미매핑 upstream 모델을 admin 소유로 동기화하는 경로(`scripts/sync_models.py`)를 별도로 갖는다.

## 페이지네이션

- 요청: `page` (≥1, 기본 1), `size` (1~100, 기본 20)
- 응답: `{ "data": [...], "total": int, "page": int, "size": int }`
- upstream의 `page_size`/`limit`/`offset`/`items`/`results`는 service adapter 내부에서 변환하며 public 스펙에 노출하지 않는다.
- 예외: `GET /api/v1/hub-connect/models`는 허브 원본 호환을 위해 `page` + `limit`을 그대로 노출한다.
- `GET /api/v1/datasets`는 `has_more`, `total_is_exact`를 추가로 반환한다(upstream total이 부정확할 수 있음).
- any-cloud 목록은 `{ data, total, page, size, total_pages, has_next, nextPageToken, degraded* }`를 반환한다.
  - **다음 페이지 판단은 `has_next` 하나만 보면 된다** — offset/cursor 두 모드 공통.
  - `GET /any-cloud/kubernetes/{resource_type}`만 cursor 모드다. K8s가 총계를 주지 않으므로 `total`은 현재 페이지 건수이고 `total_pages`는 의미가 없다. 다음 페이지는 응답의 `nextPageToken`을 요청의 `pageToken`으로 되돌려 보낸다(예외 표에 등록된 pass-through).
  - `degraded` / `degradedReason` / `degradedMessage`가 실리면 에이전트 장애로 인한 부분 가용이다. `data`가 비어도 "리소스 없음"이 아니다.
  - `GET /any-cloud/monit/{cluster_name}/query`·`query_range`의 `limit`은 페이지네이션이 아니라 Prometheus 쿼리 옵션이다.

## 정렬

- 공통 파서: `app/common/sort.py`
- 형식: `sort=-created_at,name` (`-` 접두사 = DESC)
- 허용 필드 화이트리스트 검증, 빈 토큰·중복 필드는 422, 페이지 경계 안정화를 위한 tie-breaker 자동 부가, NULL은 항상 마지막.
- 지원: members, services, workflows, datasets, models, prompts, knowledge-bases, learning, hub-connect

## 삭제 정책

- 매핑 테이블 8종(services, workflows, models, datasets, prompts, knowledge_bases, experiments, model_improvements)은 **soft delete** (`deleted_at`, `deleted_by`, `is_active`).
- `DELETE /api/v1/members/{member_id}`는 **하드 삭제**.
- 워크플로우 삭제/정리는 upstream 리소스 회수를 위해 2단계(`DELETE` → `finalize-deletion`, `cleanup` → `finalize-cleanup`).

## 감사 로그 · 요청 로깅

- `app/services/audit_service.py`가 `audit_logs`에 생성/수정/삭제/복구/로그인/로그아웃/권한변경 이벤트를 기록한다. 감사 기록 실패가 본 요청을 깨지 않는다(best-effort).
- `RequestLoggingMiddleware`는 요청마다 `X-Request-ID`를 부여·응답 헤더에 반영하고, access 로그를 남기며 응답시간을 in-process 버퍼에 적재한다(`LOG_ACCESS_MASK_PATHS`에 등록된 경로는 member_id·query를 마스킹).
