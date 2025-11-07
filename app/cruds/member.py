from sqlalchemy.orm import Session
from sqlalchemy import and_, or_
from typing import List, Optional
from datetime import datetime
from passlib.context import CryptContext
from app.models import Member
from app.schemas.member import MemberCreate, MemberUpdate

# 비밀번호 해싱을 위한 설정
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


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

    def get_member(self, db: Session, member_id: str, include_inactive: bool = False) -> Optional[Member]:
        query = db.query(Member).filter(Member.member_id == member_id)
        if not include_inactive:
            query = query.filter(Member.is_active == True)
        return query.first()

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
        role: Optional[str] = None,
    ) -> tuple[List[Member], int]:
        """전체 멤버 목록 조회 (활성/비활성 필터링 가능)"""
        query = db.query(Member)

        # 검색어 필터
        if search:
            search_filter = f"%{search}%"
            query = query.filter(
                or_(
                    Member.member_id.ilike(search_filter),
                    Member.name.ilike(search_filter),
                    Member.email.ilike(search_filter)
                )
            )

        # 역할(role) 필터
        if role:
            query = query.filter(Member.role == role)

        total = query.count()
        members = query.offset(skip).limit(limit).all()
        return members, total

    def update_member(self, db: Session, member_id: str, member_update: MemberUpdate) -> Optional[Member]:
        db_member = self.get_member(db, member_id, include_inactive=True)
        if db_member:
            update_data = member_update.dict(exclude_unset=True)

            # 비밀번호 수정 시 해싱
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
        db_member = self.get_member(db, member_id, include_inactive=True)
        if db_member:
            db_member.is_active = False
            db_member.updated_at = datetime.utcnow()
            db.commit()
            return True
        return False


# 전역 CRUD 인스턴스
member_crud = MemberCRUD()