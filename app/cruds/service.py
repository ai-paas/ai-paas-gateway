from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional, Tuple
from app.models.service import Service
from app.schemas.service import ServiceCreate, ServiceUpdate


class ServiceCRUD:
    def create_service(
            self,
            db: Session,
            service: ServiceCreate,
            created_by: str,
            surro_service_id: str
    ) -> Service:
        """서비스 생성 (외부 API 호출 후 우리 DB 저장)"""
        db_service = Service(
            name=service.name,
            description=service.description,
            tags=service.tags,
            created_by=created_by,
            surro_service_id=surro_service_id
        )
        db.add(db_service)
        db.commit()
        db.refresh(db_service)
        return db_service

    def get_service(self, db: Session, service_id: int) -> Optional[Service]:
        """내부 ID로 조회"""
        return db.query(Service).filter(Service.id == service_id).first()

    def get_service_by_surro_id(self, db: Session, surro_service_id: str) -> Optional[Service]:
        """외부 API UUID로 조회"""
        return db.query(Service).filter(Service.surro_service_id == surro_service_id).first()

    def get_services(
            self,
            db: Session,
            skip: int = 0,
            limit: int = 100,
            search: Optional[str] = None,
            creator_name: Optional[str] = None
    ) -> Tuple[List[Service], int]:
        """서비스 목록 조회"""
        query = db.query(Service)

        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    Service.name.ilike(search_filter),
                    Service.description.ilike(search_filter)
                )
            )

        if creator_name:
            query = query.filter(Service.created_by.ilike(f"%{creator_name}%"))

        total = query.count()
        services = query.offset(skip).limit(limit).all()
        return services, total

    def update_service(
            self,
            db: Session,
            service_id: int,
            service_update: ServiceUpdate
    ) -> Optional[Service]:
        """내부 ID로 서비스 수정"""
        db_service = self.get_service(db, service_id)
        if db_service:
            update_data = service_update.model_dump(exclude_unset=True, exclude_none=True)
            for key, value in update_data.items():
                setattr(db_service, key, value)
            db.commit()
            db.refresh(db_service)
        return db_service

    def update_service_by_surro_id(
            self,
            db: Session,
            surro_service_id: str,
            service_update: ServiceUpdate
    ) -> Optional[Service]:
        """UUID로 서비스 수정"""
        db_service = self.get_service_by_surro_id(db, surro_service_id)
        if db_service:
            update_data = service_update.model_dump(exclude_unset=True, exclude_none=True)
            for key, value in update_data.items():
                setattr(db_service, key, value)
            db.commit()
            db.refresh(db_service)
        return db_service

    def delete_service(self, db: Session, service_id: int) -> bool:
        """내부 ID로 서비스 삭제"""
        db_service = self.get_service(db, service_id)
        if db_service:
            db.delete(db_service)
            db.commit()
            return True
        return False

    def delete_service_by_surro_id(self, db: Session, surro_service_id: str) -> bool:
        """UUID로 서비스 삭제"""
        db_service = self.get_service_by_surro_id(db, surro_service_id)
        if db_service:
            db.delete(db_service)
            db.commit()
            return True
        return False


# 전역 CRUD 인스턴스
service_crud = ServiceCRUD()