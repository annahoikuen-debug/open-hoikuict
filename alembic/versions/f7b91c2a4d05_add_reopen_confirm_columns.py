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
    with op.batch_alter_table('zengin_exports', schema=None) as batch_op:
        batch_op.add_column(sa.Column('reopen_confirm_requested_by', sa.VARCHAR(length=255), nullable=True))
        batch_op.add_column(sa.Column('reopen_confirm_requested_at', sa.DateTime(), nullable=True))
        # 差額あり（L1）解除の園長確認申請。{"reason_templates": [...], "reason_free": "...",
        # "estimated_amount": int, "estimated_count": int}
        batch_op.add_column(sa.Column('reopen_confirm_payload', sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column('reopen_confirm_by', sa.VARCHAR(length=255), nullable=True))
        batch_op.add_column(sa.Column('reopen_confirm_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('zengin_exports', schema=None) as batch_op:
        batch_op.drop_column('reopen_confirm_at')
        batch_op.drop_column('reopen_confirm_by')
        batch_op.drop_column('reopen_confirm_payload')
        batch_op.drop_column('reopen_confirm_requested_at')
        batch_op.drop_column('reopen_confirm_requested_by')
