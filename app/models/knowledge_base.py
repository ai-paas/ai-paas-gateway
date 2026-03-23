from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Index, Sequence
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.models import Base  # 이 import가 중요!
from datetime import datetime


class KnowledgeBase(Base):  # Base를 상속받아야 함!
    __tablename__ = "knowledge_bases"

    # PostgreSQL SERIAL 타입을 명시적으로 사용
    id = Column(
        Integer,
        Sequence('knowledge_bases_id_seq'),
        primary_key=True,
        index=True,
        autoincrement=True
    )

    # 실제 데이터 컬럼 (외부 API에서 받은 핵심 데이터만)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    collection_name = Column(String(255), nullable=False)

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
    surro_knowledge_id = Column(Integer, nullable=False, index=True)

    # Relationship
    creator = relationship("Member", backref="created_knowledge_bases")

    # 인덱스 설정
    __table_args__ = (
        Index('idx_knowledge_bases_surro_id', 'surro_knowledge_id', unique=True),
        {'extend_existing': True}
    )