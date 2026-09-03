"""Add reinstall-safe partial unique indexes for prompt and knowledge base.

Revision ID: b3d4e5f60718
Revises: a2c3d4e5f607
Create Date: 2026-07-13 00:10:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b3d4e5f60718"
down_revision: Union[str, Sequence[str], None] = "a2c3d4e5f607"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Initial installations used global unique indexes, which prevent keeping a
    # soft-deleted row when MLOps reuses a numeric ID after reinstall.
    for index_name, table_name in (
        ("idx_prompts_surro_prompt_id", "prompts"),
        ("ix_prompts_surro_prompt_id", "prompts"),
        ("idx_knowledge_bases_surro_id", "knowledge_bases"),
        ("ix_knowledge_bases_surro_knowledge_id", "knowledge_bases"),
    ):
        op.drop_index(index_name, table_name=table_name, if_exists=True)

    op.create_index(
        "idx_prompts_unique_active",
        "prompts",
        ["surro_prompt_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_knowledge_bases_active",
        "knowledge_bases",
        ["surro_knowledge_id", "is_active", "deleted_at"],
        unique=False,
    )
    op.create_index(
        "idx_knowledge_bases_unique_active",
        "knowledge_bases",
        ["surro_knowledge_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_knowledge_bases_unique_active", table_name="knowledge_bases")
    op.drop_index("idx_knowledge_bases_active", table_name="knowledge_bases")
    op.drop_index("idx_prompts_unique_active", table_name="prompts")
    op.create_index(
        "idx_prompts_surro_prompt_id",
        "prompts",
        ["surro_prompt_id"],
        unique=True,
    )
    op.create_index(
        "ix_prompts_surro_prompt_id",
        "prompts",
        ["surro_prompt_id"],
        unique=False,
    )
    op.create_index(
        "idx_knowledge_bases_surro_id",
        "knowledge_bases",
        ["surro_knowledge_id"],
        unique=True,
    )
    op.create_index(
        "ix_knowledge_bases_surro_knowledge_id",
        "knowledge_bases",
        ["surro_knowledge_id"],
        unique=False,
    )
