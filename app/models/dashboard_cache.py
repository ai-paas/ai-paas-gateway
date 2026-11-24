"""개인 대시보드 서비스 카드·모니터링 캐시 테이블.

MLOps 서비스 detail 호출(서비스 수만큼 N+1)을 매 요청마다 하지 않도록, 서비스별
워크플로우/모델 수와 기간별(1h/1d/1w) 모니터링 메트릭을 스냅샷으로 저장한다.

- 채우는 주체:
  1. `me_dashboard_service.refresh_member_services_live()` — 개인 대시보드 첫 요청/캐시 TTL 만료 시 본인 서비스만 즉시 갱신
  2. 스케줄러 `job_refresh_dashboard_services()` — 전체 서비스 주기 pre-warm
- 읽는 주체: `/me/dashboard/services`, `/me/dashboard/monitoring`
  소유권/이름은 항상 gateway `services` 테이블(JOIN)을 기준으로 하고, 이 스냅샷은 캐시 수치만 보관한다
  (created_by/name 미중복 저장 → 단일 출처 유지).
"""
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from .base import Base


class ServiceCardSnapshot(Base):
    """서비스 현황 카드용 캐시 (서비스당 1행). 워크플로우 수 / 사용 모델 수."""

    __tablename__ = "service_card_snapshots"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    surro_service_id = Column(String(255), nullable=False, comment="MLOps 서비스 UUID")
    workflow_count = Column(Integer, nullable=False, default=0, comment="연결 워크플로우 수")
    model_count = Column(
        Integer, nullable=True, comment="사용 모델 distinct 수. 미집계/집계 실패 시 NULL"
    )
    refreshed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="이 행이 갱신된 시각",
    )

    __table_args__ = (
        UniqueConstraint("surro_service_id", name="uq_service_card_surro_id"),
        Index("idx_service_card_refreshed", "refreshed_at"),
        {"comment": "대시보드 서비스 현황 카드 캐시"},
    )


class ServiceMetricSnapshot(Base):
    """서비스 모니터링 캐시 (서비스 × 기간 = 1행). period ∈ 1h/1d/1w."""

    __tablename__ = "service_metric_snapshots"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    surro_service_id = Column(String(255), nullable=False, comment="MLOps 서비스 UUID")
    period = Column(String(4), nullable=False, comment="1h/1d/1w")

    message_count = Column(Integer, nullable=False, default=0)
    active_users = Column(Integer, nullable=False, default=0)
    token_usage = Column(
        BigInteger().with_variant(Integer, "sqlite"), nullable=False, default=0
    )
    avg_interaction_count = Column(Float, nullable=False, default=0.0)
    response_time_ms = Column(Float, nullable=True, comment="평균 응답시간(ms). 없으면 NULL")
    error_count = Column(Integer, nullable=False, default=0)
    success_rate = Column(Float, nullable=True, comment="성공률(%). 없으면 NULL")

    aggregated_at = Column(
        DateTime(timezone=True), nullable=True, comment="MLOps 집계 기준 끝점"
    )
    refreshed_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="이 행이 갱신된 시각",
    )

    __table_args__ = (
        UniqueConstraint(
            "surro_service_id", "period", name="uq_service_metric_surro_period"
        ),
        Index("idx_service_metric_surro", "surro_service_id"),
        Index("idx_service_metric_period", "period"),
        {"comment": "대시보드 서비스 모니터링(기간별) 캐시"},
    )
