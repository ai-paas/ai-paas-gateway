"""Add audit_logs table

Revision ID: c5d8e9f01234
Revises: b3a1f7c9d201
Create Date: 2026-05-22 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d8e9f01234"
down_revision: Union[str, Sequence[str], None] = "b3a1f7c9d201"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False,
                  comment="create/update/delete/restore/login/logout/permission_change"),
        sa.Column("resource_type", sa.String(length=64), nullable=False,
                  comment="service/workflow/model/..."),
        sa.Column("resource_id", sa.String(length=255), nullable=True,
                  comment="gateway PK 또는 surro id"),
        sa.Column("actor_member_id", sa.String(length=100), nullable=False,
                  comment="액션 수행 사용자"),
        sa.Column("target_member_id", sa.String(length=100), nullable=True,
                  comment="대상 사용자(권한 변경 등)"),
        sa.Column("metadata", sa.JSON(), nullable=True,
                  comment="액션 부가 정보(JSON)"),
        sa.Column("request_id", sa.String(length=64), nullable=True,
                  comment="X-Request-ID와 연결"),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False, comment="기록 시간"),
        sa.PrimaryKeyConstraint("id"),
        comment="관리자 대시보드 활동 / 감사 로그",
    )
    op.create_index(op.f("ix_audit_logs_id"), "audit_logs", ["id"], unique=False)
    op.create_index("idx_audit_created_at", "audit_logs", ["created_at"], unique=False)
    op.create_index("idx_audit_resource", "audit_logs", ["resource_type", "created_at"], unique=False)
    op.create_index("idx_audit_actor", "audit_logs", ["actor_member_id", "created_at"], unique=False)
    op.create_index("idx_audit_request_id", "audit_logs", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_audit_request_id", table_name="audit_logs")
    op.drop_index("idx_audit_actor", table_name="audit_logs")
    op.drop_index("idx_audit_resource", table_name="audit_logs")
    op.drop_index("idx_audit_created_at", table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_id"), table_name="audit_logs")
    op.drop_table("audit_logs")
