import logging
from datetime import datetime
from typing import Optional, List, Dict, Tuple

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.models.dataset import Dataset

_MISSING = object()


class DatasetCRUD:
    """데이터셋 CRUD 작업 클래스 - Inno DB에서 사용자별 데이터셋 매핑 관리"""

    def get_dataset(self, db: Session, dataset_id: int) -> Optional[Dataset]:
        """ID로 데이터셋 매핑 조회"""
        return db.query(Dataset).filter(
            and_(Dataset.id == dataset_id, Dataset.deleted_at.is_(None))
        ).first()

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

    def search_datasets_by_member_id(
            self,
            db: Session,
            member_id: str,
            skip: int = 0,
            limit: int = 20,
            search: Optional[str] = None,
            order_by: Optional[list] = None,
            valid_surro_ids: Optional[set] = None,
    ) -> Tuple[List[Dataset], int]:
        """로컬 데이터셋 매핑 검색 (이름, 설명). (결과, 총개수) 반환.

        `order_by` 미지정 시 `surro_dataset_id DESC` 를 기본 적용한다.
        `valid_surro_ids` 가 주어지면 그 집합에 속한 매핑만 포함 → `total` 과 `data`
        가 stale 매핑으로 어긋나지 않도록 외부 존재 기준으로 교차 필터링한다.
        """
        query = db.query(Dataset).filter(
            and_(
                Dataset.created_by == member_id,
                Dataset.deleted_at.is_(None),
                Dataset.is_active == True,
            )
        )

        if valid_surro_ids is not None:
            if not valid_surro_ids:
                return [], 0
            query = query.filter(Dataset.surro_dataset_id.in_(valid_surro_ids))

        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Dataset.name.ilike(search_term),
                    Dataset.description.ilike(search_term),
                )
            )

        total = query.count()
        if order_by:
            query = query.order_by(*order_by)
        else:
            query = query.order_by(Dataset.surro_dataset_id.desc())
        datasets = query.offset(skip).limit(limit).all()
        return datasets, total

    def backfill_cache_if_changed(
            self,
            db: Session,
            surro_dataset_id: int,
            member_id: str,
            name=_MISSING,
            description=_MISSING,
    ) -> bool:
        """외부 응답값이 로컬 캐시와 다를 때만 갱신한다.

        - "인자 미지정"과 "명시적 None"을 구분하기 위해 sentinel(`_MISSING`)을 사용한다.
          미지정이면 해당 필드는 건드리지 않고, None이 명시적으로 전달되면 외부가 값을 비운
          것으로 간주해 로컬도 NULL로 수렴시킨다(검색 false positive 방지).
        - 변경 시에만 commit. updated_by/updated_at은 건드리지 않음(시스템 sync vs 사용자 수정 구분).
        """
        mapping = self.get_dataset_by_surro_id(db, surro_dataset_id, member_id)
        if not mapping:
            return False

        changed = False
        if name is not _MISSING and mapping.name != name:
            mapping.name = name
            changed = True
        if description is not _MISSING and mapping.description != description:
            mapping.description = description
            changed = True

        if changed:
            db.commit()
        return changed

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
            dataset_name: str = None,
            dataset_description: str = None
    ) -> Dataset:
        """외부 API 데이터셋과 Inno 사용자 매핑 생성"""
        # 중복 확인
        existing = self.get_dataset_by_surro_id(db, surro_dataset_id, member_id)
        if existing:
            stale_name = dataset_name and existing.name != dataset_name
            stale_desc = dataset_description is not None and existing.description != dataset_description
            if stale_name or stale_desc:
                logger.info(
                    f"Updating stale dataset mapping: surro_id={surro_dataset_id}, "
                    f"old_name={existing.name}, new_name={dataset_name}"
                )
                if stale_name:
                    existing.name = dataset_name
                if stale_desc:
                    existing.description = dataset_description
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
            name=dataset_name,
            description=dataset_description
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
            dataset_name: str = None,
            dataset_description: str = None
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
            existing.description = dataset_description
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
            dataset_name=dataset_name,
            dataset_description=dataset_description
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
            dataset_name: str = None,
            dataset_description: str = None
    ) -> Optional[Dataset]:
        """데이터셋 캐시 정보 업데이트"""
        db_dataset = self.get_dataset_by_surro_id(db, surro_dataset_id, member_id)
        if not db_dataset:
            return None

        if dataset_name is not None:
            db_dataset.name = dataset_name
        if dataset_description is not None:
            db_dataset.description = dataset_description

        db_dataset.updated_by = member_id
        db_dataset.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(db_dataset)
        return db_dataset

    def bulk_create_mappings(
            self,
            db: Session,
            mappings: List[Tuple[int, str, str, Optional[str]]]
    ) -> int:
        """
        여러 데이터셋 매핑을 한번에 생성

        Args:
            mappings: (surro_dataset_id, member_id, dataset_name, dataset_description) 튜플 리스트

        Returns:
            생성된 매핑 개수
        """
        created_count = 0
        for entry in mappings:
            surro_id, member_id, name = entry[0], entry[1], entry[2]
            description = entry[3] if len(entry) > 3 else None
            try:
                if not self.get_dataset_by_surro_id(db, surro_id, member_id):
                    self.create_dataset_mapping(
                        db, surro_id, member_id, name, description
                    )
                    created_count += 1
            except Exception as e:
                logger.error(f"Failed to create mapping for {surro_id}: {e}")
                continue

        return created_count


# 싱글톤 인스턴스
dataset_crud = DatasetCRUD()
