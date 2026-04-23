import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import and_
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.models.knowledge_base import KnowledgeBase


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
        # 중복 확인 (MLOps 재설치 시 ID 재사용 대응)
        existing = self.get_knowledge_base_by_surro_id(db, surro_knowledge_id)
        if existing:
            # stale 매핑이면 새 데이터로 업데이트
            if name and existing.name != name:
                logger.info(
                    f"Updating stale knowledge base mapping: surro_id={surro_knowledge_id}, "
                    f"old_name={existing.name}, new_name={name}"
                )
                existing.name = name
                existing.description = description
                existing.collection_name = collection_name
                existing.updated_by = created_by
                existing.updated_at = datetime.utcnow()
                # 소프트 삭제된 상태였으면 복원
                if existing.deleted_at is not None:
                    existing.deleted_at = None
                    existing.deleted_by = None
                    existing.is_active = True
                db.commit()
                db.refresh(existing)
            else:
                logger.warning(
                    f"Knowledge base mapping already exists: surro_id={surro_knowledge_id}, "
                    f"member_id={created_by}"
                )
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
                KnowledgeBase.deleted_at.is_(None)
            )
        ).first()

    def get_knowledge_base_by_surro_id(self, db: Session, surro_knowledge_id: int):
        return db.query(KnowledgeBase).filter(
            KnowledgeBase.surro_knowledge_id == surro_knowledge_id
        ).first()

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


knowledge_base_crud = KnowledgeBaseCRUD()