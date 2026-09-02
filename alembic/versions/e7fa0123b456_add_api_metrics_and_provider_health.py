"""Add api_request_histograms and provider_health_snapshots

Revision ID: e7fa0123b456
Revises: d6e9f01a2345
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7fa0123b456"
down_revision: Union[str, Sequence[str], None] = "d6e9f01a2345"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "api_request_histograms",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("bucket_ts", sa.DateTime(timezone=True), nullable=False,
                  comment="집계 bucket 시작 시각"),
        sa.Column("path_pattern", sa.String(length=255), nullable=False,
                  comment="경로 패턴 (path param 제거)"),
        sa.Column("status_class", sa.String(length=4), nullable=False,
                  comment="2xx/3xx/4xx/5xx"),
        sa.Column("le_bucket_ms", sa.Integer(), nullable=False,
                  comment="bucket 상한(ms). +Inf는 999999"),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sum_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_duration_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("generated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bucket_ts", "path_pattern", "status_class", "le_bucket_ms",
                            name="uq_api_hist_key"),
        comment="API 요청 응답시간 히스토그램 (p95 근사용)",
    )
    op.create_index(op.f("ix_api_request_histograms_id"), "api_request_histograms",
                    ["id"], unique=False)
    op.create_index("idx_api_hist_bucket_ts", "api_request_histograms",
                    ["bucket_ts"], unique=False)
    op.create_index("idx_api_hist_path_status", "api_request_histograms",
                    ["path_pattern", "status_class", "bucket_ts"], unique=False)

    op.create_table(
        "provider_health_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False,
                  comment="mlops/surro/hub_connect/any_cloud"),
        sa.Column("status", sa.String(length=16), nullable=False,
                  comment="healthy/unhealthy/disabled/error"),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(length=500), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        comment="Provider health probe 이력",
    )
    op.create_index(op.f("ix_provider_health_snapshots_id"), "provider_health_snapshots",
                    ["id"], unique=False)
    op.create_index("idx_provider_health_ts", "provider_health_snapshots",
                    ["ts"], unique=False)
    op.create_index("idx_provider_health_provider_ts", "provider_health_snapshots",
                    ["provider", "ts"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_provider_health_provider_ts", table_name="provider_health_snapshots")
    op.drop_index("idx_provider_health_ts", table_name="provider_health_snapshots")
    op.drop_index(op.f("ix_provider_health_snapshots_id"), table_name="provider_health_snapshots")
    op.drop_table("provider_health_snapshots")

    op.drop_index("idx_api_hist_path_status", table_name="api_request_histograms")
    op.drop_index("idx_api_hist_bucket_ts", table_name="api_request_histograms")
    op.drop_index(op.f("ix_api_request_histograms_id"), table_name="api_request_histograms")
    op.drop_table("api_request_histograms")
