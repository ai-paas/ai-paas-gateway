"""Add soft delete fields to prompts table

Revision ID: b3a1f7c9d201
Revises: 73153bc5a965
Create Date: 2026-04-23 19:05:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b3a1f7c9d201"
down_revision: Union[str, None] = "73153bc5a965"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("prompts", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("prompts", sa.Column("deleted_by", sa.String(length=100), nullable=True))
    op.add_column(
        "prompts",
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.create_index("idx_prompts_active", "prompts", ["surro_prompt_id", "is_active", "deleted_at"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_prompts_active", table_name="prompts")
    op.drop_column("prompts", "is_active")
    op.drop_column("prompts", "deleted_by")
    op.drop_column("prompts", "deleted_at")
