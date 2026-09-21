import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.config import settings
from app.models.knowledge_base import AttemptState, KnowledgeBase, KnowledgeBaseCreateAttempt


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

    def get_live_attempts(
            self,
            db: Session,
            now: datetime,
    ) -> List[KnowledgeBaseCreateAttempt]:
        """보호 효력을 갖는 시도 — orphan_suspect 이고 ATTEMPT_TTL 이내인 행."""
        cutoff = _as_aware(now) - timedelta(minutes=settings.KB_ATTEMPT_TTL_MINUTES)
        return db.query(KnowledgeBaseCreateAttempt).filter(
            and_(
                KnowledgeBaseCreateAttempt.state == AttemptState.ORPHAN_SUSPECT,
                KnowledgeBaseCreateAttempt.started_at >= cutoff,
            )
        ).all()

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

        보호 범위는 복구 범위와 일치해야 한다. MAX_INGEST 창 밖에 생긴 KB 는 Step 4 가 결코
        복구할 수 없으므로 보호하지 않는다 — 막히는데 복구도 안 되는 구간을 만들지 않기 위함.

        name/filename 은 일부러 보지 않는다. 대조에 KB 상세 조회가 필요해 목록 API 에서 N+1 이
        되기 때문이며, 느슨한 쪽이 안전 방향이다(과보호는 생겨도 과삭제는 생기지 않는다).
        """
        created_at = _as_aware(getattr(external_kb, "created_at", None))
        if created_at is None:
            return []

        max_ingest = timedelta(seconds=settings.KB_MAX_INGEST_SECONDS)
        found = []
        for t in live_attempts:
            if t.upstream_snapshot is None:
                continue                         # 스냅샷 없는 시도는 후보를 계산할 수 없다
            if external_kb.id in t.upstream_snapshot:
                continue                         # 그 시도 이전부터 있던 KB
            started_at = _as_aware(t.started_at)
            if not (started_at <= created_at <= started_at + max_ingest):
                continue                         # 복구 창 밖 → 보호해도 복구되지 않는다
            found.append(t)
        return found

    def is_protected(self, external_kb, live_attempts) -> bool:
        """공통 규칙 — 아직 주인이 정해질 수 있는 KB 인가.

        Step 1(관리자 삭제)과 Step 5(자동 정리)가 **함께** 거치는 판정이다. 각자 구현하면
        한쪽만 고쳐지는 사고가 나므로 여기 하나만 둔다.
        """
        return bool(self.find_protecting_attempts(external_kb, live_attempts))

    def abandon_attempts(
            self,
            db: Session,
            attempts: List[KnowledgeBaseCreateAttempt],
    ) -> int:
        """보호 대상이 강제 삭제됐을 때, 그것을 지켜보던 시도를 즉시 포기 처리한다.

        그대로 두면 붙을 대상이 없는 시도가 ATTEMPT_TTL 동안 남아 무관한 고아를 계속 보호한다.
        """
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
        """조건 6 — 사용자가 이미 같은 것을 갖고 있는가.

        같은 member/name/filename 으로 ``attempt`` 이후에 성공했고 그 매핑이 지금도 active 인
        KB 의 surro_knowledge_id 를 돌려준다. 있으면 복구하지 않는다. 사용자 목록에 구분할 수
        없는 중복 두 개가 놓이지 않게 하려는 것이고, 원본은 Step 5 가 회수한다.

        ``started_at`` 비교가 없으면 과거의 성공이 현재 복구를 영구히 막고, active 확인이
        없으면 사용자가 재시도본을 지운 경우까지 중복으로 판정한다.
        """
        rows = db.query(KnowledgeBaseCreateAttempt).filter(
            and_(
                KnowledgeBaseCreateAttempt.member_id == attempt.member_id,
                KnowledgeBaseCreateAttempt.name == attempt.name,
                KnowledgeBaseCreateAttempt.filename == attempt.filename,
                KnowledgeBaseCreateAttempt.state == AttemptState.SUCCEEDED,
                KnowledgeBaseCreateAttempt.started_at > attempt.started_at,
                KnowledgeBaseCreateAttempt.resolved_surro_id.isnot(None),
            )
        ).all()

        for row in rows:
            if self.get_active_knowledge_base_by_surro_id(db, row.resolved_surro_id):
                return row.resolved_surro_id
        return None


knowledge_base_crud = KnowledgeBaseCRUD()
