from sqlalchemy.orm import Session
from typing import List, Optional, Tuple

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
        """지식베이스 생성 - surro_knowledge_id만 저장"""
        db_knowledge_base = KnowledgeBase(
            name=name,
            description=description,
            collection_name=collection_name,
            created_by=created_by,
            surro_knowledge_id=surro_knowledge_id
        )
        db.add(db_knowledge_base)
        db.commit()
        db.refresh(db_knowledge_base)
        return db_knowledge_base

    def get_knowledge_base(self, db: Session, knowledge_base_id: int):
        return db.query(KnowledgeBase).filter(
            KnowledgeBase.id == knowledge_base_id
        ).first()

    def get_knowledge_base_by_surro_id(self, db: Session, surro_knowledge_id: int):
        return db.query(KnowledgeBase).filter(
            KnowledgeBase.surro_knowledge_id == surro_knowledge_id
        ).first()

    def get_knowledge_bases(
            self,
            db: Session,
            skip: Optional[int] = None,
            limit: Optional[int] = None,
            search: Optional[str] = None
    ):
        query = db.query(KnowledgeBase)

        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (KnowledgeBase.name.ilike(search_filter)) |
                (KnowledgeBase.description.ilike(search_filter)) |
                (KnowledgeBase.collection_name.ilike(search_filter))
            )

        total = query.count()
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
            collection_name: Optional[str] = None
    ):
        db_kb = self.get_knowledge_base_by_surro_id(db, surro_knowledge_id)
        if db_kb:
            if name is not None:
                db_kb.name = name
            if description is not None:
                db_kb.description = description
            if collection_name is not None:
                db_kb.collection_name = collection_name
            db.commit()
            db.refresh(db_kb)
        return db_kb

    def delete_knowledge_base_by_surro_id(self, db: Session, surro_knowledge_id: int):
        db_kb = self.get_knowledge_base_by_surro_id(db, surro_knowledge_id)
        if db_kb:
            db.delete(db_kb)
            db.commit()
            return True
        return False


knowledge_base_crud = KnowledgeBaseCRUD()