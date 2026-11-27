"""add composite index on health_check_records for /health overview

Revision ID: i0e24f5a7c38
Revises: h9d13e4c6f27
Create Date: 2026-11-27 16:05:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i0e24f5a7c38"
down_revision: Union[str, Sequence[str], None] = "h9d13e4c6f27"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "health_check_records" not in inspector.get_table_names():
        return
    existing = {idx["name"] for idx in inspector.get_indexes("health_check_records")}
    if "ix_health_check_records_child_checked" not in existing:
        op.create_index(
            "ix_health_check_records_child_checked",
            "health_check_records",
            ["child_id", "checked_at", "updated_at", "id"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "health_check_records" not in inspector.get_table_names():
        return
    existing = {idx["name"] for idx in inspector.get_indexes("health_check_records")}
    if "ix_health_check_records_child_checked" in existing:
        op.drop_index("ix_health_check_records_child_checked", table_name="health_check_records")
