"""Add soft-delete fields to workflows and services.

Revision ID: a2c3d4e5f607
Revises: f1a2b3c4d5e6
Create Date: 2026-07-13 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a2c3d4e5f607"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name, index_name, id_column in (
        ("workflows", "idx_workflows_active", "surro_workflow_id"),
        ("services", "idx_services_active", "surro_service_id"),
    ):
        op.add_column(
            table_name,
            sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("deleted_by", sa.String(length=100), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column(
                "is_active",
                sa.Boolean(),
                server_default=sa.text("true"),
                nullable=False,
            ),
        )
        op.create_index(
            index_name,
            table_name,
            [id_column, "is_active", "deleted_at"],
            unique=False,
        )


def downgrade() -> None:
    for table_name, index_name in (
        ("services", "idx_services_active"),
        ("workflows", "idx_workflows_active"),
    ):
        op.drop_index(index_name, table_name=table_name)
        op.drop_column(table_name, "is_active")
        op.drop_column(table_name, "deleted_by")
        op.drop_column(table_name, "deleted_at")
