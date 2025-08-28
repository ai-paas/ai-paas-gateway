from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, List
from datetime import datetime

from app.models.dataset import Dataset
from app.schemas.dataset import DatasetCreate, DatasetUpdate


class DatasetCRUD:
    """데이터셋 CRUD 작업 클래스 - Inno DB에서 사용자별 데이터셋 ID만 관리"""

    def get_dataset(self, db: Session, dataset_id: int) -> Optional[Dataset]:
        """ID로 데이터셋 조회"""
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
        """데이터셋 목록 조회"""
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
        """데이터셋 총 개수 조회"""
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

    def get_datasets_by_member_id(
            self,
            db: Session,
            member_id: str,
            skip: int = 0,
            limit: int = 100
    ) -> List[int]:
        """특정 사용자가 만든 데이터셋의 ID 목록 조회 (Surro API ID)"""
        datasets = db.query(Dataset).filter(
            and_(
                Dataset.created_by == member_id,
                Dataset.deleted_at.is_(None)
            )
        ).offset(skip).limit(limit).all()

        # Surro API의 데이터셋 ID만 반환
        return [dataset.surro_dataset_id for dataset in datasets if dataset.surro_dataset_id]

    def get_dataset_by_surro_id(self, db: Session, surro_dataset_id: int, member_id: str) -> Optional[Dataset]:
        """Surro 데이터셋 ID와 멤버 ID로 데이터셋 조회"""
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
            dataset_name: str = None,
            description: str = None
    ) -> Dataset:
        """Surro 데이터셋과 Inno 사용자 매핑 생성"""
        db_dataset = Dataset(
            surro_dataset_id=surro_dataset_id,
            created_by=member_id,
            updated_by=member_id,
            name=dataset_name,
            description=description
        )
        db.add(db_dataset)
        db.commit()
        db.refresh(db_dataset)
        return db_dataset

    def delete_dataset_mapping(self, db: Session, surro_dataset_id: int, member_id: str) -> bool:
        """데이터셋 매핑 소프트 삭제"""
        db_dataset = self.get_dataset_by_surro_id(db, surro_dataset_id, member_id)
        if not db_dataset:
            return False

        db_dataset.deleted_at = datetime.utcnow()
        db_dataset.deleted_by = member_id
        db_dataset.is_active = False

        db.commit()
        return True

    def check_dataset_ownership(self, db: Session, surro_dataset_id: int, member_id: str) -> bool:
        """사용자가 해당 데이터셋의 소유자인지 확인"""
        dataset = self.get_dataset_by_surro_id(db, surro_dataset_id, member_id)
        return dataset is not None

    def get_dataset_by_name(self, db: Session, name: str, member_id: str) -> Optional[Dataset]:
        """이름과 사용자 ID로 데이터셋 조회"""
        return db.query(Dataset).filter(
            and_(
                Dataset.name == name,
                Dataset.created_by == member_id,
                Dataset.deleted_at.is_(None)
            )
        ).first()

    def update_dataset(
            self,
            db: Session,
            dataset_id: int,
            dataset_update: DatasetUpdate,
            updated_by: str
    ) -> Optional[Dataset]:
        """데이터셋 정보 업데이트"""
        db_dataset = self.get_dataset(db, dataset_id)
        if not db_dataset:
            return None

        # 업데이트할 필드만 적용
        update_data = dataset_update.model_dump(exclude_unset=True, exclude_none=True)

        for field, value in update_data.items():
            setattr(db_dataset, field, value)

        db_dataset.updated_by = updated_by
        db_dataset.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(db_dataset)
        return db_dataset

    def delete_dataset(self, db: Session, dataset_id: int, deleted_by: str) -> bool:
        """데이터셋 소프트 삭제"""
        db_dataset = self.get_dataset(db, dataset_id)
        if not db_dataset:
            return False

        db_dataset.deleted_at = datetime.utcnow()
        db_dataset.deleted_by = deleted_by
        db_dataset.is_active = False

        db.commit()
        return True

# 싱글톤 인스턴스
dataset_crud = DatasetCRUD()