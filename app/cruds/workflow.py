from datetime import datetime, timezone
from typing import List, Optional, Set, Tuple

from sqlalchemy.orm import Session

from app.database import commit_or_rollback
from app.models.workflow import Workflow

REGISTERED_VIA_AUTO = "auto"


class WorkflowCRUD:
    def create_workflow(
            self,
            db: Session,
            name: str,
            description: Optional[str],
            created_by: str,
            surro_workflow_id: str,
            registered_via: Optional[str] = None,
    ) -> Workflow:
        """워크플로우 생성 (외부 API 호출 후 우리 DB 저장)"""
        db_workflow = Workflow(
            name=name,
            description=description,
            created_by=created_by,
            surro_workflow_id=surro_workflow_id,
            registered_via=registered_via,
        )
        db.add(db_workflow)
        commit_or_rollback(db)
        db.refresh(db_workflow)
        return db_workflow

    def claim_auto_registered(
            self, db: Session, surro_workflow_id: str, member_id: str,
    ) -> Optional[Workflow]:
        """자동 등록이 만든 활성 매핑의 소유권을 member_id 로 넘긴다. 그런 행이 없으면 None.

        판정과 변경을 UPDATE 한 문장으로 해 사이에 다른 요청이 끼어들 틈을 두지 않는다.
        """
        claimed = db.query(Workflow).filter(
            Workflow.surro_workflow_id == surro_workflow_id,
            Workflow.deleted_at.is_(None),
            Workflow.registered_via == REGISTERED_VIA_AUTO,
        ).update(
            {
                Workflow.created_by: member_id,
                Workflow.registered_via: None,
                Workflow.updated_at: datetime.utcnow(),
            },
            synchronize_session=False,
        )
        commit_or_rollback(db)
        if not claimed:
            return None
        return db.query(Workflow).filter(
            Workflow.surro_workflow_id == surro_workflow_id,
            Workflow.deleted_at.is_(None),
        ).one()

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
            surro_workflow_id: str,
            include_deleted: bool = False,
    ) -> Optional[Workflow]:
        """외부 API ID로 조회.

        include_deleted=True는 soft-delete된 매핑도 반환한다(활성 행 우선, 없으면
        최신 삭제 행). 삭제 완료 확인(finalize-deletion) 재호출이 게이트웨이에서
        404로 끊기지 않게 하려는 용도.
        """
        query = db.query(Workflow).filter(
            Workflow.surro_workflow_id == surro_workflow_id,
        )
        if not include_deleted:
            return query.filter(
                Workflow.deleted_at.is_(None),
                Workflow.is_active.is_(True),
            ).first()
        return query.order_by(
            Workflow.deleted_at.is_(None).desc(),
            Workflow.id.desc(),
        ).first()

    def get_workflows(
            self,
            db: Session,
            skip: Optional[int] = None,
            limit: Optional[int] = None,
            search: Optional[str] = None,
            creator_id: Optional[str] = None,
            status: Optional[str] = None,
            surro_workflow_ids: Optional[List[str]] = None,
    ) -> Tuple[List[Workflow], int]:
        """워크플로우 목록 조회.

        surro_workflow_ids 를 주면 그 외부 ID 로 한정하고 10000건 상한을 두지 않는다.
        결과 크기가 넘긴 ID 수를 넘지 않기 때문이다.
        """
        query = db.query(Workflow).filter(
            Workflow.deleted_at.is_(None),
            Workflow.is_active.is_(True),
        )
        if surro_workflow_ids is not None:
            query = query.filter(Workflow.surro_workflow_id.in_(surro_workflow_ids))

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
        elif surro_workflow_ids is not None:
            workflows = query.all()
        else:
            # 전체 데이터 조회 (최대 10000개)
            workflows = query.limit(10000).all()

        return workflows, total

    def get_mapped_surro_ids(self, db: Session, surro_workflow_ids: List[str]) -> Set[str]:
        """주어진 외부 ID 중 매핑이 있는 것.

        유니크 인덱스와 같이 deleted_at 만 본다. is_active=False 라도 deleted_at 이 없으면
        자리를 차지하므로 새로 등록할 수 없다.
        """
        if not surro_workflow_ids:
            return set()
        rows = db.query(Workflow.surro_workflow_id).filter(
            Workflow.surro_workflow_id.in_(surro_workflow_ids),
            Workflow.deleted_at.is_(None),
        ).all()
        return {sid for (sid,) in rows}

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
            *,
            fetched_at: datetime,
            deleted_by: str = "system",
    ) -> int:
        """외부 목록에 없는 활성 매핑을 soft-delete 한다.

        목록 조회 라우트는 원격 장애나 service/status 필터가 만든 빈 결과로
        멀쩡한 매핑을 지울 수 있어 이 작업을 하지 않는다. 호출자는 필터 없는
        전체 목록을 넘겨야 한다.

        fetched_at 은 외부 목록을 요청하기 전 시각(naive UTC, created_at 저장값과 같은 기준)이다.
        그 뒤에 만든 매핑은 목록에 없을 뿐 사라진 것이 아니므로 지우지 않는다.
        """
        # 빈 목록은 "전부 삭제됨"과 "업스트림 일시 장애"를 구분할 수 없다.
        if not active_surro_workflow_ids:
            return 0
        active_id_set = set(active_surro_workflow_ids)
        targets = db.query(Workflow).filter(
            Workflow.deleted_at.is_(None),
            Workflow.is_active == True,
            Workflow.created_at < fetched_at,
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
