"""add planned_check_in_time to attendance_records

Revision ID: b7d21c4e90a1
Revises: 3dadc5ad96b9
Create Date: 2026-11-10 13:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d21c4e90a1'
down_revision: Union[str, Sequence[str], None] = '3dadc5ad96b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.add_column(sa.Column('planned_check_in_time', sa.VARCHAR(length=5), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('attendance_records', schema=None) as batch_op:
        batch_op.drop_column('planned_check_in_time')

