from datetime import datetime

from sqlalchemy import Boolean, Column, Integer, String, Text, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from .base import Base


class Service(Base):
    __tablename__ = "services"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    tags = Column(JSON, nullable=True)

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
    surro_service_id = Column(String(255), nullable=False, index=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_by = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

    creator = relationship("Member", backref="created_services")

    __table_args__ = (
        Index('idx_services_active', 'surro_service_id', 'is_active', 'deleted_at'),
        Index(
            'idx_services_unique_active',
            'surro_service_id',
            unique=True,
            postgresql_where=Column('deleted_at').is_(None),
            sqlite_where=Column('deleted_at').is_(None),
        ),
        {'extend_existing': True}
    )
