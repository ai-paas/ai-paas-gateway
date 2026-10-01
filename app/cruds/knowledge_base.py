import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.config import settings
from app.database import SessionLocal
from app.models.knowledge_base import AttemptState, KnowledgeBase, KnowledgeBaseCreateAttempt


# pg_try_advisory_xact_lock 의 첫 인자. 다른 기능이 같은 정수로 락을 잡아 무관한 두 작업이
# 서로를 기다리는 일이 없도록, KB 전용 네임스페이스를 고정한다.
_KB_ADVISORY_LOCK_NAMESPACE = 0x4B42  # 'KB'

# 여기 도달한 시도는 결말이 났다. 되돌아가는 전이를 허용하면 포기시킨 시도가 되살아난다.
_TERMINAL_ATTEMPT_STATES = (
    AttemptState.SUCCEEDED,
    AttemptState.ABANDONED,
    AttemptState.RECOVERED,
)


def _as_aware(value: Optional[datetime]) -> Optional[datetime]:
    """naive datetime 을 UTC 로 간주해 aware 로 맞춘다.
    started_at 은 timestamptz(aware)인데 업스트림 응답의 created_at 은 
    타임존 없이 올 수 있어, 그대로 비교하면 TypeError 가 난다.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


class KnowledgeBaseCRUD:
    def create_knowledge_base(
            self,
            db: Session,
            name: str,
            description: Optional[str],
            created_by: str,
            surro_knowledge_id: int,
            collection_name: str
    ):
        """지식베이스 생성 - surro_knowledge_id만 저장 (중복 매핑 처리 포함)"""
        # 활성 ID가 다른 이름을 가리키면 재설치 후 ID 재사용으로 보고 이력을 분리한다.
        existing = self.get_active_knowledge_base_by_surro_id(db, surro_knowledge_id)
        if existing:
            if name and existing.name != name:
                logger.info(
                    f"Retiring reused knowledge base mapping: surro_id={surro_knowledge_id}, "
                    f"old_name={existing.name}, new_name={name}"
                )
                now = datetime.utcnow()
                existing.deleted_at = now
                existing.deleted_by = "system:upstream-id-reused"
                existing.is_active = False
                existing.updated_at = now
                db.flush()
            else:
                existing.description = description
                existing.collection_name = collection_name
                existing.updated_by = created_by
                existing.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(existing)
                return existing

        db_knowledge_base = KnowledgeBase(
            name=name,
            description=description,
            collection_name=collection_name,
            created_by=created_by,
            updated_by=created_by,
            surro_knowledge_id=surro_knowledge_id
        )
        db.add(db_knowledge_base)
        db.commit()
        db.refresh(db_knowledge_base)
        return db_knowledge_base

    def get_knowledge_base(self, db: Session, knowledge_base_id: int):
        return db.query(KnowledgeBase).filter(
            and_(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.is_active == True,
            )
        ).first()

    def get_knowledge_base_by_surro_id(self, db: Session, surro_knowledge_id: int):
        return db.query(KnowledgeBase).filter(
            KnowledgeBase.surro_knowledge_id == surro_knowledge_id
        ).order_by(KnowledgeBase.id.desc()).first()

    def get_active_knowledge_base_by_surro_id(self, db: Session, surro_knowledge_id: int):
        """삭제되지 않은 활성 지식베이스 조회"""
        return db.query(KnowledgeBase).filter(
            and_(
                KnowledgeBase.surro_knowledge_id == surro_knowledge_id,
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.is_active == True
            )
        ).first()

    def get_knowledge_bases(
            self,
            db: Session,
            skip: Optional[int] = None,
            limit: Optional[int] = None,
            search: Optional[str] = None,
            member_id: Optional[str] = None,
            order_by: Optional[list] = None,
    ):
        """지식베이스 목록 조회.

        `order_by` 미지정 시 `created_at DESC` 를 기본 적용한다.
        """
        query = db.query(KnowledgeBase).filter(
            and_(
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.is_active == True
            )
        )

        # 사용자별 필터링
        if member_id:
            query = query.filter(KnowledgeBase.created_by == member_id)

        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (KnowledgeBase.name.ilike(search_filter)) |
                (KnowledgeBase.description.ilike(search_filter)) |
                (KnowledgeBase.collection_name.ilike(search_filter))
            )

        total = query.count()
        if order_by:
            query = query.order_by(*order_by)
        else:
            query = query.order_by(KnowledgeBase.created_at.desc())

        if skip is not None and limit is not None:
            knowledge_bases = query.offset(skip).limit(limit).all()
        else:
            knowledge_bases = query.limit(10000).all()

        return knowledge_bases, total

    def update_knowledge_base_by_surro_id(
            self,
            db: Session,
            surro_knowledge_id: int,
            name: Optional[str] = None,
            description: Optional[str] = None,
            collection_name: Optional[str] = None,
            updated_by: Optional[str] = None
    ):
        db_kb = self.get_active_knowledge_base_by_surro_id(db, surro_knowledge_id)
        if db_kb:
            if name is not None:
                db_kb.name = name
            if description is not None:
                db_kb.description = description
            if collection_name is not None:
                db_kb.collection_name = collection_name
            if updated_by is not None:
                db_kb.updated_by = updated_by
            db_kb.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(db_kb)
        return db_kb

    def delete_knowledge_base_by_surro_id(
            self,
            db: Session,
            surro_knowledge_id: int,
            deleted_by: Optional[str] = None
    ):
        """지식베이스 매핑 소프트 삭제"""
        db_kb = self.get_active_knowledge_base_by_surro_id(db, surro_knowledge_id)
        if db_kb:
            db_kb.deleted_at = datetime.utcnow()
            db_kb.deleted_by = deleted_by
            db_kb.is_active = False
            db.commit()
            return True
        return False

    # === 생성 시도 레코드 관련 메서드 ===
    # 생성·갱신 모두 라우트의 db 세션을 쓰지 않는다. 매핑 write 가 실패해 롤백되면
    # 정작 기록이 필요한 순간에 시도 행이 함께 사라진다. 한쪽만 분리하면 의미가 없다.

    def create_attempt(
            self,
            member_id: str,
            name: str,
            filename: Optional[str],
            request_id: Optional[str],
    ) -> int:
        """MLOps 호출 전에 시도를 기록하고 id 를 돌려준다.

        이 쓰기가 실패하면 호출자는 MLOps 를 부르지 않고 종료해 외부 부작용 없이 실패한다.
        """
        db = SessionLocal()
        try:
            attempt = KnowledgeBaseCreateAttempt(
                member_id=member_id,
                name=name,
                filename=filename,
                request_id=request_id,
                state=AttemptState.PENDING,
            )
            db.add(attempt)
            db.commit()
            return attempt.id
        finally:
            db.close()

    def finish_attempt(
            self,
            attempt_id: int,
            state: str,
            resolved_surro_id: Optional[int] = None,
            failure_kind: Optional[str] = None,
    ) -> None:
        """시도를 종료 상태로 갱신한다. 실패해도 예외를 밖으로 내보내지 않는다."""
        db = SessionLocal()
        try:
            attempt = db.get(KnowledgeBaseCreateAttempt, attempt_id)
            if attempt is None:
                return
            if attempt.state in _TERMINAL_ATTEMPT_STATES:
                logger.info(
                    "Ignoring %s for already finished knowledge base create attempt %s (state=%s)",
                    state, attempt_id, attempt.state,
                )
                return
            attempt.state = state
            attempt.finished_at = datetime.now(timezone.utc)
            if resolved_surro_id is not None:
                attempt.resolved_surro_id = resolved_surro_id
            if failure_kind is not None:
                attempt.failure_kind = failure_kind
            db.commit()
        except Exception:
            logger.exception("Failed to update knowledge base create attempt %s", attempt_id)
            db.rollback()
        finally:
            db.close()

    def _live_attempts_query(self, db: Session, now: datetime):
        """아직 결말이 나지 않은 시도 — pending·orphan_suspect 이고 ATTEMPT_TTL 이내인 행."""
        cutoff = _as_aware(now) - timedelta(minutes=settings.KB_ATTEMPT_TTL_MINUTES)
        return db.query(KnowledgeBaseCreateAttempt).filter(
            and_(
                KnowledgeBaseCreateAttempt.state.in_(
                    (AttemptState.PENDING, AttemptState.ORPHAN_SUSPECT)
                ),
                KnowledgeBaseCreateAttempt.started_at >= cutoff,
            )
        )

    def get_live_attempts(
            self,
            db: Session,
            now: datetime,
    ) -> List[KnowledgeBaseCreateAttempt]:
        """삭제 보호 집합 — 아직 주인이 정해질 수 있는 모든 시도.
        자동 복구와 관리자 삭제가 이 집합을 공유한다. TTL 이 지나면 자동으로 제외된다.
        이 집합은 자동 복구 대상의 상위집합이다 — 복구는 복구 창이 열린 pending 을 빼지만,
        보호는 그 시도까지 포함한다. 범위를 맞추려고 보호를 줄이면 생성 중인 KB 가 지워진다."""
        return self._live_attempts_query(db, now).all()

    def try_lock_surro_knowledge_id(self, db: Session, surro_knowledge_id: int) -> bool:
        """업스트림 KB에 대한 트랜잭션 범위 advisory lock을 대기 없이 시도한다.

        자동 복구와 관리자 삭제의 판정·쓰기를 동기화하기 위한 락이다.
        락 경합 시 이벤트 루프를 blocking하지 않고 즉시 False를 반환한다.
        락은 현재 트랜잭션의 commit/rollback 시 해제된다.
        락 안의 재확인이 다른 세션의 커밋을 보려면 격리 수준이 READ COMMITTED 여야 한다(운영
        기본값). 그보다 높이면 재확인이 트랜잭션 시작 시점 스냅샷을 읽어 조용히 무력화된다.
        """
        # SQLite 테스트 환경에는 advisory lock 이 없다. 단일 커넥션이라 직렬화도 불필요하다.
        if db.bind is None or db.bind.dialect.name != "postgresql":
            return True
        return bool(
            db.execute(
                text("SELECT pg_try_advisory_xact_lock(:ns, :id)"),
                {"ns": _KB_ADVISORY_LOCK_NAMESPACE, "id": surro_knowledge_id},
            ).scalar()
        )

    def mark_recovered(self, attempt_id: int, surro_id: int) -> None:
        """자동 복구로 매핑이 붙은 시도를 recovered 로 올린다 (별도 세션)."""
        db = SessionLocal()
        try:
            attempt = db.get(KnowledgeBaseCreateAttempt, attempt_id)
            if attempt is None:
                return
            attempt.state = AttemptState.RECOVERED
            attempt.resolved_surro_id = surro_id
            attempt.recovered_at = datetime.now(timezone.utc)
            db.commit()
        except Exception:
            logger.exception("Failed to mark attempt %s recovered", attempt_id)
            db.rollback()
        finally:
            db.close()

    def get_recoverable_attempts(
            self,
            db: Session,
            member_id: str,
            now: datetime,
    ) -> List[KnowledgeBaseCreateAttempt]:
        """이 사용자의 복구 후보 시도 — orphan_suspect(또는 복구 창이 닫힌 pending) · TTL 이내."""
        cutoff = _as_aware(now) - timedelta(minutes=settings.KB_ATTEMPT_TTL_MINUTES)
        window_closed = _as_aware(now) - timedelta(seconds=settings.KB_MAX_INGEST_SECONDS)
        return db.query(KnowledgeBaseCreateAttempt).filter(
            and_(
                KnowledgeBaseCreateAttempt.member_id == member_id,
                or_(
                    KnowledgeBaseCreateAttempt.state == AttemptState.ORPHAN_SUSPECT,
                    # 강제 종료(배포 재시작의 SIGKILL 등)로 끝난 요청은 예외 경로를 타지 못해 pending 에
                    # 남는다. 복구 창이 닫혔으면 그 요청은 이미 끝났다 — 살아 있었더라도 소유자가 같아 무해하다.
                    and_(
                        KnowledgeBaseCreateAttempt.state == AttemptState.PENDING,
                        KnowledgeBaseCreateAttempt.started_at < window_closed,
                    ),
                ),
                KnowledgeBaseCreateAttempt.started_at >= cutoff,
            )
            # 정렬로 후보 KB 락을 잡아 락이 엇갈리는 상황(데드락)을 방지한다.
        ).order_by(KnowledgeBaseCreateAttempt.id).all()

    def get_known_surro_ids(self, db: Session) -> set:
        """게이트웨이가 **한 번이라도** 알았던 업스트림 KB id — soft-delete 포함.

        active 만 보면 사용자가 지운 KB 가 다시 "미지" 로 올라와 후보 개수를 부풀리고
        멀쩡한 복구를 거부시킨다.
        """
        rows = db.query(KnowledgeBase.surro_knowledge_id).all()
        return {row[0] for row in rows}

    def get_active_surro_ids(self, db: Session) -> set:
        """active 매핑이 있는 업스트림 KB id 집합 — 고아 차집합의 기준."""
        rows = db.query(KnowledgeBase.surro_knowledge_id).filter(
            and_(
                KnowledgeBase.deleted_at.is_(None),
                KnowledgeBase.is_active == True
            )
        ).all()
        return {row[0] for row in rows}

    def find_protecting_attempts(
            self,
            external_kb,
            live_attempts,
    ) -> List[KnowledgeBaseCreateAttempt]:
        """이 업스트림 KB 를 후보로 삼을 수 있는 살아 있는 시도들.

        삭제 보호와 복구 충돌 판정이 이 하나를 공유한다. 빈 반환은 "이 KB 를 가져갈 수 있는
        시도가 없다" 로 읽히므로, 판정할 수 없는 시도를 여기서 버리면 모름이 없음으로 둔갑한다.
        """
        created_at = _as_aware(getattr(external_kb, "created_at", None))
        if created_at is None:
            return list(live_attempts)
        
        max_ingest = timedelta(seconds=settings.KB_MAX_INGEST_SECONDS)
        found = []
        for t in live_attempts:
            if t.upstream_snapshot is not None and external_kb.id in t.upstream_snapshot:
                continue
            # 스냅샷이 없는 시도의 보호 범위를 시간으로 설정한다. 
            started_at = _as_aware(t.started_at)
            if not (started_at <= created_at <= started_at + max_ingest):
                continue                         # 복구 창 밖 → 보호해도 복구되지 않는다
            found.append(t)
        return found

    def is_protected(self, external_kb, live_attempts) -> bool:
        """관리자 삭제와 정리 잡이 보호해야 하는 KB 인지 판정 — 두 삭제 경로 공통."""
        return bool(self.find_protecting_attempts(external_kb, live_attempts))

    def find_cleanup_targets(self, db: Session, external_kbs, now: datetime) -> list:
        """정리 잡 — active 매핑 없음 · ORPHAN_TTL 경과 · `is_protected` 거짓. """
        cutoff = _as_aware(now) - timedelta(minutes=settings.PROXY_KB_ORPHAN_TTL_MINUTES)
        active_ids = self.get_active_surro_ids(db)
        live_attempts = self.get_live_attempts(db, now)

        targets = []
        for kb in external_kbs:
            if kb.id in active_ids:
                continue
            created_at = _as_aware(getattr(kb, "created_at", None))
            if created_at is None or created_at > cutoff:
                continue
            if self.is_protected(kb, live_attempts):
                continue
            targets.append(kb)
        return targets

    def abandon_attempts(
            self,
            db: Session,
            attempts: List[KnowledgeBaseCreateAttempt],
    ) -> int:
        """보호 대상이 강제 삭제됐을 때, 그것을 지켜보던 시도를 즉시 포기 처리한다."""
        if not attempts:
            return 0
        now = datetime.now(timezone.utc)
        for t in attempts:
            t.state = AttemptState.ABANDONED
            t.finished_at = now
        db.commit()
        return len(attempts)

    def find_duplicate_success(
            self,
            db: Session,
            attempt: KnowledgeBaseCreateAttempt,
    ) -> Optional[int]:
        """사용자가 같은 이름·파일로 이미 성공시킨 KB 의 surro_knowledge_id 를 돌려준다."""
        rows = db.query(KnowledgeBaseCreateAttempt).filter(
            and_(
                KnowledgeBaseCreateAttempt.member_id == attempt.member_id,
                KnowledgeBaseCreateAttempt.name == attempt.name,
                KnowledgeBaseCreateAttempt.filename == attempt.filename,
                KnowledgeBaseCreateAttempt.state == AttemptState.SUCCEEDED,
                # 이 비교가 없으면 과거의 성공이 현재 복구를 영구히 막는다.
                KnowledgeBaseCreateAttempt.started_at > attempt.started_at,
                KnowledgeBaseCreateAttempt.resolved_surro_id.isnot(None),
            )
        ).all()

        for row in rows:
            # 사용자가 재시도본을 지웠으면 중복이 아니다 — 원본을 복구해야 맞다.
            if self.get_active_knowledge_base_by_surro_id(db, row.resolved_surro_id):
                return row.resolved_surro_id
        return None


knowledge_base_crud = KnowledgeBaseCRUD()
