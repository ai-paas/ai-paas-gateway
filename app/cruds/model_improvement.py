from typing import Optional, List

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.models.model_improvement import ModelImprovement


class ModelImprovementCRUD:
    """모델 최적화/경량화 task CRUD"""

    def get_by_task_id(self, db: Session, task_id: str) -> Optional[ModelImprovement]:
        """task_id로 조회"""
        return db.query(ModelImprovement).filter(
            and_(
                ModelImprovement.task_id == task_id,
                ModelImprovement.deleted_at.is_(None)
            )
        ).first()

    def get_tasks_by_member_id(self, db: Session, member_id: str) -> List[ModelImprovement]:
        """특정 사용자의 task 목록 조회"""
        return db.query(ModelImprovement).filter(
            and_(
                ModelImprovement.created_by == member_id,
                ModelImprovement.deleted_at.is_(None)
            )
        ).all()

    def create_mapping(self, db: Session, task_id: str, source_model_id: int,
                       task_type: str, member_id: str) -> ModelImprovement:
        """task 매핑 생성"""
        db_mi = ModelImprovement(
            task_id=task_id,
            source_model_id=source_model_id,
            task_type=task_type,
            created_by=member_id
        )
        db.add(db_mi)
        db.commit()
        db.refresh(db_mi)
        return db_mi

    def check_ownership(self, db: Session, task_id: str, member_id: str) -> bool:
        """사용자가 해당 task의 소유자인지 확인"""
        mi = self.get_by_task_id(db, task_id)
        return mi is not None and mi.created_by == member_id


model_improvement_crud = ModelImprovementCRUD()
