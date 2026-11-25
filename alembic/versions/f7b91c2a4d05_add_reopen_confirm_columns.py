"""add reopen confirm columns to zengin_exports

Revision ID: f7b91c2a4d05
Revises: e1f54a7b30d4
Create Date: 2026-11-24 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f7b91c2a4d05'
down_revision: Union[str, Sequence[str], None] = 'e1f54a7b30d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("zengin_exports")}
    with op.batch_alter_table('zengin_exports', schema=None) as batch_op:
        if 'reopen_confirm_requested_by' not in cols:
            batch_op.add_column(sa.Column('reopen_confirm_requested_by', sa.VARCHAR(length=255), nullable=True))
        if 'reopen_confirm_requested_at' not in cols:
            batch_op.add_column(sa.Column('reopen_confirm_requested_at', sa.DateTime(), nullable=True))
        # 差額あり（L1）解除の園長確認申請。{"reason_templates": [...], "reason_free": "...",
        # "estimated_amount": int, "estimated_count": int}
        if 'reopen_confirm_payload' not in cols:
            batch_op.add_column(sa.Column('reopen_confirm_payload', sa.JSON(), nullable=True))
        if 'reopen_confirm_by' not in cols:
            batch_op.add_column(sa.Column('reopen_confirm_by', sa.VARCHAR(length=255), nullable=True))
        if 'reopen_confirm_at' not in cols:
            batch_op.add_column(sa.Column('reopen_confirm_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("zengin_exports")}
    with op.batch_alter_table('zengin_exports', schema=None) as batch_op:
        for col_name in (
            'reopen_confirm_at',
            'reopen_confirm_by',
            'reopen_confirm_payload',
            'reopen_confirm_requested_at',
            'reopen_confirm_requested_by',
        ):
            if col_name in cols:
                batch_op.drop_column(col_name)
