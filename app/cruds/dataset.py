from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, List, Dict
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

from app.models.dataset import Dataset


class DatasetCRUD:
    """데이터셋 CRUD 작업 클래스 - Inno DB에서 사용자별 데이터셋 매핑 관리"""

    def get_dataset(self, db: Session, dataset_id: int) -> Optional[Dataset]:
        """ID로 데이터셋 매핑 조회"""
        return db.query(Dataset).filter(
            and_(Dataset.id == dataset_id, Dataset.deleted_at.is_(None))
        ).first()

    def get_datasets(
            self,
            db: Session,
            skip: int = 0,
            limit: int = 100,
            search: Optional[str] = None,
            is_active: Optional[bool] = True
    ) -> List[Dataset]:
        """데이터셋 매핑 목록 조회"""
        query = db.query(Dataset).filter(Dataset.deleted_at.is_(None))

        if is_active is not None:
            query = query.filter(Dataset.is_active == is_active)

        # 검색 조건 추가
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Dataset.name.ilike(search_term),
                    Dataset.description.ilike(search_term)
                )
            )

        return query.offset(skip).limit(limit).all()

    def get_datasets_count(
            self,
            db: Session,
            search: Optional[str] = None,
            is_active: Optional[bool] = True
    ) -> int:
        """데이터셋 매핑 총 개수 조회"""
        query = db.query(Dataset).filter(Dataset.deleted_at.is_(None))

        if is_active is not None:
            query = query.filter(Dataset.is_active == is_active)

        # 검색 조건 추가
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Dataset.name.ilike(search_term),
                    Dataset.description.ilike(search_term)
                )
            )

        return query.count()

    def get_datasets_count_by_member(
            self,
            db: Session,
            member_id: str,
            is_active: Optional[bool] = True
    ) -> int:
        """특정 사용자의 데이터셋 총 개수 조회"""
        query = db.query(Dataset).filter(
            and_(
                Dataset.created_by == member_id,
                Dataset.deleted_at.is_(None)
            )
        )

        if is_active is not None:
            query = query.filter(Dataset.is_active == is_active)

        return query.count()

    def get_datasets_by_member_id(
            self,
            db: Session,
            member_id: str,
            skip: int = 0,
            limit: int = 100
    ) -> List[int]:
        """특정 사용자가 만든 데이터셋의 ID 목록 조회 (외부 API ID)"""
        datasets = db.query(Dataset).filter(
            and_(
                Dataset.created_by == member_id,
                Dataset.deleted_at.is_(None),
                Dataset.is_active == True
            )
        ).order_by(Dataset.created_at.desc()).offset(skip).limit(limit).all()

        # 외부 API의 데이터셋 ID만 반환
        return [dataset.surro_dataset_id for dataset in datasets if dataset.surro_dataset_id]

    def get_dataset_mappings_by_member_id(
            self,
            db: Session,
            member_id: str,
            skip: int = 0,
            limit: int = 100
    ) -> Dict[int, str]:
        """특정 사용자가 만든 데이터셋의 {surro_dataset_id: created_by} 매핑 조회"""
        datasets = db.query(Dataset).filter(
            and_(
                Dataset.created_by == member_id,
                Dataset.deleted_at.is_(None),
                Dataset.is_active == True
            )
        ).order_by(Dataset.created_at.desc()).offset(skip).limit(limit).all()

        return {
            dataset.surro_dataset_id: dataset.created_by
            for dataset in datasets if dataset.surro_dataset_id
        }

    def get_dataset_by_surro_id(
            self,
            db: Session,
            surro_dataset_id: int,
            member_id: str
    ) -> Optional[Dataset]:
        """외부 API 데이터셋 ID와 멤버 ID로 매핑 조회"""
        return db.query(Dataset).filter(
            and_(
                Dataset.surro_dataset_id == surro_dataset_id,
                Dataset.created_by == member_id,
                Dataset.deleted_at.is_(None)
            )
        ).first()

    def create_dataset_mapping(
            self,
            db: Session,
            surro_dataset_id: int,
            member_id: str,
            dataset_name: str = None
    ) -> Dataset:
        """외부 API 데이터셋과 Inno 사용자 매핑 생성"""
        # 중복 확인
        existing = self.get_dataset_by_surro_id(db, surro_dataset_id, member_id)
        if existing:
            # stale 매핑이면 이름 업데이트 (MLOps 재설치 등으로 ID 재사용 시)
            if dataset_name and existing.name != dataset_name:
                logger.info(
                    f"Updating stale dataset mapping: surro_id={surro_dataset_id}, "
                    f"old_name={existing.name}, new_name={dataset_name}"
                )
                existing.name = dataset_name
                existing.updated_by = member_id
                existing.updated_at = datetime.utcnow()
                db.commit()
                db.refresh(existing)
            else:
                logger.warning(
                    f"Dataset mapping already exists: surro_id={surro_dataset_id}, "
                    f"member_id={member_id}"
                )
            return existing

        db_dataset = Dataset(
            surro_dataset_id=surro_dataset_id,
            created_by=member_id,
            updated_by=member_id,
            name=dataset_name
        )
        db.add(db_dataset)
        db.commit()
        db.refresh(db_dataset)
        return db_dataset

    def upsert_dataset_mapping(
            self,
            db: Session,
            surro_dataset_id: int,
            member_id: str,
            dataset_name: str = None
    ) -> Dataset:
        """삭제 여부와 관계없이 매핑을 생성하거나 재활성화한다."""
        existing = db.query(Dataset).filter(
            and_(
                Dataset.surro_dataset_id == surro_dataset_id,
                Dataset.created_by == member_id
            )
        ).order_by(Dataset.id.desc()).first()

        if existing:
            existing.name = dataset_name
            existing.is_active = True
            existing.deleted_at = None
            existing.deleted_by = None
            existing.updated_by = member_id
            existing.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(existing)
            return existing

        return self.create_dataset_mapping(
            db=db,
            surro_dataset_id=surro_dataset_id,
            member_id=member_id,
            dataset_name=dataset_name
        )

    def soft_delete_missing_mappings(
            self,
            db: Session,
            member_id: str,
            active_surro_dataset_ids: List[int],
            deleted_by: Optional[str] = None
    ) -> int:
        """외부 목록에 없는 활성 매핑을 소프트 삭제한다."""
        active_id_set = set(active_surro_dataset_ids)
        targets = db.query(Dataset).filter(
            and_(
                Dataset.created_by == member_id,
                Dataset.deleted_at.is_(None),
                Dataset.is_active == True
            )
        ).all()

        deleted_count = 0
        deleted_actor = deleted_by or member_id
        now = datetime.utcnow()

        for dataset in targets:
            if dataset.surro_dataset_id in active_id_set:
                continue
            dataset.is_active = False
            dataset.deleted_at = now
            dataset.deleted_by = deleted_actor
            dataset.updated_by = deleted_actor
            dataset.updated_at = now
            deleted_count += 1

        if deleted_count:
            db.commit()

        return deleted_count

    def delete_dataset_mapping(
            self,
            db: Session,
            surro_dataset_id: int,
            member_id: str
    ) -> bool:
        """데이터셋 매핑 소프트 삭제"""
        db_dataset = self.get_dataset_by_surro_id(db, surro_dataset_id, member_id)
        if not db_dataset:
            return False

        db_dataset.deleted_at = datetime.utcnow()
        db_dataset.deleted_by = member_id
        db_dataset.is_active = False

        db.commit()
        return True

    def check_dataset_ownership(
            self,
            db: Session,
            surro_dataset_id: int,
            member_id: str
    ) -> bool:
        """사용자가 해당 데이터셋의 소유자인지 확인"""
        dataset = self.get_dataset_by_surro_id(db, surro_dataset_id, member_id)
        return dataset is not None

    def get_dataset_by_name(
            self,
            db: Session,
            name: str,
            member_id: str
    ) -> Optional[Dataset]:
        """이름과 사용자 ID로 데이터셋 매핑 조회"""
        return db.query(Dataset).filter(
            and_(
                Dataset.name == name,
                Dataset.created_by == member_id,
                Dataset.deleted_at.is_(None)
            )
        ).first()

    def update_dataset_cache(
            self,
            db: Session,
            surro_dataset_id: int,
            member_id: str,
            dataset_name: str = None
    ) -> Optional[Dataset]:
        """데이터셋 캐시 정보 업데이트"""
        db_dataset = self.get_dataset_by_surro_id(db, surro_dataset_id, member_id)
        if not db_dataset:
            return None

        if dataset_name is not None:
            db_dataset.name = dataset_name

        db_dataset.updated_by = member_id
        db_dataset.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(db_dataset)
        return db_dataset

    def bulk_create_mappings(
            self,
            db: Session,
            mappings: List[tuple[int, str, str]]
    ) -> int:
        """
        여러 데이터셋 매핑을 한번에 생성

        Args:
            mappings: (surro_dataset_id, member_id, dataset_name) 튜플 리스트

        Returns:
            생성된 매핑 개수
        """
        created_count = 0
        for surro_id, member_id, name in mappings:
            try:
                # 중복 체크
                if not self.get_dataset_by_surro_id(db, surro_id, member_id):
                    self.create_dataset_mapping(db, surro_id, member_id, name)
                    created_count += 1
            except Exception as e:
                logger.error(f"Failed to create mapping for {surro_id}: {e}")
                continue

        return created_count


# 싱글톤 인스턴스
dataset_crud = DatasetCRUD()
