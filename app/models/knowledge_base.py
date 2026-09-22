from datetime import datetime

from sqlalchemy import JSON, Column, Integer, String, Text, DateTime, Boolean, ForeignKey, Index, Sequence
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.models.base import Base


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
    updated_by = Column(
        String(100),
        nullable=True,
        comment="수정자 member_id"
    )
    surro_knowledge_id = Column(Integer, nullable=False)

    # 소프트 삭제
    deleted_at = Column(
        DateTime(timezone=True),
        nullable=True,
        comment="삭제 시간"
    )
    deleted_by = Column(
        String(100),
        nullable=True,
        comment="삭제자 member_id"
    )
    is_active = Column(
        Boolean,
        default=True,
        nullable=False,
        comment="활성화 상태"
    )

    # Relationship
    creator = relationship("Member", backref="created_knowledge_bases")

    # 인덱스 설정
    __table_args__ = (
        Index(
            'idx_knowledge_bases_active',
            'surro_knowledge_id',
            'is_active',
            'deleted_at',
        ),
        Index(
            'idx_knowledge_bases_unique_active',
            'surro_knowledge_id',
            unique=True,
            postgresql_where=Column('deleted_at').is_(None),
            sqlite_where=Column('deleted_at').is_(None),
        ),
        {'extend_existing': True}
    )


class AttemptState:
    """knowledge_base_create_attempts.state 허용값."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    ORPHAN_SUSPECT = "orphan_suspect"
    ABANDONED = "abandoned"
    RECOVERED = "recovered"


class KnowledgeBaseCreateAttempt(Base):
    __tablename__ = "knowledge_base_create_attempts"

    id = Column(Integer, Sequence("knowledge_base_create_attempts_id_seq"), primary_key=True, index=True, autoincrement=True)

    member_id = Column(String(100), ForeignKey("members.member_id"), nullable=False)
    name = Column(String(255), nullable=False)
    filename = Column(String(255), nullable=True)
    request_id = Column(String(255), nullable=False)

    upstream_snapshot = Column(JSON, nullable=True, comment="POST 직전 업스트림 KB id 집합")
    state = Column(String(32), nullable=False, index=True)
    failure_kind      = Column(String(64), nullable=True)

    started_at  = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    resolved_surro_id = Column(Integer, nullable=True)
    recovered_at      = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # 살아있는 시도만 빠르게 조회하기 위한 인덱스
        Index("idx_kb_attempts_live", "state", "started_at"),
        # 같은 이름, 같은 파일로 성공한 재시도 검출을 위한 인덱스
        Index("idx_kb_attempts_dedup", "member_id", "name", "filename", "state")
    )
