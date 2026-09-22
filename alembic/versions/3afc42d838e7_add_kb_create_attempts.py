"""Add knowledge_base_create_attempts table.

고아 KB 대응. KB 생성 요청 직전에 시도 레코드를 남겨, 타임아웃 등으로 매핑이 저장되지
못한 건을 나중에 업스트림 목록과 대조해 복구하거나 정리할 수 있게 한다.

autogenerate 는 이 테이블 외에 기존 스키마 드리프트(timestamp 타입 변경, 누락된
FK/인덱스, 컬럼 코멘트, 미마이그레이션 상태인 any_cloud_* 테이블)를 함께 뽑아냈다.
이 마이그레이션의 범위가 아니므로 전부 제거하고 신규 테이블만 남겼다.

Revision ID: 3afc42d838e7
Revises: e60718293a4b
Create Date: 2026-09-21 15:06:13.045497

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "3afc42d838e7"
down_revision: Union[str, Sequence[str], None] = "e60718293a4b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_base_create_attempts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("member_id", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("request_id", sa.String(length=255), nullable=False),
        sa.Column(
            "upstream_snapshot",
            sa.JSON(),
            nullable=True,
            comment="POST 직전 업스트림 KB id 집합",
        ),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("failure_kind", sa.String(length=64), nullable=True),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_surro_id", sa.Integer(), nullable=True),
        sa.Column("recovered_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["member_id"], ["members.member_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # 살아 있는 시도 조회(is_protected, 자동 정리)
    op.create_index(
        "idx_kb_attempts_live",
        "knowledge_base_create_attempts",
        ["state", "started_at"],
        unique=False,
    )
    # 조건 6 — 같은 이름·파일로 성공한 재시도 검출
    op.create_index(
        "idx_kb_attempts_dedup",
        "knowledge_base_create_attempts",
        ["member_id", "name", "filename", "state"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_base_create_attempts_id"),
        "knowledge_base_create_attempts",
        ["id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_base_create_attempts_state"),
        "knowledge_base_create_attempts",
        ["state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_knowledge_base_create_attempts_state"),
        table_name="knowledge_base_create_attempts",
    )
    op.drop_index(
        op.f("ix_knowledge_base_create_attempts_id"),
        table_name="knowledge_base_create_attempts",
    )
    op.drop_index("idx_kb_attempts_dedup", table_name="knowledge_base_create_attempts")
    op.drop_index("idx_kb_attempts_live", table_name="knowledge_base_create_attempts")
    op.drop_table("knowledge_base_create_attempts")
