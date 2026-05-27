"""Add description column to datasets for search

Revision ID: 73153bc5a965
Revises: a07e590912ce
Create Date: 2026-04-23 16:55:52.436955

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '73153bc5a965'
down_revision: Union[str, None] = 'a07e590912ce'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'datasets',
        sa.Column(
            'description',
            sa.Text(),
            nullable=True,
            comment='데이터셋 설명 (캐시용, 검색 대상)',
        ),
    )


def downgrade() -> None:
    op.drop_column('datasets', 'description')
