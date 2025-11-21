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
            collection_name: str,
            chunk_size: Optional[int] = None,
            chunk_overlap: Optional[int] = None,
            top_k: Optional[int] = None,
            threshold: Optional[int] = None
    ) -> KnowledgeBase:
        """지식베이스 생성 (외부 API 호출 후 우리 DB 저장)"""
        db_knowledge_base = KnowledgeBase(
            name=name,
            description=description,
            collection_name=collection_name,
            created_by=created_by,
            surro_knowledge_id=surro_knowledge_id,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            top_k=top_k,
            threshold=threshold
        )
        db.add(db_knowledge_base)
        db.commit()
        db.refresh(db_knowledge_base)
        return db_knowledge_base

    def get_knowledge_base(self, db: Session, knowledge_base_id: int) -> Optional[KnowledgeBase]:
        """내부 ID로 조회"""
        return db.query(KnowledgeBase).filter(KnowledgeBase.id == knowledge_base_id).first()

    def get_knowledge_base_by_surro_id(
            self,
            db: Session,
            surro_knowledge_id: int
    ) -> Optional[KnowledgeBase]:
        """외부 API ID로 조회"""
        return db.query(KnowledgeBase).filter(
            KnowledgeBase.surro_knowledge_id == surro_knowledge_id
        ).first()

    def get_knowledge_bases(
            self,
            db: Session,
            skip: Optional[int] = None,
            limit: Optional[int] = None,
            search: Optional[str] = None
    ) -> Tuple[List[KnowledgeBase], int]:
        """지식베이스 목록 조회"""
        query = db.query(KnowledgeBase)

        # 검색 조건 추가 (이름, 설명, collection_name)
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (KnowledgeBase.name.ilike(search_filter)) |
                (KnowledgeBase.description.ilike(search_filter)) |
                (KnowledgeBase.collection_name.ilike(search_filter))
            )

        total = query.count()

        # 정렬 (최신순)
        query = query.order_by(KnowledgeBase.created_at.desc())

        # 페이지네이션 적용 (skip, limit이 있을 때만)
        if skip is not None and limit is not None:
            knowledge_bases = query.offset(skip).limit(limit).all()
        else:
            # 전체 데이터 조회 (최대 10000개)
            knowledge_bases = query.limit(10000).all()

        return knowledge_bases, total

    def update_knowledge_base(
            self,
            db: Session,
            knowledge_base_id: int,
            name: Optional[str] = None,
            description: Optional[str] = None,
            collection_name: Optional[str] = None
    ) -> Optional[KnowledgeBase]:
        """지식베이스 업데이트"""
        db_knowledge_base = self.get_knowledge_base(db, knowledge_base_id)
        if db_knowledge_base:
            if name is not None:
                db_knowledge_base.name = name
            if description is not None:
                db_knowledge_base.description = description
            if collection_name is not None:
                db_knowledge_base.collection_name = collection_name

            db.commit()
            db.refresh(db_knowledge_base)
        return db_knowledge_base

    def update_knowledge_base_by_surro_id(
            self,
            db: Session,
            surro_knowledge_id: int,
            name: Optional[str] = None,
            description: Optional[str] = None,
            collection_name: Optional[str] = None
    ) -> Optional[KnowledgeBase]:
        """외부 ID로 지식베이스 업데이트"""
        db_knowledge_base = self.get_knowledge_base_by_surro_id(db, surro_knowledge_id)
        if db_knowledge_base:
            if name is not None:
                db_knowledge_base.name = name
            if description is not None:
                db_knowledge_base.description = description
            if collection_name is not None:
                db_knowledge_base.collection_name = collection_name

            db.commit()
            db.refresh(db_knowledge_base)
        return db_knowledge_base

    def delete_knowledge_base(self, db: Session, knowledge_base_id: int) -> bool:
        """내부 ID로 지식베이스 삭제"""
        db_knowledge_base = self.get_knowledge_base(db, knowledge_base_id)
        if db_knowledge_base:
            db.delete(db_knowledge_base)
            db.commit()
            return True
        return False

    def delete_knowledge_base_by_surro_id(self, db: Session, surro_knowledge_id: int) -> bool:
        """외부 ID로 지식베이스 삭제"""
        db_knowledge_base = self.get_knowledge_base_by_surro_id(db, surro_knowledge_id)
        if db_knowledge_base:
            db.delete(db_knowledge_base)
            db.commit()
            return True
        return False


# 전역 CRUD 인스턴스
knowledge_base_crud = KnowledgeBaseCRUD()