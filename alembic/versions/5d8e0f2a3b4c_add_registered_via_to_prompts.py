"""Add registered_via to prompts.

프롬프트 목록·상세 조회는 MLOps 에만 있는 프롬프트를 admin(없으면 요청자) 소유로 자동 등록한다.
생성 요청이 MLOps 생성과 DB 저장 사이에 있을 때 이 자동 등록이 먼저 INSERT 하면, 생성 경로가
그 행을 그대로 돌려줘 만든 사람이 작성자로 남지 않는다. 자동 등록 행에 'auto' 를 남겨 두면
생성 요청이 그 행을 골라 넘겨받을 수 있다.

기존 행은 NULL(알 수 없음)로 둔다. 예전에 자동 등록된 행과 사람이 만든 행을 구분할 근거가 없다.

Revision ID: 5d8e0f2a3b4c
Revises: 4c7d9e1f2a3b
Create Date: 2026-10-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "5d8e0f2a3b4c"
down_revision: Union[str, Sequence[str], None] = "4c7d9e1f2a3b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prompts",
        sa.Column(
            "registered_via",
            sa.String(length=20),
            nullable=True,
            comment="'auto' = 조회 경로의 자동 등록이 만든 행. NULL = 생성 API 또는 알 수 없음",
        ),
    )


def downgrade() -> None:
    op.drop_column("prompts", "registered_via")
