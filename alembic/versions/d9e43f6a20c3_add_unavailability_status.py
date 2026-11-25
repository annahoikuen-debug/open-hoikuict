"""add status to staff_shift_unavailability

Revision ID: d9e43f6a20c3
Revises: c8d32e5f10b2
Create Date: 2026-11-10 13:36:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd9e43f6a20c3'
down_revision: Union[str, Sequence[str], None] = 'c8d32e5f10b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("staff_shift_unavailability")}
    if "status" not in cols:
        with op.batch_alter_table('staff_shift_unavailability', schema=None) as batch_op:
            batch_op.add_column(sa.Column('status', sa.VARCHAR(length=16), server_default='approved', nullable=False))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("staff_shift_unavailability")}
    if "status" in cols:
        with op.batch_alter_table('staff_shift_unavailability', schema=None) as batch_op:
            batch_op.drop_column('status')

