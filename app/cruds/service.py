from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from app.models import Service
from app.schemas.service import ServiceCreate, ServiceUpdate


class ServiceCRUD:
    def create_service(self, db: Session, service: ServiceCreate, created_by: str) -> Service:
        # ServiceCreate 스키마의 데이터를 dict로 변환하고 created_by 추가
        service_data = service.dict()
        service_data['created_by'] = created_by

        db_service = Service(**service_data)
        db.add(db_service)
        db.commit()
        db.refresh(db_service)
        return db_service

    def get_service(self, db: Session, service_id: int) -> Optional[Service]:
        return db.query(Service).filter(
            and_(Service.id == service_id)
        ).first()

    def get_service_with_details(self, db: Session, service_id: int) -> Optional[Service]:
        return db.query(Service).filter(
            and_(Service.id == service_id)
        ).first()

    def get_services(
            self,
            db: Session,
            skip: int = 0,
            limit: int = 100,
            search: Optional[str] = None,
            creator_name: Optional[str] = None,
            tag: Optional[str] = None
    ) -> tuple[List[Service], int]:
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

        if tag:
            query = query.filter(Service.tag.ilike(f"%{tag}%"))

        total = query.count()
        services = query.offset(skip).limit(limit).all()
        return services, total

    def update_service(self, db: Session, service_id: int, service_update: ServiceUpdate) -> Optional[Service]:
        db_service = self.get_service(db, service_id)
        if db_service:
            update_data = service_update.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_service, key, value)
            db.commit()
            db.refresh(db_service)
        return db_service

    def delete_service(self, db: Session, service_id: int) -> bool:
        db_service = self.get_service(db, service_id)
        if db_service:
            db.commit()
            return True
        return False


# 전역 CRUD 인스턴스
service_crud = ServiceCRUD()