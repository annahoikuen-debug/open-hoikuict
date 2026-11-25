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
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("staff_contracts")}
    with op.batch_alter_table('staff_contracts', schema=None) as batch_op:
        if "has_36_agreement" not in cols:
            batch_op.add_column(sa.Column('has_36_agreement', sa.Boolean(), server_default='1', nullable=False))
        if "variable_working_hours" not in cols:
            batch_op.add_column(sa.Column('variable_working_hours', sa.Boolean(), server_default='0', nullable=False))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("staff_contracts")}
    with op.batch_alter_table('staff_contracts', schema=None) as batch_op:
        if "variable_working_hours" in cols:
            batch_op.drop_column('variable_working_hours')
        if "has_36_agreement" in cols:
            batch_op.drop_column('has_36_agreement')

