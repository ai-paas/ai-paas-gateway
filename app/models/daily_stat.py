from sqlalchemy import BigInteger, Column, Date, DateTime, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.sql import func

from .base import Base


class DailyStat(Base):
    """대시보드 트렌드용 일별 집계 캐시 테이블.

    스케줄러가 매일 0시 직전일 기준으로 재계산해 upsert한다.
    실시간이 필요하면 PostgreSQL view(`v_daily_asset_creation`) 또는 service의 fallback 함수가 raw COUNT.
    """
    __tablename__ = "daily_stats"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    date = Column(Date, nullable=False, comment="집계 기준 일자")
    domain = Column(String(64), nullable=False, comment="service/workflow/.../signup")
    metric = Column(String(32), nullable=False, comment="created/deleted/active/inactive/signup")
    value = Column(Integer, nullable=False, default=0)
    dimensions = Column(JSON, nullable=True, comment="부가 메타(JSON)")
    generated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        comment="이 행이 채워진 시각",
    )

    __table_args__ = (
        UniqueConstraint("date", "domain", "metric", name="uq_daily_stats_date_domain_metric"),
        Index("idx_daily_stats_date", "date"),
        Index("idx_daily_stats_domain_metric_date", "domain", "metric", "date"),
        {"comment": "관리자 대시보드 트렌드/시계열용 일별 집계 캐시"},
    )
