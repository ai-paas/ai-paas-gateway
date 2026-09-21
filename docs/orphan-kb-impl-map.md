# 고아 KB 대응 — 코드 변경 지도

`docs/orphan-kb-plan.md` 의 동반 문서. 계획서가 **무엇을 왜** 라면, 이 문서는 **어느 파일의
어디를 어떻게** 다. 구현 전 학습·리뷰용이며, 줄 번호는 `f68e862` 시점 기준이다.

## 0. 한눈에 보기

| 파일 | | Step | 들어가는 것 |
|---|---|---|---|
| `app/models/knowledge_base.py` | 수정 | 2 | `KnowledgeBaseCreateAttempt` 모델 |
| `alembic/versions/<new>_add_kb_create_attempts.py` | 신규 | 2 | 테이블·인덱스 |
| `app/cruds/knowledge_base.py` | 수정 | 1·2·4·5 | 시도 CRUD, `is_protected`, 고아 집합 계산 |
| `app/config.py` | 수정 | 2 | 파라미터 3개 + 불변식 검증 |
| `app/schemas/knowledge_base.py` | 수정 | 1 | admin 고아 응답 스키마 |
| `app/routes/knowledge_base.py` | 수정 | 1·3·4·6 | **네 군데** (아래 2.6) |
| `app/scheduler.py` 또는 별도 워커 | 수정/신규 | 5 | 정리 잡 |
| `tests/test_knowledge_base_orphan.py` | 신규 | 전부 | 회귀 테스트 |
| `docs/api-reference.md` | 생성물 | 6 | `scripts/gen_api_docs.py` 로 재생성 |
| `app/services/knowledge_base_service.py` | **건드리지 않음** | 0 | 이슈 1 소유 |

수정 7개 + 신규 3개. 그중 **실질적인 난이도는 라우트 한 파일에 몰려 있다.**

## 1. 변경 전 코드 읽기

### 1.1 고아가 태어나는 자리

[app/routes/knowledge_base.py:444-479](../app/routes/knowledge_base.py#L444-L479)

```python
    user_info = _user_info(current_user)

    external_kb = await knowledge_base_service.create_knowledge_base(   # 446  ← 여기서 타임아웃
        name=name, description=description, file=file, ...
    )

    try:
        db_kb = knowledge_base_crud.create_knowledge_base(              # 462  ← 카드 저장
            db=db,
            name=external_kb.name,
            created_by=current_user.member_id,
            surro_knowledge_id=external_kb.id,                          #      ← 이 값이 핵심
            collection_name=external_kb.collection_name,
        )
        ...
    except Exception as mapping_error:
        logger.error(f"Failed to create knowledge base: {str(mapping_error)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Knowledge base created in external API but failed to save: ...",  # 478
        )
```

읽을 때 세 가지를 같이 봐야 한다.

1. **446이 실패하면 462는 아예 실행되지 않는다.** 예외가 그대로 위로 올라가므로 `try` 블록에
   도달하지 못한다. 게이트웨이는 `external_kb.id` 를 **한 번도 보지 못한 채** 끝난다.
2. **478의 문구는 이미 이 문제를 인정하고 있다.** "외부에는 만들어졌는데 저장은 실패했다" —
   이 경로로도 똑같이 고아가 생긴다. 다만 이쪽은 `external_kb.id` 를 손에 쥐고 있다는 차이가
   있어, 고아라는 결과는 같아도 남길 수 있는 정보량이 다르다.
3. **소유자 정보는 `current_user.member_id` 하나뿐이다.** 업스트림은 소유자를 저장하지 않으므로
   (계획서 3.1), 이 값을 잃으면 나중에 어디서도 복원할 수 없다.

### 1.2 복구를 얹을 자리

[app/routes/knowledge_base.py:552-584](../app/routes/knowledge_base.py#L552-L584)

```python
    try:
        external_kbs = await knowledge_base_service.get_knowledge_bases(...)   # 553
        external_kb_map = {kb.id: kb for kb in external_kbs}                   # 554
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=...)

    response_data = []
    for kb in knowledge_bases:
        external_kb = external_kb_map.get(kb.surro_knowledge_id)
        response_data.append(KnowledgeBaseResponse(
            ...
            name=kb.name,                      # 574  ← 로컬 값
            description=kb.description,        # 575  ← 로컬 값
            chunk_size=external_kb.chunk_size if external_kb else None,   # 업스트림 값
            ...
        ))
```

**554의 `external_kb_map` 이 이 설계의 출발점이다.** 목록 조회는 이미 매 요청마다 업스트림 전체
목록을 받아 온다. 즉 "업스트림에 있는데 게이트웨이 매핑이 없는 KB" 를 계산할 재료가 **이미 이
함수 안에 있다.** Step 4가 별도 스케줄러 없이 성립하는 이유다.

부수적으로, 목록의 `name`/`description` 은 **로컬 행**에서 나오고 상세
([:618-619](../app/routes/knowledge_base.py#L618-L619))는 **업스트림**에서 나온다는 비대칭도
여기서 확인된다. 검토 과정에서 "이름에 복구 표시를 달자" 안을 접은 근거가 이것이다.

## 2. 파일별 변경

### 2.1 `app/models/knowledge_base.py` — 모델 추가

기존 `KnowledgeBase` 는 손대지 않고 클래스 하나를 아래에 붙인다.

```python
class KnowledgeBaseCreateAttempt(Base):
    __tablename__ = "knowledge_base_create_attempts"

    id = Column(Integer, Sequence("kb_create_attempts_id_seq"), primary_key=True, autoincrement=True)

    member_id  = Column(String(100), ForeignKey("members.member_id"), nullable=False)
    name       = Column(String(255), nullable=False)
    filename   = Column(String(512), nullable=True)
    request_id = Column(String(64), nullable=True)

    upstream_snapshot = Column(JSON, nullable=True, comment="POST 직전 업스트림 KB id 집합")
    state             = Column(String(32), nullable=False, index=True)
    failure_kind      = Column(String(64), nullable=True)

    started_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    resolved_surro_id = Column(Integer, nullable=True)
    recovered_at      = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_kb_attempts_live", "state", "started_at"),
        Index("idx_kb_attempts_dedup", "member_id", "name", "filename", "state"),
    )
```

**계획서의 `JSONB` 는 `JSON` 으로 내려야 한다.** 이 저장소의 테스트는 기본이 sqlite 인메모리이고
([tests/conftest.py:31](../tests/conftest.py#L31)), 모델들도 전부 portable 한 `JSON` 을 쓴다
([any_cloud.py:21](../app/models/any_cloud.py#L21), [audit_log.py:28](../app/models/audit_log.py#L28)).
PostgreSQL 전용 타입을 쓰려면 `with_variant` 로 방언을 나눠야 하는데, 스냅샷은 id 배열이라 JSONB 의
인덱싱 이점을 쓸 일이 없다. 굳이 나눌 이유가 없다.

인덱스 두 개의 용도가 다르다는 점도 봐 두자. `idx_kb_attempts_live` 는 `is_protected` 와 Step 5가
"살아 있는 시도" 를 훑을 때, `idx_kb_attempts_dedup` 은 **조건 6**(같은 이름·파일의 성공한
재시도 찾기)이 쓴다.

사소하지만 놓치기 쉬운 것 — 이 파일의 `from sqlalchemy import ...` 줄에 `JSON` 이 아직 없다.
같이 추가해야 한다.

### 2.2 `alembic/versions/<new>_add_kb_create_attempts.py` — 마이그레이션

```python
down_revision = "e60718293a4b"   # 현재 head
```

`alembic/versions/` 의 파일명 규칙(`<rev>_<snake_case_설명>.py`)을 따른다. 작업 중 다른 PR 이
먼저 머지되면 head 가 바뀌므로, **머지 직전에 `alembic heads` 가 단일인지 다시 확인**해야 한다.
계획서 Step 2의 검증 항목이 이것이다.

### 2.3 `app/cruds/knowledge_base.py` — 판정 로직의 집

기존 `KnowledgeBaseCRUD` 클래스에 메서드를 더하거나 시도 전용 CRUD 를 새로 만든다. 어느 쪽이든
**`is_protected` 는 반드시 한 군데에만 존재해야 한다.**

```python
def get_live_attempts(self, db, now) -> list[KnowledgeBaseCreateAttempt]:
    """orphan_suspect 이면서 ATTEMPT_TTL 이내인 시도"""

def is_protected(self, kb, live_attempts) -> bool:
    """이 업스트림 KB 를 후보로 삼을 수 있는 살아 있는 시도가 있는가"""
    for t in live_attempts:
        if t.upstream_snapshot is None:      # 스냅샷 없으면 후보 계산 불가
            continue
        if kb.id in t.upstream_snapshot:     # 시도 이전부터 있던 KB
            continue
        if not (t.started_at <= kb.created_at <= t.started_at + MAX_INGEST):
            continue                         # 복구 창 밖 → 보호해도 복구되지 않는다
        return True
    return False

def find_duplicate_success(self, db, attempt) -> Optional[int]:
    """조건 6 — 같은 member/name/filename 으로 성공했고 매핑이 아직 active 인 시도"""
```

`is_protected` 를 CRUD 에 두는 이유는 **호출자가 둘**이기 때문이다. Step 1(관리자 삭제)과
Step 5(자동 정리)가 각자 구현하면 나중에 한쪽만 고쳐지는 사고가 난다. 계획서가 이걸 "공통 규칙"
으로 따로 떼어 놓은 이유다.

`find_duplicate_success` 는 시도 테이블과 로컬 매핑만 본다. **업스트림 호출이 없다** — 조건 6이
싼 이유이자, 프론트 작업 없이 중복 문제를 없앨 수 있는 이유다.

### 2.4 `app/config.py` — 파라미터와 불변식

[app/config.py:102](../app/config.py#L102) 의 `PROXY_KB_INGEST_TIMEOUT` 바로 아래에 붙인다.

```python
    KB_ATTEMPT_TTL_MINUTES: int = int(os.getenv("KB_ATTEMPT_TTL_MINUTES", "1440"))
    PROXY_KB_ORPHAN_TTL_MINUTES: int = int(os.getenv("PROXY_KB_ORPHAN_TTL_MINUTES", "10080"))
    KB_MAX_INGEST_SECONDS: int = int(os.getenv("KB_MAX_INGEST_SECONDS", "3600"))
```

검증은 [`Settings.__init__`](../app/config.py#L154) 에 추가한다. 이 저장소는 pydantic-settings 가
아니라 **평범한 클래스 + `__init__` 에서 `ValueError`** 방식이다.

```python
        if self.KB_ATTEMPT_TTL_MINUTES >= self.PROXY_KB_ORPHAN_TTL_MINUTES:
            raise ValueError("KB_ATTEMPT_TTL_MINUTES must be less than PROXY_KB_ORPHAN_TTL_MINUTES")
```

모듈 로드 시점에 `settings = Settings()` 가 실행되므로, 이 부등식이 깨지면 **애플리케이션이
기동하지 않는다.** 잘못된 설정으로 복구 가능한 KB 가 먼저 삭제되는 것보다 기동 실패가 낫다는
판단이다.

### 2.5 `app/schemas/knowledge_base.py` — admin 응답

```python
class OrphanKnowledgeBaseItem(BaseModel):
    surro_knowledge_id: int
    name: str
    collection_name: str
    created_at: Optional[datetime]
    is_protected: bool                       # 목록에 그대로 노출
    protected_by: Optional[str]              # 예: "kim.dev (10:00 시도)"


class OrphanKnowledgeBaseListResponse(BaseModel):
    data: List[OrphanKnowledgeBaseItem]
    total: int
```

`is_protected` 를 **응답에 싣는 것**이 포인트다. 관리자가 "곧 주인이 정해질 KB" 를 고아로 오인해
지우는 걸 막는 유일한 장치다.

### 2.6 `app/routes/knowledge_base.py` — 네 군데

가장 많이 바뀌는 파일. 서로 독립적인 변경 네 개가 한 파일에 들어간다.

#### (1) Step 3 — create 라우트 배선 (446 앞뒤)

```python
    user_info = _user_info(current_user)

    # --- 추가: 스냅샷 + 시도 레코드 (별도 세션) ---
    snapshot = await _try_snapshot(user_info)          # 실패하면 None, 생성은 계속 진행
    attempt_id = attempt_crud.create_pending(
        member_id=current_user.member_id, name=name,
        filename=file.filename, upstream_snapshot=snapshot,
        request_id=request.state.request_id,   # middleware.py:20 에서 항상 세팅된다
    )

    try:
        external_kb = await knowledge_base_service.create_knowledge_base(...)   # 446
    except HTTPException as e:
        attempt_crud.finish(attempt_id, state=_classify(e.status_code),
                            failure_kind=str(e.status_code))
        raise

    try:
        db_kb = knowledge_base_crud.create_knowledge_base(...)                  # 462
        attempt_crud.finish(attempt_id, state="succeeded", resolved_surro_id=external_kb.id)
    except Exception as mapping_error:
        attempt_crud.finish(attempt_id, state="orphan_suspect",
                            resolved_surro_id=external_kb.id)
        raise HTTPException(500, detail="... failed to save: ...")              # 478
```

**세 가지를 반드시 지켜야 한다.**

- **별도 세션(`SessionLocal()`)으로 커밋한다.** 라우트의 `db` 세션을 쓰면 매핑 write 실패 시
  롤백에 휩쓸려, 정작 기록이 필요한 순간에 시도 행이 사라진다. `app/scheduler.py` 가 쓰는
  `from app.database import SessionLocal` 패턴 그대로다. 생성만 분리하고 갱신을 라우트 세션에
  두면 `orphan_suspect` 로 바꾸는 그 write 가 함께 날아가므로, **양쪽 다** 분리해야 의미가 있다.
- **시도 레코드를 MLOps 호출보다 먼저 쓴다.** 이 쓰기가 실패하면 MLOps 를 호출하지 않고 끝난다.
  외부 부작용 없이 실패하는 순서다.
- **분류는 `HTTPException.status_code` 만 본다.** 서비스 레이어는 이슈 1 소유라 건드리지 않는다.
  이슈 1이 503/502/504 를 정확히 세팅하면 이쪽 분류가 자동으로 정확해지는 구조다.

#### (2) Step 4 — list 라우트에 복구 얹기 (554 뒤)

```python
        external_kbs = await knowledge_base_service.get_knowledge_bases(...)   # 553
        external_kb_map = {kb.id: kb for kb in external_kbs}                   # 554

    # --- 추가 ---
    try:
        await _try_recover_orphans(db, current_user, external_kbs)
    except Exception:
        logger.exception("orphan recovery failed (list unaffected)")
```

`try/except` 로 통째로 감싸는 게 핵심이다. 부가 기능이 주 기능을 깨면 사용자가 KB 목록 자체를
못 본다. 같은 패턴이 이미
[dataset.py:369-381](../app/routes/dataset.py#L369-L381) 의 `backfill_cache_if_changed` 에 있다.

구현 시 정할 것이 하나 있다. 복구가 매핑을 만들어도 **이미 조회해 둔 로컬 목록에는 반영되지
않는다.** 복구 후 로컬 목록을 다시 조회할지, 다음 요청으로 미룰지를 골라야 한다. 다시 조회하는
쪽이 사용자 경험은 낫고, 미루는 쪽이 단순하다.

#### (3) Step 1 — admin 라우트 2개 추가

```python
@router.get("/admin/orphans", response_model=OrphanKnowledgeBaseListResponse)
async def list_orphans(db=Depends(get_db), current_user=Depends(get_current_admin_user)):
    ...

@router.delete("/admin/orphans/{surro_id}")
async def delete_orphan(surro_id: int, force: bool = Query(False), ...):
    ...
```

**경로 등록 순서에 함정이 있다.** 이 라우터에는 이미
`@router.get("/{surro_knowledge_id}")` ([:587](../app/routes/knowledge_base.py#L587))가 있다.
FastAPI 는 등록 순서대로 매칭하므로 `/admin/orphans` 를 그 **뒤**에 등록하면 `admin` 이
`surro_knowledge_id` 로 파싱되려다 422 가 난다. 정적 경로를 먼저 등록해야 한다.

`get_current_admin_user` 는 [app/auth.py:128](../app/auth.py#L128) 에 이미 있고, 감사로그는
`emit_from_request(db, request, action=Action.DELETE, resource_type=ResourceType.KNOWLEDGE_BASE, ...)`
를 그대로 쓴다 — 라우트 상단에서 이미 import 되어 있다. 새로 만들 것이 없다.

#### (4) Step 6 — Swagger 문구

[:168](../app/routes/knowledge_base.py#L168) 의 "목록에 없으면 관리자에게 확인 요청" 을 실제 admin
경로 안내로 교체한다. 지금 문구는 사용자에게는 정확하지만, 정작 관리자가 확인할 방법이 없었다.

### 2.7 Step 5 — 자동 정리

[app/scheduler.py:145-176](../app/scheduler.py#L145-L176) 의 workflow reconcile 잡이 거의 그대로
본이 된다. 읽어볼 값어치가 있다.

```python
        external = asyncio.run(_fetch())
        if not external:
            # 빈 응답을 "전부 삭제됨"으로 해석하면 안 된다.
            logger.warning("[scheduler] workflow reconcile skipped (upstream returned no workflows)")
            return
```

**업스트림 빈 응답 가드**가 이 저장소의 확립된 관례다. 고아 정리에서 이걸 빠뜨리면 업스트림
장애 한 번에 전체 KB 를 지운다. 같이 볼 것 — `db = SessionLocal()` / `try` / `finally: db.close()`
구조, `deleted_by="system:..."` 행위자 표기.

다만 `ENABLE_SCHEDULER` 는 기본 false 이고 in-process 단일 워커 가정이므로
([config.py:116-117](../app/config.py#L116-L117)), 운영에서 실제로 무엇이 이 잡을 돌릴지는
계획서 7장 4번의 미결 항목이다.

### 2.8 `tests/test_knowledge_base_orphan.py`

기존 `tests/test_knowledge_base_timeout.py` 가 타임아웃 주입 패턴을 이미 갖고 있으므로 그걸
본으로 삼는다. 계획서 각 Step 의 "검증:" 줄이 그대로 테스트 목록이다.

## 3. 건드리지 않는 파일

`app/services/knowledge_base_service.py` 는 **이슈 1 소유**다. 타임아웃·연결 오류의 상태코드
매핑(`_raise_kb_timeout`, [:37](../app/services/knowledge_base_service.py#L37))이 그쪽 작업
범위라, 두 이슈가 같은 파일을 만지면 충돌한다.

작업 후 `git diff --name-only` 의 교집합이 `app/routes/knowledge_base.py` 뿐이어야 한다.

## 4. 이 변경에서 배울 만한 패턴

1. **"외부 먼저, 로컬 나중" 의 수렴성** — create 와 delete 는 순서가 같은데 결과가 반대다.
   delete 는 로컬 카드가 남아 재시도가 수렴하지만, create 는 카드가 없어 영구 고아가 된다.
   외부 부작용과 로컬 기록의 순서를 정할 때 **"중간에 끊기면 재시도로 수렴하는가"** 를 먼저 묻는
   습관이 이 사건의 교훈이다.
2. **세션 분리** — 기록이 목적인 write 는 주 트랜잭션과 생사를 같이하면 안 된다.
3. **빈 응답 가드** — "업스트림이 아무것도 안 줬다" 를 "전부 없어졌다" 로 읽지 않는다.
4. **부가 기능 격리** — 목록 조회에 얹은 복구가 목록 조회를 죽이면 안 된다.
5. **fail-closed 판정** — 조건을 늘릴수록 복구율은 떨어지지만 오매칭은 0에 수렴한다. 권한 근거를
   만들어 내는 로직에서는 이 방향이 맞다.
6. **설정 불변식은 기동 시점에 강제** — 런타임에 조용히 어긋나도록 두지 않는다.

## 5. 머지 단위 제안

| # | 범위 | 단독 배포 | 비고 |
|---|---|---|---|
| 1 | 2.5 + 2.6(3) — admin 조회·삭제 | 가능 | 시도 테이블이 없어 `is_protected` 는 항상 거짓 |
| 2 | 2.1 + 2.2 + 2.3 + 2.4 — 테이블·CRUD·설정 | 가능 | 아직 아무도 쓰지 않는다 |
| 3 | 2.6(1) — create 배선 | 가능 | 여기부터 시도가 쌓인다 |
| 4 | 2.6(2) — 자동 복구 | 3 필요 | |
| 5 | 2.7 — 자동 정리 (dry-run) | 1·2 필요 | 실삭제는 확인 후 별도로 켠다 |
| 6 | 2.6(4) — Swagger | 마지막 | `gen_api_docs.py --check` 통과 확인 |

**1번과 2번 사이에 함정이 있다.** 1번을 단독 배포한 구간에서는 보호 대상이 없어 안전하지만,
2번이 들어오는 순간 1번이 `is_protected` 를 참조하도록 **함께 배선해야 한다.** 이 배선을
빠뜨리면 관리자 삭제가 복구 가능한 KB 를 지우는 결함이 그대로 남는다.
