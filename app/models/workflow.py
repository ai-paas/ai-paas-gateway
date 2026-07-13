from datetime import datetime

from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, Index, Sequence
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base


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
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    creator = relationship("Member", backref="created_workflows")

    __table_args__ = (
        Index('idx_workflows_active', 'surro_workflow_id', 'is_active', 'deleted_at'),
        Index(
            'idx_workflows_unique_active',
            'surro_workflow_id',
            unique=True,
            postgresql_where=Column('deleted_at').is_(None),
            sqlite_where=Column('deleted_at').is_(None),
        ),
        {'extend_existing': True}
    )
