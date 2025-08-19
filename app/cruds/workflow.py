from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime
from app.models import Workflow
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate


class WorkflowCRUD:
    def create_workflow(self, db: Session, workflow: WorkflowCreate, created_by: str,
                        workflow_id: str) -> Workflow:
        """워크플로우 생성 (external_workflow_id는 써로 API 호출 후 받은 값)"""
        workflow_data = workflow.dict()
        workflow_data['created_by'] = created_by
        workflow_data['workflow_id'] = workflow_id

        db_workflow = Workflow(**workflow_data)
        db.add(db_workflow)
        db.commit()
        db.refresh(db_workflow)
        return db_workflow

    def get_workflow(self, db: Session, workflow_id: int) -> Optional[Workflow]:
        return db.query(Workflow).filter(
            and_(Workflow.id == workflow_id)
        ).first()

    def get_workflow_with_creator(self, db: Session, workflow_id: int) -> Optional[Workflow]:
        return db.query(Workflow).options(joinedload(Workflow.creator)).filter(
            and_(Workflow.id == workflow_id)
        ).first()

    def get_workflows(
            self,
            db: Session,
            skip: int = 0,
            limit: int = 100,
            search: Optional[str] = None,
            creator_id: Optional[str] = None,
    ) -> tuple[List[Workflow], int]:
        query = db.query(Workflow)

        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    Workflow.name.ilike(search_filter),
                    Workflow.description.ilike(search_filter)
                )
            )

        if creator_id:
            query = query.filter(Workflow.created_by == creator_id)

        total = query.count()
        workflows = query.offset(skip).limit(limit).all()
        return workflows, total

    def get_workflows_by_member(self, db: Session, member_id: str, skip: int = 0, limit: int = 100) -> tuple[
        List[Workflow], int]:
        """특정 멤버가 생성한 워크플로우 조회"""
        query = db.query(Workflow).filter(
            and_(Workflow.created_by == member_id)
        )
        total = query.count()
        workflows = query.offset(skip).limit(limit).all()
        return workflows, total

    def update_workflow(self, db: Session, workflow_id: int, workflow_update: WorkflowUpdate) -> Optional[Workflow]:
        db_workflow = self.get_workflow(db, workflow_id)
        if db_workflow:
            update_data = workflow_update.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_workflow, key, value)

            db_workflow.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(db_workflow)
        return db_workflow

    def delete_workflow(self, db: Session, workflow_id: int) -> bool:
        """워크플로우 소프트 삭제 (status를 deleted로 변경)"""
        db_workflow = self.get_workflow(db, workflow_id)
        if db_workflow:
            db_workflow.updated_at = datetime.utcnow()
            db.commit()
            return True
        return False

    def get_workflow_by_external_id(self, db: Session, external_workflow_id: str) -> Optional[Workflow]:
        """외부 워크플로우 ID로 조회"""
        return db.query(Workflow).filter(
            and_(Workflow.external_workflow_id == external_workflow_id)
        ).first()


# 전역 CRUD 인스턴스
workflow_crud = WorkflowCRUD()