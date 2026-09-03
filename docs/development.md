# 개발 가이드

## 프로젝트 구조

```
.
├── app/
│   ├── main.py, config.py, database.py, auth.py
│   ├── middleware.py, logging_config.py, scheduler.py
│   ├── common/sort.py
│   ├── routes/      # auth, member, service, workflow, dataset, learning,
│   │                # model, model_improvement, prompt, knowledge_base,
│   │                # hub_connect, any_cloud, dashboard, me_dashboard
│   ├── services/    # provider 통합 + 대시보드/메트릭/감사/트렌드 서비스
│   ├── cruds/       # 도메인별 DB CRUD
│   ├── schemas/     # Pydantic 요청/응답
│   └── models/      # SQLAlchemy ORM (18 테이블)
├── alembic/versions/   # 마이그레이션 14개
├── scripts/            # 공유 개발 도구 (sync_models, sync_datasets, seed_gateway_samples)
├── tests/              # pytest 스위트
├── Dockerfile, docker-compose.yml, docker-compose.test.yml, run.sh
├── requirements.txt, pytest.ini, alembic.ini
└── .env.example, .editorconfig
```

`scripts/` 규약: 커밋 대상 도구는 `scripts/` 직하, 로컬 전용 스크립트·덤프·토큰은 `.gitignore`된 `scripts/local/` 하위. 상세는 `scripts/README.md`.

## 새 도메인 추가

1. `app/models/{domain}.py` — ORM 모델 (매핑 + soft delete 필드)
2. `app/schemas/{domain}.py` — Pydantic 스키마
3. `app/cruds/{domain}.py` — CRUD (소유자 조건 포함)
4. `app/services/{domain}_service.py` — provider 연동 (필요 시)
5. `app/routes/{domain}.py` — `APIRouter(prefix="/{domain}s", tags=["{Domain}"])`
6. `app/main.py`에 `include_router` 등록
7. `alembic revision --autogenerate -m "..."` → `alembic upgrade head`
8. `tests/`에 라우트·CRUD 테스트 추가
9. `python scripts/gen_api_docs.py` — `docs/api-reference.md` 갱신 (새 태그는 스크립트의 `SECTIONS`에 추가)

라우트 표준 시그니처:

```python
@router.get("", response_model=DomainListResponse)
async def list_items(
    page: int = Query(1, ge=1, description="페이지 번호 (1부터 시작)"),
    size: int = Query(20, ge=1, le=100, description="페이지 크기"),
    sort: str | None = Query(None, description="정렬 (예: -created_at,name)"),
    db: Session = Depends(get_db),
    current_user: Member = Depends(get_current_user),
):
    ...
```

## 문서

- `README.md`은 저장소 랜딩 페이지다. 소개·빠른 시작·문서 색인만 두고, 상세는 `docs/`로 내린다.
- `docs/api-reference.md`는 **생성물**이다. 직접 고치지 말고 `python scripts/gen_api_docs.py`를 돌린다.
  커밋 전 `--check`로 최신 여부를 확인할 수 있다.
- 요청/응답 스키마의 단일 소스는 Swagger UI(`/docs`)다. 마크다운에 스키마를 복제하지 않는다.
- 내부 공유용·임시 문서는 `docs/temp/`(gitignored)에 둔다.

## 마이그레이션

```bash
alembic revision --autogenerate -m "변경사항 설명"
alembic upgrade head
alembic downgrade -1
alembic heads
```

## 커밋 메시지

기존 히스토리 형식을 따른다: `이모지 + type(scope): 한국어 설명`, 변경 건당 한 줄.
사용 이모지: ✨ feat / 🔧 fix·refactor / 📝 docs / 📦 chore / ⚡️ update / ✅ test / 🗑️ delete / 🗃️ migration

## 보안

- 이 저장소는 public이다. JWT·평문 비밀번호·공인 IP를 코드·문서·테스트에 하드코딩하지 않고 `.env`(gitignored)로만 주입한다.
- `.env.example`에는 placeholder만 둔다.

## 알려진 제약

| 항목 | 내용 |
|---|---|
| 토큰 blacklist | `app/auth.py`의 `TOKEN_BLACKLIST`가 프로세스 메모리 기반이라 멀티 워커/재시작 시 공유되지 않는다. 즉시 무효화가 실효성 있게 필요하면 외부 저장소가 필요하다. |
| 인프라 대시보드 | `/admin/dashboard/infra/*` 3종은 Any Cloud 연동 확정 전까지 `app/services/infra_adapter.py`의 mock 응답을 반환한다(`_USE_MOCK`). |
| 페이지네이션 helper 중복 | `app/routes/model.py`, `app/routes/learning.py`, `app/routes/dataset.py`에 도메인 로컬 `_create_pagination_response()`가 남아 있다(공용화 대상). |
| Hub Connect 목록 | `GET /hub-connect/models`만 허브 원본 호환을 위해 `limit`을 public 파라미터로 노출한다. |
| 워크플로우 추론 endpoint | `POST /workflows/{id}/models/{component_id}/inference`는 MLOps v2에서 제거되어 410을 반환한다. |
| DB 드리프트 | 개발 DB 일부 테이블은 Alembic baseline 이전에 생성되어, `upgrade head`가 성공해도 실제 컬럼 폭/nullable이 ORM 정의와 다를 수 있다(`d5f60718293a`, `e60718293a4b`에서 정렬). |
