"""add shift_suggestion_actions table

Revision ID: g8c02d3b5e16
Revises: f7b91c2a4d05
Create Date: 2026-11-26 14:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g8c02d3b5e16'
down_revision: Union[str, Sequence[str], None] = 'f7b91c2a4d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if 'shift_suggestion_actions' not in tables:
        op.create_table(
            'shift_suggestion_actions',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('facility_id', sa.Uuid(), nullable=False),
            sa.Column('plan_id', sa.Integer(), nullable=False),
            sa.Column('snapshot_id', sa.Integer(), nullable=True),
            sa.Column('suggestion_id', sa.String(length=64), nullable=False),
            sa.Column('suggestion_type', sa.String(length=64), nullable=False),
            sa.Column('target_date', sa.String(length=16), nullable=True),
            sa.Column('action', sa.String(length=16), nullable=False),
            sa.Column('reason_code', sa.String(length=64), nullable=True),
            sa.Column('reason_note', sa.String(length=500), nullable=True),
            sa.Column('notified_staff_ids', sa.JSON(), nullable=True),
            sa.Column('actor_user_id', sa.String(length=64), nullable=True),
            sa.Column('actor_name', sa.String(length=100), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['plan_id'], ['shift_plans.id']),
            sa.ForeignKeyConstraint(['snapshot_id'], ['shift_solve_snapshots.id']),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_shift_suggestion_actions_facility_id', 'shift_suggestion_actions', ['facility_id'])
        op.create_index('ix_shift_suggestion_actions_plan_id', 'shift_suggestion_actions', ['plan_id'])
        op.create_index('ix_shift_suggestion_actions_snapshot_id', 'shift_suggestion_actions', ['snapshot_id'])
        op.create_index('ix_shift_suggestion_actions_suggestion_id', 'shift_suggestion_actions', ['suggestion_id'])
        op.create_index('ix_shift_suggestion_actions_suggestion_type', 'shift_suggestion_actions', ['suggestion_type'])
        op.create_index('ix_shift_suggestion_actions_target_date', 'shift_suggestion_actions', ['target_date'])
        op.create_index('ix_shift_suggestion_actions_action', 'shift_suggestion_actions', ['action'])
        op.create_index('ix_shift_suggestion_actions_actor_user_id', 'shift_suggestion_actions', ['actor_user_id'])
        op.create_index('ix_shift_suggestion_actions_created_at', 'shift_suggestion_actions', ['created_at'])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if 'shift_suggestion_actions' in tables:
        op.drop_table('shift_suggestion_actions')
