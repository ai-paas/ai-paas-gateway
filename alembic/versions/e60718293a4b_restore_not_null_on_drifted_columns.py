"""Restore NOT NULL and timestamp defaults on pre-baseline mapping tables.

Companion to ``d5f60718293a`` (column widths). The same pre-baseline
installations also left ``prompts`` / ``knowledge_bases`` / ``services`` /
``workflows`` columns nullable and dropped the ``now()`` server defaults on
``created_at`` / ``updated_at``, while the ORM declares them ``nullable=False``
with a server default.

Timestamps are backfilled with ``now()`` before the constraint is applied.
Value-bearing columns cannot be invented, so a column that still holds NULLs is
skipped with a warning instead of aborting the whole upgrade — rerunning the
migration after cleaning the rows finishes the job.

Revision ID: e60718293a4b
Revises: d5f60718293a
Create Date: 2026-08-14 18:05:00.000000

"""
import logging
from typing import Sequence, Union

from alembic import op
from sqlalchemy import text


revision: str = "e60718293a4b"
down_revision: Union[str, Sequence[str], None] = "d5f60718293a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

_TABLES = ("prompts", "knowledge_bases", "services", "workflows")
_TIMESTAMP_COLUMNS = ("created_at", "updated_at")
# 값을 임의로 만들 수 없는 컬럼 — NULL 이 남아 있으면 건너뛴다.
_VALUE_COLUMNS = {
    "prompts": ("name", "content", "created_by"),
    "knowledge_bases": ("name", "collection_name", "created_by", "surro_knowledge_id"),
    "services": (),
    "workflows": (),
}


def _null_count(bind, table: str, column: str) -> int:
    return bind.execute(text(f'SELECT count(*) FROM "{table}" WHERE "{column}" IS NULL')).scalar()


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for table in _TABLES:
        for column in _TIMESTAMP_COLUMNS:
            bind.execute(text(
                f'UPDATE "{table}" SET "{column}" = now() WHERE "{column}" IS NULL'
            ))
            op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET DEFAULT now()')
            op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL')

        for column in _VALUE_COLUMNS[table]:
            remaining = _null_count(bind, table, column)
            if remaining:
                logger.warning(
                    "%s.%s: %d NULL row(s) remain; leaving column nullable. "
                    "Clean the rows and rerun this migration.",
                    table, column, remaining,
                )
                continue
            op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" SET NOT NULL')


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in _TABLES:
        for column in _TIMESTAMP_COLUMNS:
            op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL')
        for column in _VALUE_COLUMNS[table]:
            op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" DROP NOT NULL')
