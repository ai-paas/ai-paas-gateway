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
    surro_prompt_id = Column(Integer, nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    creator = relationship("Member", backref="created_prompts")

    __table_args__ = (
        Index('idx_prompts_surro_prompt_id', 'surro_prompt_id', unique=True),
        Index('idx_prompts_active', 'surro_prompt_id', 'is_active', 'deleted_at'),
        {'extend_existing': True}
    )
