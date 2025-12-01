from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index, Sequence
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from . import Base
from datetime import datetime


class Workflow(Base):
    __tablename__ = "workflows"

    # PostgreSQL SERIAL 타입을 명시적으로 사용
    id = Column(
        Integer,
        Sequence('workflows_id_seq'),
        primary_key=True,
        index=True,
        autoincrement=True
    )

    # 실제 데이터 컬럼
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

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
    surro_workflow_id = Column(String(255), nullable=False, index=True)  # UUID 문자열

    creator = relationship("Member", backref="created_workflows")

    __table_args__ = (
        Index('idx_workflows_surro_id', 'surro_workflow_id', unique=True),
        {'extend_existing': True}
    )