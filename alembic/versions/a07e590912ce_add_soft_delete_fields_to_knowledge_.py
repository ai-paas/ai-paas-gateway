"""Add soft delete fields to knowledge_bases table

Revision ID: a07e590912ce
Revises: 1f39748064e8
Create Date: 2026-04-13 15:50:37.062028

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a07e590912ce'
down_revision: Union[str, None] = '1f39748064e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # knowledge_bases 테이블에 소프트 삭제 관련 컬럼 추가
    op.add_column('knowledge_bases', sa.Column('updated_by', sa.String(length=100), nullable=True, comment='수정자 member_id'))
    op.add_column('knowledge_bases', sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='삭제 시간'))
    op.add_column('knowledge_bases', sa.Column('deleted_by', sa.String(length=100), nullable=True, comment='삭제자 member_id'))
    op.add_column('knowledge_bases', sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False, comment='활성화 상태'))


def downgrade() -> None:
    op.drop_column('knowledge_bases', 'is_active')
    op.drop_column('knowledge_bases', 'deleted_by')
    op.drop_column('knowledge_bases', 'deleted_at')
    op.drop_column('knowledge_bases', 'updated_by')
