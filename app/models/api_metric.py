from sqlalchemy import BigInteger, Column, DateTime, Index, Integer, String, UniqueConstraint
from sqlalchemy.sql import func

from .base import Base


class ApiRequestHistogram(Base):
    """API 요청 응답시간 히스토그램 버킷 (시간/분 단위 집계).

    bucket_ts: 집계 단위(분 또는 시간) 시작 시각.
    le_bucket_ms: bucket 상한 (Prometheus-like). +∞ 버킷은 999999로.
    count: 해당 bucket 누적 횟수.

    p95는 누적합 보간으로 근사 — `api_metrics_service`에서 계산.
    """
    __tablename__ = "api_request_histograms"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    bucket_ts = Column(DateTime(timezone=True), nullable=False, comment="집계 bucket 시작 시각")
    path_pattern = Column(String(255), nullable=False, comment="경로 패턴 (path param 제거)")
    status_class = Column(String(4), nullable=False, comment="2xx/3xx/4xx/5xx")
    le_bucket_ms = Column(Integer, nullable=False, comment="bucket 상한(ms). +Inf는 999999")
    count = Column(Integer, nullable=False, default=0)
    sum_duration_ms = Column(Integer, nullable=False, default=0, comment="해당 bucket의 duration 합")
    max_duration_ms = Column(Integer, nullable=False, default=0, comment="해당 bucket의 최대 duration")

    generated_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("bucket_ts", "path_pattern", "status_class", "le_bucket_ms",
                         name="uq_api_hist_key"),
        Index("idx_api_hist_bucket_ts", "bucket_ts"),
        Index("idx_api_hist_path_status", "path_pattern", "status_class", "bucket_ts"),
        {"comment": "API 요청 응답시간 히스토그램 (p95 근사용)"},
    )


class ProviderHealthSnapshot(Base):
    """외부 provider health probe 결과 스냅샷."""
    __tablename__ = "provider_health_snapshots"

    id = Column(
        BigInteger().with_variant(Integer, "sqlite"),
        primary_key=True,
        autoincrement=True,
        index=True,
    )
    ts = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    provider = Column(String(32), nullable=False, comment="mlops/surro/hub_connect/any_cloud")
    status = Column(String(16), nullable=False, comment="healthy/unhealthy/disabled/error")
    latency_ms = Column(Integer, nullable=True)
    error = Column(String(500), nullable=True)

    __table_args__ = (
        Index("idx_provider_health_ts", "ts"),
        Index("idx_provider_health_provider_ts", "provider", "ts"),
        {"comment": "Provider health probe 이력"},
    )
