"""add board qr settings to facility_settings

Revision ID: a1b2c3d4e5f6
Revises: f7b91c2a4d05
Create Date: 2026-11-26 13:55:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f7b91c2a4d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("facility_settings")}
    with op.batch_alter_table('facility_settings', schema=None) as batch_op:
        if 'board_qr_enabled' not in cols:
            batch_op.add_column(sa.Column('board_qr_enabled', sa.Boolean(), nullable=False, server_default=sa.true()))
        if 'board_qr_version' not in cols:
            batch_op.add_column(sa.Column('board_qr_version', sa.Integer(), nullable=False, server_default='1'))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("facility_settings")}
    with op.batch_alter_table('facility_settings', schema=None) as batch_op:
        for col_name in ('board_qr_version', 'board_qr_enabled'):
            if col_name in cols:
                batch_op.drop_column(col_name)
