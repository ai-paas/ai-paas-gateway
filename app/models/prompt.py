from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from . import Base
from datetime import datetime


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

    creator = relationship("Member", backref="created_prompts")

    __table_args__ = (
        Index('idx_prompts_surro_prompt_id', 'surro_prompt_id', unique=True),
        {'extend_existing': True}
    )