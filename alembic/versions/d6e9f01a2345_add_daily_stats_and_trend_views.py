"""Add daily_stats table and trend views (PG only)

Revision ID: d6e9f01a2345
Revises: c5d8e9f01234
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d6e9f01a2345"
down_revision: Union[str, Sequence[str], None] = "c5d8e9f01234"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# soft-delete 도메인은 (table_name, has_soft_delete=True)
_ASSET_DOMAINS = [
    ("services", "service", False),
    ("workflows", "workflow", False),
    ("models", "model", True),
    ("model_improvements", "model_improvement", True),
    ("datasets", "dataset", True),
    ("experiments", "experiment", True),
    ("knowledge_bases", "knowledge_base", True),
    ("prompts", "prompt", True),
]


def _view_select_sql() -> str:
    """모든 자산 도메인의 일별 created/deleted 카운트를 UNION한 SELECT.

    metric 컬럼:
      - 'created'  : 생성 기준 (created_at)
      - 'deleted'  : soft-delete 기준 (deleted_at IS NOT NULL일 때만)
    """
    parts = []
    for table, domain, has_soft in _ASSET_DOMAINS:
        parts.append(
            f"""
            SELECT DATE_TRUNC('day', created_at)::date AS bucket,
                   '{domain}' AS domain,
                   'created' AS metric,
                   COUNT(*)::int AS value
            FROM {table}
            WHERE created_at IS NOT NULL
            GROUP BY 1
            """
        )
        if has_soft:
            parts.append(
                f"""
                SELECT DATE_TRUNC('day', deleted_at)::date AS bucket,
                       '{domain}' AS domain,
                       'deleted' AS metric,
                       COUNT(*)::int AS value
                FROM {table}
                WHERE deleted_at IS NOT NULL
                GROUP BY 1
                """
            )

    # signup (Member.created_at) - hard delete라 deleted는 없음
    parts.append(
        """
        SELECT DATE_TRUNC('day', created_at)::date AS bucket,
               'signup' AS domain,
               'created' AS metric,
               COUNT(*)::int AS value
        FROM members
        WHERE created_at IS NOT NULL
        GROUP BY 1
        """
    )

    return " UNION ALL ".join(parts)


def upgrade() -> None:
    # 1. daily_stats 테이블 — 어떤 DB든 동일하게 생성
    op.create_table(
        "daily_stats",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("date", sa.Date(), nullable=False, comment="집계 기준 일자"),
        sa.Column("domain", sa.String(length=64), nullable=False,
                  comment="service/workflow/.../signup"),
        sa.Column("metric", sa.String(length=32), nullable=False,
                  comment="created/deleted/active/inactive/signup"),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("dimensions", sa.JSON(), nullable=True, comment="부가 메타(JSON)"),
        sa.Column("generated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False,
                  comment="이 행이 채워진 시각"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("date", "domain", "metric", name="uq_daily_stats_date_domain_metric"),
        comment="관리자 대시보드 트렌드/시계열용 일별 집계 캐시",
    )
    op.create_index(op.f("ix_daily_stats_id"), "daily_stats", ["id"], unique=False)
    op.create_index("idx_daily_stats_date", "daily_stats", ["date"], unique=False)
    op.create_index("idx_daily_stats_domain_metric_date", "daily_stats",
                    ["domain", "metric", "date"], unique=False)

    # 2. PostgreSQL view + materialized view — PG에서만
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    select_sql = _view_select_sql()

    op.execute(f"CREATE OR REPLACE VIEW v_daily_trends AS {select_sql}")

    op.execute(f"CREATE MATERIALIZED VIEW IF NOT EXISTS mv_daily_trends AS {select_sql} WITH NO DATA")
    # CONCURRENTLY refresh 위해 unique index 필수
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_mv_daily_trends_key "
        "ON mv_daily_trends (bucket, domain, metric)"
    )
    op.execute("REFRESH MATERIALIZED VIEW mv_daily_trends")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_daily_trends")
        op.execute("DROP VIEW IF EXISTS v_daily_trends")

    op.drop_index("idx_daily_stats_domain_metric_date", table_name="daily_stats")
    op.drop_index("idx_daily_stats_date", table_name="daily_stats")
    op.drop_index(op.f("ix_daily_stats_id"), table_name="daily_stats")
    op.drop_table("daily_stats")
