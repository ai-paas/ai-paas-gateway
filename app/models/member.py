from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import relationship
from datetime import datetime
from . import Base

class Member(Base):
    __tablename__ = "members"

    id = Column(Integer, primary_key=True, index=True)
    # 기본 정보
    name = Column(String(255), nullable=False)
    member_id = Column(String(100), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)

    # 비밀번호 관련
    password_hash = Column(String(255), nullable=False)

    # 연락처
    phone = Column(String(50))

    # 역할 구분
    role = Column(String(50), default="user")

    # 기존 필드들
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime)

    # 설명 필드
    description = Column(Text)

    # backref 방식에서는 여기에 relationship을 정의하지 않음
    # Service와 Workflow에서 backref로 자동 생성됨