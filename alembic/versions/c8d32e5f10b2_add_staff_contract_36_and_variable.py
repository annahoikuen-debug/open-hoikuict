"""add has_36_agreement and variable_working_hours to staff_contracts

Revision ID: c8d32e5f10b2
Revises: b7d21c4e90a1
Create Date: 2026-11-10 13:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d32e5f10b2'
down_revision: Union[str, Sequence[str], None] = 'b7d21c4e90a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('staff_contracts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('has_36_agreement', sa.Boolean(), server_default='1', nullable=False))
        batch_op.add_column(sa.Column('variable_working_hours', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('staff_contracts', schema=None) as batch_op:
        batch_op.drop_column('variable_working_hours')
        batch_op.drop_column('has_36_agreement')

