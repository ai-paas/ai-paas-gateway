from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime
from passlib.context import CryptContext
from app.models import Service, Member, Workflow
from app.schemas.service import ServiceCreate, ServiceUpdate
from app.schemas.member import MemberCreate, MemberUpdate
from app.schemas.workflow import WorkflowCreate, WorkflowUpdate

# 비밀번호 해싱을 위한 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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


class MemberCRUD:
    def get_password_hash(self, password: str) -> str:
        """비밀번호 해싱"""
        return pwd_context.hash(password)

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """비밀번호 검증"""
        return pwd_context.verify(plain_password, hashed_password)

    def create_member(self, db: Session, member: MemberCreate) -> Member:
        # 비밀번호 해싱
        hashed_password = self.get_password_hash(member.password)
        member_dict = member.dict(exclude={'password', 'password_confirm'})
        member_dict['password_hash'] = hashed_password

        db_member = Member(**member_dict)
        db.add(db_member)
        db.commit()
        db.refresh(db_member)
        return db_member

    def get_member(self, db: Session, member_id: str) -> Optional[Member]:
        """member_id(아이디)로 멤버 조회"""
        return db.query(Member).filter(
            and_(Member.member_id == member_id, Member.is_active == True)
        ).first()

    def get_member_by_email(self, db: Session, email: str) -> Optional[Member]:
        return db.query(Member).filter(
            and_(Member.email == email, Member.is_active == True)
        ).first()

    def get_member_with_services(self, db: Session, member_id: str) -> Optional[Member]:
        return db.query(Member).filter(
            and_(Member.member_id == member_id, Member.is_active == True)
        ).first()

    def get_members(
            self,
            db: Session,
            skip: int = 0,
            limit: int = 100,
            search: Optional[str] = None,
            role: Optional[str] = None
    ) -> tuple[List[Member], int]:
        query = db.query(Member).filter(Member.is_active == True)

        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    Member.member_id.ilike(search_filter),
                    Member.name.ilike(search_filter),
                    Member.email.ilike(search_filter)
                )
            )

        if role:
            query = query.filter(Member.role == role)

        total = query.count()
        members = query.offset(skip).limit(limit).all()
        return members, total

    def update_member(self, db: Session, member_id: str, member_update: MemberUpdate) -> Optional[Member]:
        db_member = self.get_member(db, member_id)
        if db_member:
            update_data = member_update.dict(exclude_unset=True)

            # 비밀번호가 포함된 경우 해싱
            if 'password' in update_data:
                password = update_data.pop('password')
                update_data['password_hash'] = self.get_password_hash(password)

            for key, value in update_data.items():
                setattr(db_member, key, value)

            db_member.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(db_member)
        return db_member

    def update_last_login(self, db: Session, member_id: str) -> Optional[Member]:
        db_member = self.get_member(db, member_id)
        if db_member:
            db_member.last_login = datetime.utcnow()
            db.commit()
            db.refresh(db_member)
        return db_member

    def delete_member(self, db: Session, member_id: str) -> bool:
        db_member = self.get_member(db, member_id)
        if db_member:
            db_member.is_active = False
            db_member.updated_at = datetime.utcnow()
            db.commit()
            return True
        return False

## Surro API 관련 cruds
class WorkflowCRUD:
    def create_workflow(self, db: Session, workflow: WorkflowCreate, created_by: str,
                        workflow_id: str) -> Workflow:
        """워크플로우 생성 (external_workflow_id는 써로 API 호출 후 받은 값)"""
        workflow_data = workflow.dict()
        workflow_data['created_by'] = created_by
        workflow_data['workflow_id'] = workflow_id

        db_workflow = Workflow(**workflow_data)
        db.add(db_workflow)
        db.commit()
        db.refresh(db_workflow)
        return db_workflow

    def get_workflow(self, db: Session, workflow_id: int) -> Optional[Workflow]:
        return db.query(Workflow).filter(
            and_(Workflow.id == workflow_id)
        ).first()

    def get_workflow_with_creator(self, db: Session, workflow_id: int) -> Optional[Workflow]:
        return db.query(Workflow).options(joinedload(Workflow.creator)).filter(
            and_(Workflow.id == workflow_id)
        ).first()

    def get_workflows(
            self,
            db: Session,
            skip: int = 0,
            limit: int = 100,
            search: Optional[str] = None,
            creator_id: Optional[str] = None,
    ) -> tuple[List[Workflow], int]:
        query = db.query(Workflow)

        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    Workflow.name.ilike(search_filter),
                    Workflow.description.ilike(search_filter)
                )
            )

        if creator_id:
            query = query.filter(Workflow.created_by == creator_id)

        total = query.count()
        workflows = query.offset(skip).limit(limit).all()
        return workflows, total

    def get_workflows_by_member(self, db: Session, member_id: str, skip: int = 0, limit: int = 100) -> tuple[
        List[Workflow], int]:
        """특정 멤버가 생성한 워크플로우 조회"""
        query = db.query(Workflow).filter(
            and_(Workflow.created_by == member_id)
        )
        total = query.count()
        workflows = query.offset(skip).limit(limit).all()
        return workflows, total

    def update_workflow(self, db: Session, workflow_id: int, workflow_update: WorkflowUpdate) -> Optional[Workflow]:
        db_workflow = self.get_workflow(db, workflow_id)
        if db_workflow:
            update_data = workflow_update.dict(exclude_unset=True)
            for key, value in update_data.items():
                setattr(db_workflow, key, value)

            db_workflow.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(db_workflow)
        return db_workflow

    def delete_workflow(self, db: Session, workflow_id: int) -> bool:
        """워크플로우 소프트 삭제 (status를 deleted로 변경)"""
        db_workflow = self.get_workflow(db, workflow_id)
        if db_workflow:
            db_workflow.updated_at = datetime.utcnow()
            db.commit()
            return True
        return False

    def get_workflow_by_external_id(self, db: Session, external_workflow_id: str) -> Optional[Workflow]:
        """외부 워크플로우 ID로 조회"""
        return db.query(Workflow).filter(
            and_(Workflow.external_workflow_id == external_workflow_id)
        ).first()


# 전역 CRUD 인스턴스
service_crud = ServiceCRUD()
member_crud = MemberCRUD()
workflow_crud = WorkflowCRUD()