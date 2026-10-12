from datetime import datetime

from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base


class Prompt(Base):
    __tablename__ = "prompts"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)

    # 실제 데이터 컬럼
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    content = Column(Text, nullable=False)
    prompt_variable = Column(JSON, nullable=True)

    # 메타 정보
    created_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=func.now(),
        nullable=False
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        server_default=func.now(),
        onupdate=datetime.utcnow,
        nullable=False
    )

    created_by = Column(String(100), ForeignKey("members.member_id"), nullable=False)
    surro_prompt_id = Column(Integer, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    # 생성 요청은 'auto' 행만 넘겨받는다.
    registered_via = Column(
        String(20), nullable=True,
        comment="'auto' = 조회 경로의 자동 등록이 만든 행. NULL = 생성 API 또는 알 수 없음",
    )

    creator = relationship("Member", backref="created_prompts")

    __table_args__ = (
        Index('idx_prompts_active', 'surro_prompt_id', 'is_active', 'deleted_at'),
        Index(
            'idx_prompts_unique_active',
            'surro_prompt_id',
            unique=True,
            postgresql_where=Column('deleted_at').is_(None),
            sqlite_where=Column('deleted_at').is_(None),
        ),
        {'extend_existing': True}
    )
