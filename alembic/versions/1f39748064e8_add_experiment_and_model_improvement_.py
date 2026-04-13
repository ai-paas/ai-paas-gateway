"""Add experiment and model_improvement tables

Revision ID: 1f39748064e8
Revises: 1ff2d78b663d
Create Date: 2026-04-08 20:02:16.721214

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '1f39748064e8'
down_revision: Union[str, None] = '1ff2d78b663d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # experiments 테이블
    op.create_table('experiments',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='Inno DB 내부 ID'),
    sa.Column('surro_experiment_id', sa.Integer(), nullable=False, comment='외부 API 실험 ID'),
    sa.Column('created_by', sa.String(length=50), nullable=False, comment='생성자 member_id'),
    sa.Column('name', sa.String(length=255), nullable=True, comment='실험 이름 (캐시용)'),
    sa.Column('description', sa.Text(), nullable=True, comment='실험 설명 (캐시용)'),
    sa.Column('model_id', sa.Integer(), nullable=True, comment='관련 모델 ID (참조용)'),
    sa.Column('dataset_id', sa.Integer(), nullable=True, comment='관련 데이터셋 ID (참조용)'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='생성 시간'),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='수정 시간'),
    sa.Column('updated_by', sa.String(length=50), nullable=True, comment='수정자 member_id'),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='삭제 시간'),
    sa.Column('deleted_by', sa.String(length=50), nullable=True, comment='삭제자 member_id'),
    sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true'), comment='활성화 상태'),
    sa.PrimaryKeyConstraint('id'),
    comment='사용자별 학습 실험 매핑 테이블'
    )
    op.create_index('idx_experiments_member_active', 'experiments', ['created_by', 'is_active', 'deleted_at'], unique=False)
    op.create_index('idx_experiments_surro_member', 'experiments', ['surro_experiment_id', 'created_by'], unique=False)
    op.create_index('idx_experiments_unique_mapping', 'experiments', ['surro_experiment_id', 'created_by'], unique=True, postgresql_where=sa.text('deleted_at IS NULL'))
    op.create_index(op.f('ix_experiments_created_by'), 'experiments', ['created_by'], unique=False)
    op.create_index(op.f('ix_experiments_id'), 'experiments', ['id'], unique=False)
    op.create_index(op.f('ix_experiments_surro_experiment_id'), 'experiments', ['surro_experiment_id'], unique=False)

    # model_improvements 테이블
    op.create_table('model_improvements',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False, comment='Inno DB 내부 ID'),
    sa.Column('task_id', sa.String(length=255), nullable=False, comment='외부 API task UUID'),
    sa.Column('source_model_id', sa.Integer(), nullable=False, comment='소스 모델 ID'),
    sa.Column('task_type', sa.String(length=100), nullable=True, comment='최적화 타입 (tensorrt, openvino 등)'),
    sa.Column('created_by', sa.String(length=50), nullable=False, comment='생성자 member_id'),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='생성 시간'),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False, comment='수정 시간'),
    sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True, comment='삭제 시간'),
    sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true'), comment='활성화 상태'),
    sa.PrimaryKeyConstraint('id'),
    comment='사용자별 모델 최적화/경량화 task 매핑 테이블'
    )
    op.create_index('idx_mi_member_active', 'model_improvements', ['created_by', 'is_active'], unique=False)
    op.create_index('idx_mi_task_id', 'model_improvements', ['task_id'], unique=True)
    op.create_index(op.f('ix_model_improvements_created_by'), 'model_improvements', ['created_by'], unique=False)
    op.create_index(op.f('ix_model_improvements_id'), 'model_improvements', ['id'], unique=False)
    op.create_index(op.f('ix_model_improvements_task_id'), 'model_improvements', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_model_improvements_task_id'), table_name='model_improvements')
    op.drop_index(op.f('ix_model_improvements_id'), table_name='model_improvements')
    op.drop_index(op.f('ix_model_improvements_created_by'), table_name='model_improvements')
    op.drop_index('idx_mi_task_id', table_name='model_improvements')
    op.drop_index('idx_mi_member_active', table_name='model_improvements')
    op.drop_table('model_improvements')

    op.drop_index(op.f('ix_experiments_surro_experiment_id'), table_name='experiments')
    op.drop_index(op.f('ix_experiments_id'), table_name='experiments')
    op.drop_index(op.f('ix_experiments_created_by'), table_name='experiments')
    op.drop_index('idx_experiments_unique_mapping', table_name='experiments', postgresql_where=sa.text('deleted_at IS NULL'))
    op.drop_index('idx_experiments_surro_member', table_name='experiments')
    op.drop_index('idx_experiments_member_active', table_name='experiments')
    op.drop_table('experiments')
