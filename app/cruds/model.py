from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import Optional, List
from datetime import datetime

from app.models.model import Model
from app.schemas.model import ModelCreate, ModelUpdate


class ModelCRUD:
    """모델 CRUD 작업 클래스 - Inno DB에서 사용자별 모델 ID만 관리"""

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

    def get_models_by_member_id(
            self,
            db: Session,
            member_id: str,
            skip: int = 0,
            limit: int = 100
    ) -> List[int]:
        """특정 사용자가 만든 모델의 ID 목록 조회 (Surro API ID)"""
        models = db.query(Model).filter(
            and_(
                Model.created_by == member_id,
                Model.deleted_at.is_(None)
            )
        ).offset(skip).limit(limit).all()

        # Surro API의 모델 ID만 반환
        return [model.surro_model_id for model in models if model.surro_model_id]

    def count_models_by_member_id(self, db: Session, member_id: str) -> int:
        """사용자가 소유한 모델 총 개수 반환"""
        return db.query(Model).filter(
            Model.created_by == member_id,
            Model.deleted_at.is_(None)
        ).count()

    def count_catalog_models(self, db: Session) -> int:
        """카탈로그 모델 총 개수 반환"""
        return db.query(Model).filter(
            Model.is_catalog == True,
            Model.deleted_at.is_(None)
        ).count()

    def get_catalog_models_paginated(
            self,
            db: Session,
            skip: int = 0,
            limit: int = 20
    ) -> List[Model]:
        """카탈로그 모델을 페이지네이션으로 조회"""
        return db.query(Model).filter(
            Model.is_catalog == True,
            Model.deleted_at.is_(None)
        ).offset(skip).limit(limit).all()

    def get_user_models_paginated(
            self,
            db: Session,
            member_id: str,
            skip: int = 0,
            limit: int = 20
    ) -> List[Model]:
        """사용자 모델을 페이지네이션으로 조회"""
        return db.query(Model).filter(
            Model.created_by == member_id,
            Model.deleted_at.is_(None)
        ).offset(skip).limit(limit).all()

    def get_model_by_surro_id(self, db: Session, surro_model_id: int, member_id: str) -> Optional[Model]:
        """Surro 모델 ID와 멤버 ID로 모델 조회"""
        return db.query(Model).filter(
            and_(
                Model.surro_model_id == surro_model_id,
                Model.created_by == member_id,
                Model.deleted_at.is_(None)
            )
        ).first()

    def create_model_mapping(
            self,
            db: Session,
            surro_model_id: int,
            member_id: str,
            model_name: str = None,
            is_catalog: bool = False  # 새로운 파라미터 추가
    ) -> Model:
        """Surro 모델과 Inno 사용자 매핑 생성 (간소화된 버전)

        Args:
            db: 데이터베이스 세션
            surro_model_id: Surro API의 모델 ID
            member_id: 생성한 사용자 ID
            model_name: 모델 이름 (선택)
            is_catalog: 카탈로그 모델 여부 (admin이 생성한 경우 True)

        Returns:
            생성된 Model 객체
        """
        db_model = Model(
            surro_model_id=surro_model_id,  # Surro API의 모델 ID
            name=model_name or f"Model_{surro_model_id}",
            is_catalog=is_catalog,  # 카탈로그 플래그 설정
            created_by=member_id,
            updated_by=member_id
        )
        db.add(db_model)
        db.commit()
        db.refresh(db_model)
        return db_model

    def delete_model_mapping(self, db: Session, surro_model_id: int, member_id: str) -> bool:
        """모델 매핑 소프트 삭제"""
        db_model = self.get_model_by_surro_id(db, surro_model_id, member_id)
        if not db_model:
            return False

        db_model.deleted_at = datetime.utcnow()
        db_model.deleted_by = member_id
        db_model.is_active = False

        db.commit()
        return True

    def check_model_ownership(self, db: Session, surro_model_id: int, member_id: str) -> bool:
        """사용자가 해당 모델의 소유자인지 확인"""
        model = self.get_model_by_surro_id(db, surro_model_id, member_id)
        return model is not None

    # 기존 메서드들은 호환성을 위해 유지하되, 새로운 구조에 맞게 수정할 수 있음
    def get_model_by_name(self, db: Session, name: str, provider_id: int) -> Optional[Model]:
        """이름과 프로바이더로 모델 조회 (기존 호환성 유지)"""
        return db.query(Model).filter(
            and_(
                Model.name == name,
                Model.provider_id == provider_id,
                Model.deleted_at.is_(None)
            )
        ).first()

    def create_model(self, db: Session, model: ModelCreate, created_by: str) -> Model:
        """모델 생성 (기존 호환성 유지)"""
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

    # 검색 및 필터링을 위한 추가 메서드들
    def search_models_by_member(
            self,
            db: Session,
            member_id: str,
            search: Optional[str] = None,
            provider_id: Optional[int] = None,
            type_id: Optional[int] = None,
            format_id: Optional[int] = None,
            skip: int = 0,
            limit: int = 20
    ) -> tuple[List[Model], int]:
        """사용자 모델 검색 (데이터와 총 개수 함께 반환)"""
        query = db.query(Model).filter(
            Model.created_by == member_id,
            Model.deleted_at.is_(None)
        )

        # 필터링 조건 추가
        if provider_id:
            query = query.filter(Model.provider_id == provider_id)
        if type_id:
            query = query.filter(Model.type_id == type_id)
        if format_id:
            query = query.filter(Model.format_id == format_id)

        # 검색 조건 추가
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Model.name.ilike(search_term),
                    Model.description.ilike(search_term)
                )
            )

        total = query.count()
        models = query.offset(skip).limit(limit).all()

        return models, total

    def search_catalog_models(
            self,
            db: Session,
            search: Optional[str] = None,
            provider_id: Optional[int] = None,
            type_id: Optional[int] = None,
            format_id: Optional[int] = None,
            skip: int = 0,
            limit: int = 20
    ) -> tuple[List[Model], int]:
        """카탈로그 모델 검색 (데이터와 총 개수 함께 반환)"""
        query = db.query(Model).filter(
            Model.is_catalog == True,
            Model.deleted_at.is_(None)
        )

        # 필터링 조건 추가
        if provider_id:
            query = query.filter(Model.provider_id == provider_id)
        if type_id:
            query = query.filter(Model.type_id == type_id)
        if format_id:
            query = query.filter(Model.format_id == format_id)

        # 검색 조건 추가
        if search:
            search_term = f"%{search}%"
            query = query.filter(
                or_(
                    Model.name.ilike(search_term),
                    Model.description.ilike(search_term)
                )
            )

        total = query.count()
        models = query.offset(skip).limit(limit).all()

        return models, total


# 싱글톤 인스턴스
model_crud = ModelCRUD()