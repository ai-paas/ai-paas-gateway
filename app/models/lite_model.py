from sqlalchemy import Boolean, Column, DateTime, Index, Integer, JSON, String
from sqlalchemy.sql import func

from . import Base


class LiteModelData(Base):
    __tablename__ = "lite_model_data"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True, comment="Lite model data ID")
    request_path = Column(String(500), nullable=True, comment="Upstream API path")
    request_method = Column(String(10), nullable=True, comment="HTTP method")
    payload = Column(JSON, nullable=True, comment="Cached lite-model payload")
    member_id = Column(String(50), nullable=True, comment="Requester member_id")
    cache_key = Column(String(255), nullable=True, comment="Cache key")
    hit_count = Column(Integer, default=0, nullable=False, comment="Cache hit count")
    expires_at = Column(DateTime(timezone=True), nullable=True, comment="Cache expiration")
    is_active = Column(Boolean, default=True, nullable=False, comment="Active flag")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, comment="Created at")
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        comment="Updated at",
    )

    __table_args__ = (
        Index("idx_lite_model_data_expires", "expires_at"),
        Index("idx_lite_model_data_active", "is_active"),
        Index("idx_lite_model_data_created", "created_at"),
        Index("idx_lite_model_data_member_created", "member_id", "created_at"),
        {"comment": "Lite Model generic cache/data table"},
    )

    def __repr__(self):
        return f"<LiteModelData(id={self.id}, cache_key={self.cache_key}, hits={self.hit_count})>"
