from datetime import datetime, timezone
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.workflow import Workflow


class WorkflowCRUD:
    def create_workflow(
            self,
            db: Session,
            name: str,
            description: Optional[str],
            created_by: str,
            surro_workflow_id: str
    ) -> Workflow:
        """워크플로우 생성 (외부 API 호출 후 우리 DB 저장)"""
        db_workflow = Workflow(
            name=name,
            description=description,
            created_by=created_by,
            surro_workflow_id=surro_workflow_id
        )
        db.add(db_workflow)
        db.commit()
        db.refresh(db_workflow)
        return db_workflow

    def get_workflow(self, db: Session, workflow_id: int) -> Optional[Workflow]:
        """내부 ID로 조회"""
        return db.query(Workflow).filter(
            Workflow.id == workflow_id,
            Workflow.deleted_at.is_(None),
            Workflow.is_active.is_(True),
        ).first()

    def get_workflow_by_surro_id(
            self,
            db: Session,
            surro_workflow_id: str
    ) -> Optional[Workflow]:
        """외부 API ID로 조회"""
        return db.query(Workflow).filter(
            Workflow.surro_workflow_id == surro_workflow_id,
            Workflow.deleted_at.is_(None),
            Workflow.is_active.is_(True),
        ).first()

    def get_workflows(
            self,
            db: Session,
            skip: Optional[int] = None,
            limit: Optional[int] = None,
            search: Optional[str] = None,
            creator_id: Optional[str] = None,
            status: Optional[str] = None
    ) -> Tuple[List[Workflow], int]:
        """워크플로우 목록 조회"""
        query = db.query(Workflow).filter(
            Workflow.deleted_at.is_(None),
            Workflow.is_active.is_(True),
        )

        # 검색 조건 추가 (이름, 설명)
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                (Workflow.name.ilike(search_filter)) |
                (Workflow.description.ilike(search_filter))
            )

        # 생성자 필터
        if creator_id:
            query = query.filter(Workflow.created_by == creator_id)

        total = query.count()

        # 정렬 (최신순)
        query = query.order_by(Workflow.created_at.desc(), Workflow.id.desc())

        # 페이지네이션 적용 (skip, limit이 있을 때만)
        if skip is not None and limit is not None:
            workflows = query.offset(skip).limit(limit).all()
        else:
            # 전체 데이터 조회 (최대 10000개)
            workflows = query.limit(10000).all()

        return workflows, total

    def update_workflow(
            self,
            db: Session,
            workflow_id: int,
            name: Optional[str] = None,
            description: Optional[str] = None
    ) -> Optional[Workflow]:
        """워크플로우 업데이트"""
        db_workflow = self.get_workflow(db, workflow_id)
        if db_workflow:
            if name is not None:
                db_workflow.name = name
            if description is not None:
                db_workflow.description = description

            db.commit()
            db.refresh(db_workflow)
        return db_workflow

    def update_workflow_by_surro_id(
            self,
            db: Session,
            surro_workflow_id: str,
            name: Optional[str] = None,
            description: Optional[str] = None
    ) -> Optional[Workflow]:
        """외부 ID로 워크플로우 업데이트"""
        db_workflow = self.get_workflow_by_surro_id(db, surro_workflow_id)
        if db_workflow:
            if name is not None:
                db_workflow.name = name
            if description is not None:
                db_workflow.description = description

            db.commit()
            db.refresh(db_workflow)
        return db_workflow

    def delete_workflow(
            self, db: Session, workflow_id: int,
            deleted_by: str = "system"
    ) -> bool:
        """내부 ID로 워크플로우 soft-delete."""
        db_workflow = self.get_workflow(db, workflow_id)
        if db_workflow:
            db_workflow.deleted_at = datetime.now(timezone.utc)
            db_workflow.deleted_by = deleted_by
            db_workflow.is_active = False
            db.commit()
            return True
        return False

    def delete_workflow_by_surro_id(
            self, db: Session, surro_workflow_id: str,
            deleted_by: str = "system"
    ) -> bool:
        """외부 ID로 워크플로우 soft-delete."""
        db_workflow = self.get_workflow_by_surro_id(db, surro_workflow_id)
        if db_workflow:
            db_workflow.deleted_at = datetime.now(timezone.utc)
            db_workflow.deleted_by = deleted_by
            db_workflow.is_active = False
            db.commit()
            return True
        return False

    def soft_delete_missing_mappings(
            self,
            db: Session,
            active_surro_workflow_ids: List[str],
            deleted_by: str = "system",
    ) -> int:
        """외부 목록에 없는 활성 매핑을 soft-delete 한다.

        목록 조회 라우트는 원격 장애나 service/status 필터가 만든 빈 결과로
        멀쩡한 매핑을 지울 수 있어 이 작업을 하지 않는다. 호출자는 필터 없는
        전체 목록을 넘겨야 한다.
        """
        active_id_set = set(active_surro_workflow_ids)
        targets = db.query(Workflow).filter(
            Workflow.deleted_at.is_(None),
            Workflow.is_active == True,
        ).all()

        now = datetime.now(timezone.utc)
        deleted_count = 0
        for workflow in targets:
            if workflow.surro_workflow_id in active_id_set:
                continue
            workflow.is_active = False
            workflow.deleted_at = now
            workflow.deleted_by = deleted_by
            deleted_count += 1

        if deleted_count:
            db.commit()
        return deleted_count


# 전역 CRUD 인스턴스
workflow_crud = WorkflowCRUD()
