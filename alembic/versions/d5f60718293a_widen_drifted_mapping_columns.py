"""Widen drifted mapping cache columns to match the ORM models.

Installations created before the ORM baseline still carry the narrow
pre-baseline widths (``prompts.content`` as ``varchar(250)`` etc.), so caching
an upstream prompt whose content exceeds 250 chars fails with
``StringDataRightTruncation``. Widening a varchar (or converting it to text)
is a catalog-only change in PostgreSQL, so no table rewrite happens.

Revision ID: d5f60718293a
Revises: c4e5f6071829
Create Date: 2026-08-14 17:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d5f60718293a"
down_revision: Union[str, Sequence[str], None] = "c4e5f6071829"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, column, target type, existing_nullable)
# target type mirrors app/models/*.py; existing_nullable is the pre-baseline DB
# state, which this migration deliberately leaves alone.
_TARGETS = (
    ("prompts", "name", sa.String(length=255), True),
    ("prompts", "description", sa.Text(), True),
    ("prompts", "content", sa.Text(), True),
    ("prompts", "created_by", sa.String(length=100), True),
    ("knowledge_bases", "name", sa.String(length=255), True),
    ("knowledge_bases", "description", sa.Text(), True),
    ("knowledge_bases", "collection_name", sa.String(length=255), True),
    ("knowledge_bases", "created_by", sa.String(length=100), True),
    ("services", "surro_service_id", sa.String(length=255), False),
    ("workflows", "surro_workflow_id", sa.String(length=255), False),
)


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for table, column, target_type, nullable in _TARGETS:
        op.alter_column(
            table,
            column,
            type_=target_type,
            existing_nullable=nullable,
        )


def downgrade() -> None:
    # No-op: narrowing back would truncate cached upstream values.
    pass
