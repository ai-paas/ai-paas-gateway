from datetime import datetime
from typing import Optional, List, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.models.experiment import Experiment


class ExperimentCRUD:
    """학습 실험 CRUD - Inno DB에서 사용자별 실험 매핑 관리"""

    def get_experiments_by_member_id(self, db: Session, member_id: str) -> List[int]:
        """특정 사용자의 실험 ID 목록 조회 (외부 API ID)"""
        experiments = db.query(Experiment).filter(
            and_(
                Experiment.created_by == member_id,
                Experiment.deleted_at.is_(None)
            )
        ).all()
        return [e.surro_experiment_id for e in experiments if e.surro_experiment_id]

    def search_experiments_by_member_id(
        self,
        db: Session,
        member_id: str,
        skip: int = 0,
        limit: int = 20,
        search: Optional[str] = None,
        order_by: Optional[list] = None,
        valid_surro_ids: Optional[set] = None,
    ) -> Tuple[List[Experiment], int]:
        """로컬 실험 매핑 검색.

        `order_by` 미지정 시 `surro_experiment_id DESC` 를 기본 적용한다.
        `valid_surro_ids` 가 주어지면 그 집합에 속한 매핑만 포함 → `total` 과 `data`
        가 stale 매핑으로 어긋나지 않도록 외부 존재 기준으로 교차 필터링한다.
        """
        query = db.query(Experiment).filter(
            and_(
                Experiment.created_by == member_id,
                Experiment.deleted_at.is_(None),
            )
        )

        if valid_surro_ids is not None:
            if not valid_surro_ids:
                return [], 0
            query = query.filter(Experiment.surro_experiment_id.in_(valid_surro_ids))

        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    Experiment.name.ilike(search_filter),
                    Experiment.description.ilike(search_filter),
                )
            )

        total = query.count()
        if order_by:
            query = query.order_by(*order_by)
        else:
            query = query.order_by(Experiment.surro_experiment_id.desc())
        experiments = query.offset(skip).limit(limit).all()
        return experiments, total

    def get_experiment_by_surro_id(self, db: Session, surro_experiment_id: int, member_id: str) -> Optional[Experiment]:
        """외부 실험 ID와 멤버 ID로 조회"""
        return db.query(Experiment).filter(
            and_(
                Experiment.surro_experiment_id == surro_experiment_id,
                Experiment.created_by == member_id,
                Experiment.deleted_at.is_(None)
            )
        ).first()

    def create_mapping(self, db: Session, surro_experiment_id: int, member_id: str,
                       name: str = None, description: str = None,
                       model_id: int = None, dataset_id: int = None) -> Experiment:
        """실험 매핑 생성"""
        db_experiment = Experiment(
            surro_experiment_id=surro_experiment_id,
            created_by=member_id,
            updated_by=member_id,
            name=name,
            description=description,
            model_id=model_id,
            dataset_id=dataset_id
        )
        db.add(db_experiment)
        db.commit()
        db.refresh(db_experiment)
        return db_experiment

    def delete_mapping(self, db: Session, surro_experiment_id: int, member_id: str) -> bool:
        """실험 매핑 소프트 삭제"""
        db_experiment = self.get_experiment_by_surro_id(db, surro_experiment_id, member_id)
        if not db_experiment:
            return False
        db_experiment.deleted_at = datetime.utcnow()
        db_experiment.deleted_by = member_id
        db_experiment.is_active = False
        db.commit()
        return True

    def update_mapping(self, db: Session, surro_experiment_id: int, member_id: str,
                       update_data: dict) -> Optional[Experiment]:
        """실험 매핑 로컬 캐시 업데이트"""
        db_experiment = self.get_experiment_by_surro_id(db, surro_experiment_id, member_id)
        if not db_experiment:
            return None
        if "name" in update_data:
            db_experiment.name = update_data["name"]
        if "description" in update_data:
            db_experiment.description = update_data["description"]
        db_experiment.updated_by = member_id
        db_experiment.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(db_experiment)
        return db_experiment

    def check_ownership(self, db: Session, surro_experiment_id: int, member_id: str) -> bool:
        """사용자가 해당 실험의 소유자인지 확인"""
        return self.get_experiment_by_surro_id(db, surro_experiment_id, member_id) is not None


experiment_crud = ExperimentCRUD()
