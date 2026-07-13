"""Add active-only unique indexes for workflow and service mappings.

Revision ID: c4e5f6071829
Revises: b3d4e5f60718
Create Date: 2026-07-13 00:20:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "c4e5f6071829"
down_revision: Union[str, Sequence[str], None] = "b3d4e5f60718"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for index_name, table_name in (
        ("idx_workflows_surro_id", "workflows"),
        ("ix_workflows_surro_workflow_id", "workflows"),
        ("idx_services_surro_service_id", "services"),
        ("ix_services_surro_service_id", "services"),
    ):
        op.drop_index(index_name, table_name=table_name, if_exists=True)

    op.create_index(
        "idx_workflows_unique_active",
        "workflows",
        ["surro_workflow_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "idx_services_unique_active",
        "services",
        ["surro_service_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("idx_services_unique_active", table_name="services")
    op.drop_index("idx_workflows_unique_active", table_name="workflows")
    op.create_index(
        "idx_workflows_surro_id",
        "workflows",
        ["surro_workflow_id"],
        unique=True,
    )
    op.create_index(
        "ix_workflows_surro_workflow_id",
        "workflows",
        ["surro_workflow_id"],
        unique=False,
    )
    op.create_index(
        "idx_services_surro_service_id",
        "services",
        ["surro_service_id"],
        unique=True,
    )
    op.create_index(
        "ix_services_surro_service_id",
        "services",
        ["surro_service_id"],
        unique=False,
    )
