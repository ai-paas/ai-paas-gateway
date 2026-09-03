"""Add service_card_snapshots and service_metric_snapshots (dashboard cache)

Revision ID: f1a2b3c4d5e6
Revises: e7fa0123b456
Create Date: 2026-06-08 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e7fa0123b456"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_card_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("surro_service_id", sa.String(length=255), nullable=False,
                  comment="MLOps 서비스 UUID"),
        sa.Column("workflow_count", sa.Integer(), nullable=False, server_default="0",
                  comment="연결 워크플로우 수"),
        sa.Column("model_count", sa.Integer(), nullable=True,
                  comment="사용 모델 distinct 수. 미집계/집계 실패 시 NULL"),
        sa.Column("refreshed_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False,
                  comment="이 행이 갱신된 시각"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("surro_service_id", name="uq_service_card_surro_id"),
        comment="대시보드 서비스 현황 카드 캐시",
    )
    op.create_index(op.f("ix_service_card_snapshots_id"), "service_card_snapshots",
                    ["id"], unique=False)
    op.create_index("idx_service_card_refreshed", "service_card_snapshots",
                    ["refreshed_at"], unique=False)

    op.create_table(
        "service_metric_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("surro_service_id", sa.String(length=255), nullable=False,
                  comment="MLOps 서비스 UUID"),
        sa.Column("period", sa.String(length=4), nullable=False, comment="1h/1d/1w"),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_users", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("token_usage", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("avg_interaction_count", sa.Float(), nullable=False, server_default="0"),
        sa.Column("response_time_ms", sa.Float(), nullable=True,
                  comment="평균 응답시간(ms). 없으면 NULL"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rate", sa.Float(), nullable=True, comment="성공률(%). 없으면 NULL"),
        sa.Column("aggregated_at", sa.DateTime(timezone=True), nullable=True,
                  comment="MLOps 집계 기준 끝점"),
        sa.Column("refreshed_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False,
                  comment="이 행이 갱신된 시각"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("surro_service_id", "period",
                            name="uq_service_metric_surro_period"),
        comment="대시보드 서비스 모니터링(기간별) 캐시",
    )
    op.create_index(op.f("ix_service_metric_snapshots_id"), "service_metric_snapshots",
                    ["id"], unique=False)
    op.create_index("idx_service_metric_surro", "service_metric_snapshots",
                    ["surro_service_id"], unique=False)
    op.create_index("idx_service_metric_period", "service_metric_snapshots",
                    ["period"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_service_metric_period", table_name="service_metric_snapshots")
    op.drop_index("idx_service_metric_surro", table_name="service_metric_snapshots")
    op.drop_index(op.f("ix_service_metric_snapshots_id"), table_name="service_metric_snapshots")
    op.drop_table("service_metric_snapshots")

    op.drop_index("idx_service_card_refreshed", table_name="service_card_snapshots")
    op.drop_index(op.f("ix_service_card_snapshots_id"), table_name="service_card_snapshots")
    op.drop_table("service_card_snapshots")
