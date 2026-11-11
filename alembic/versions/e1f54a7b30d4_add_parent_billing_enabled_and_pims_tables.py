"""add parent_billing_portal_enabled and pims tables

Revision ID: e1f54a7b30d4
Revises: d9e43f6a20c3
Create Date: 2026-11-11 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e1f54a7b30d4'
down_revision: Union[str, Sequence[str], None] = 'd9e43f6a20c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. facility_settings に parent_billing_portal_enabled を追加
    with op.batch_alter_table('facility_settings', schema=None) as batch_op:
        batch_op.add_column(sa.Column('parent_billing_portal_enabled', sa.Boolean(), server_default='0', nullable=False))

    # 2. punch_children テーブル作成
    op.create_table(
        'punch_children',
        sa.Column('child_id', sa.VARCHAR(length=64), primary_key=True, nullable=False),
        sa.Column('name', sa.VARCHAR(length=100), nullable=False),
        sa.Column('kana', sa.VARCHAR(length=100), nullable=True),
        sa.Column('birth_date', sa.Date(), nullable=True),
        sa.Column('class_name', sa.VARCHAR(length=50), server_default='未設定', nullable=False),
        sa.Column('family_id', sa.VARCHAR(length=64), nullable=True),
        sa.Column('parent_email', sa.VARCHAR(length=255), nullable=True),
        sa.Column('sort_order', sa.Integer(), server_default='0', nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='1', nullable=False),
    )
    with op.batch_alter_table('punch_children', schema=None) as batch_op:
        batch_op.create_index('ix_punch_children_family_id', ['family_id'])

    # 3. punch_logs テーブル作成
    op.create_table(
        'punch_logs',
        sa.Column('log_id', sa.VARCHAR(length=64), primary_key=True, nullable=False),
        sa.Column('child_id', sa.VARCHAR(length=64), sa.ForeignKey('punch_children.child_id'), nullable=False),
        sa.Column('punched_at', sa.DateTime(), nullable=False),
        sa.Column('punch_type', sa.VARCHAR(length=20), nullable=False),
        sa.Column('absence_reason', sa.VARCHAR(length=20), nullable=True),
        sa.Column('is_auto_filled', sa.Boolean(), server_default='0', nullable=False),
    )
    with op.batch_alter_table('punch_logs', schema=None) as batch_op:
        batch_op.create_index('ix_punch_logs_child_id', ['child_id'])
        batch_op.create_index('ix_punch_logs_punched_at', ['punched_at'])


def downgrade() -> None:
    op.drop_table('punch_logs')
    op.drop_table('punch_children')
    with op.batch_alter_table('facility_settings', schema=None) as batch_op:
        batch_op.drop_column('parent_billing_portal_enabled')

