from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(String(50), default="active")  # active, inactive, deleted
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("members.id"))  # 외래키로 변경

    # 관계 설정
    creator = relationship("Member", back_populates="created_services")


class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    # 기본 정보
    name = Column(String(255), nullable=False)  # 이름 (기존 full_name에서 변경)
    member_id = Column(String(100), unique=True, nullable=False, index=True)  # 아이디 (기존 username)
    email = Column(String(255), unique=True, nullable=False, index=True)

    # 비밀번호 관련 (실제로는 해시된 값 저장)
    password_hash = Column(String(255), nullable=False)

    # 연락처
    phone = Column(String(50))  # 연락처

    # 역할 구분
    role = Column(String(50), default="user")  # "admin" 또는 "user"

    # 기존 필드들
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)

    # 설명 필드 (선택사항)
    description = Column(Text)

    # 관계 설정 - Member가 생성한 서비스들
    created_services = relationship("Service", back_populates="creator")