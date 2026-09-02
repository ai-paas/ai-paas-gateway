from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, JSON, String
from sqlalchemy.sql import func

from .base import Base


class AuditLog(Base):
    """관리자 대시보드 / 감사 추적용 활동 로그.

    발행 위치: service/CRUD 레이어(트랜잭션 내). route에서 직접 발행 금지.
    request_id는 RequestLoggingMiddleware의 X-Request-ID와 연결되어 access.log 추적 가능.
    """
    __tablename__ = "audit_logs"

    # PostgreSQL은 BIGSERIAL, SQLite는 INTEGER(테스트 환경에서 ROWID 자동증가 필요)
    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    action = Column(String(64), nullable=False, comment="create/update/delete/restore/login/logout/permission_change")
    resource_type = Column(String(64), nullable=False, comment="service/workflow/model/...")
    resource_id = Column(String(255), nullable=True, comment="gateway PK 또는 surro id")
    actor_member_id = Column(String(100), nullable=False, comment="액션 수행 사용자")
    target_member_id = Column(String(100), nullable=True, comment="대상 사용자(권한 변경 등)")
    # DB 컬럼명은 'metadata' (계획서 유지). Python 속성명은 Base.metadata와의 혼동을 피해 metadata_json.
    metadata_json = Column("metadata", JSON, nullable=True, comment="액션 부가 정보(JSON)")
    request_id = Column(String(64), nullable=True, comment="X-Request-ID와 연결")
    ip = Column(String(64), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="기록 시간"
    )

    __table_args__ = (
        Index("idx_audit_created_at", "created_at"),
        Index("idx_audit_resource", "resource_type", "created_at"),
        Index("idx_audit_actor", "actor_member_id", "created_at"),
        Index("idx_audit_request_id", "request_id"),
        {"comment": "관리자 대시보드 활동 / 감사 로그"},
    )
