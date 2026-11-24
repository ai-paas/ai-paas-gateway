"""Add registered_via to workflows.

워크플로우 목록 조회는 MLOps 에만 있는 워크플로우를 admin 소유로 자동 등록한다. 생성 요청이
MLOps 생성과 DB 저장 사이에 있을 때 이 자동 등록이 먼저 INSERT 하면, 생성자는 유니크 위반으로
실패하고 자기 워크플로우에 403 을 받는다. 자동 등록 행에 'auto' 를 남겨 두면 생성 요청이 그
행만 골라 소유권을 넘겨받을 수 있다.

기존 행은 NULL(알 수 없음)로 둔다. 예전에 자동 등록된 행과 admin 이 직접 만든 행은 둘 다
created_by=admin 이라 구분할 근거가 없다. 'auto' 로 채우면 admin 의 워크플로우가 이전 대상이 된다.

Revision ID: 4c7d9e1f2a3b
Revises: 3afc42d838e7
Create Date: 2026-10-08 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "4c7d9e1f2a3b"
down_revision: Union[str, Sequence[str], None] = "3afc42d838e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "workflows",
        sa.Column(
            "registered_via",
            sa.String(length=20),
            nullable=True,
            comment="'auto' = 목록 조회의 자동 등록이 만든 행. NULL = 생성 API 또는 알 수 없음",
        ),
    )


def downgrade() -> None:
    op.drop_column("workflows", "registered_via")
