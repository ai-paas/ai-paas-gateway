from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, List
from datetime import datetime

from app.models.model import Model
from app.schemas.model import ModelCreate, ModelUpdate


class ModelCRUD:
    """모델 CRUD 작업 클래스"""

    def get_model(self, db: Session, model_id: int) -> Optional[Model]:
        """ID로 모델 조회"""
        return db.query(Model).filter(
            and_(Model.id == model_id, Model.deleted_at.is_(None))
        ).first()

    def get_models(
            self,
            db: Session,
            skip: int = 0,
            limit: int = 100,
            provider_id: Optional[int] = None,
            type_id: Optional[int] = None,
            format_id: Optional[int] = None,
            search: Optional[str] = None,
            is_active: Optional[bool] = True
    ) -> List[Model]:
        """모델 목록 조회"""
        query = db.query(Model).filter(Model.deleted_at.is_(None))

        # 필터링 조건 추가
        if provider_id:
            query = query.filter(Model.provider_id == provider_id)
        if type_id:
            query = query.filter(Model.type_id == type_id)
        if format_id:
            query = query.filter(Model.format_id == format_id)
        if is_active is not None:
            query = query.filter(Model.is_active == is_active)

        # 검색 조건 추가
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Model.name.ilike(search_term),
                    Model.description.ilike(search_term)
                )
            )

        return query.offset(skip).limit(limit).all()

    def get_models_count(
            self,
            db: Session,
            provider_id: Optional[int] = None,
            type_id: Optional[int] = None,
            format_id: Optional[int] = None,
            search: Optional[str] = None,
            is_active: Optional[bool] = True
    ) -> int:
        """모델 총 개수 조회"""
        query = db.query(Model).filter(Model.deleted_at.is_(None))

        # 필터링 조건 추가
        if provider_id:
            query = query.filter(Model.provider_id == provider_id)
        if type_id:
            query = query.filter(Model.type_id == type_id)
        if format_id:
            query = query.filter(Model.format_id == format_id)
        if is_active is not None:
            query = query.filter(Model.is_active == is_active)

        # 검색 조건 추가
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Model.name.ilike(search_term),
                    Model.description.ilike(search_term)
                )
            )

        return query.count()

    def get_model_by_name(self, db: Session, name: str, provider_id: int) -> Optional[Model]:
        """이름과 프로바이더로 모델 조회"""
        return db.query(Model).filter(
            and_(
                Model.name == name,
                Model.provider_id == provider_id,
                Model.deleted_at.is_(None)
            )
        ).first()

    def create_model(self, db: Session, model: ModelCreate, created_by: str) -> Model:
        """모델 생성"""
        db_model = Model(
            name=model.name,
            description=model.description,
            provider_id=model.provider_id,
            type_id=model.type_id,
            format_id=model.format_id,
            parent_model_id=model.parent_model_id,
            registry_schema=model.registry_schema,
            created_by=created_by,
            updated_by=created_by
        )
        db.add(db_model)
        db.commit()
        db.refresh(db_model)
        return db_model

    def update_model(
            self,
            db: Session,
            model_id: int,
            model_update: ModelUpdate,
            updated_by: str
    ) -> Optional[Model]:
        """모델 정보 업데이트"""
        db_model = self.get_model(db, model_id)
        if not db_model:
            return None

        # 업데이트할 필드만 적용
        update_data = model_update.model_dump(exclude_unset=True, exclude_none=True)

        for field, value in update_data.items():
            setattr(db_model, field, value)

        db_model.updated_by = updated_by
        db_model.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(db_model)
        return db_model

    def delete_model(self, db: Session, model_id: int, deleted_by: str) -> bool:
        """모델 소프트 삭제"""
        db_model = self.get_model(db, model_id)
        if not db_model:
            return False

        db_model.deleted_at = datetime.utcnow()
        db_model.deleted_by = deleted_by
        db_model.is_active = False

        db.commit()
        return True

    def activate_model(self, db: Session, model_id: int, updated_by: str) -> Optional[Model]:
        """모델 활성화"""
        db_model = self.get_model(db, model_id)
        if not db_model:
            return None

        db_model.is_active = True
        db_model.updated_by = updated_by
        db_model.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(db_model)
        return db_model

    def deactivate_model(self, db: Session, model_id: int, updated_by: str) -> Optional[Model]:
        """모델 비활성화"""
        db_model = self.get_model(db, model_id)
        if not db_model:
            return None

        db_model.is_active = False
        db_model.updated_by = updated_by
        db_model.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(db_model)
        return db_model

    def get_models_by_provider(self, db: Session, provider_id: int) -> List[Model]:
        """특정 프로바이더의 모든 모델 조회"""
        return db.query(Model).filter(
            and_(
                Model.provider_id == provider_id,
                Model.deleted_at.is_(None)
            )
        ).all()

    def get_child_models(self, db: Session, parent_model_id: int) -> List[Model]:
        """특정 부모 모델의 자식 모델들 조회"""
        return db.query(Model).filter(
            and_(
                Model.parent_model_id == parent_model_id,
                Model.deleted_at.is_(None)
            )
        ).all()

    def update_registry_info(
            self,
            db: Session,
            model_id: int,
            artifact_path: str,
            uri: str,
            updated_by: str
    ) -> Optional[Model]:
        """모델 레지스트리 정보 업데이트"""
        db_model = self.get_model(db, model_id)
        if not db_model:
            return None

        db_model.artifact_path = artifact_path
        db_model.uri = uri
        db_model.updated_by = updated_by
        db_model.updated_at = datetime.utcnow()

        db.commit()
        db.refresh(db_model)
        return db_model


# 싱글톤 인스턴스
model_crud = ModelCRUD()