"""initial schema baseline

Revision ID: 3dadc5ad96b9
Revises:
Create Date: 2026-11-10 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "3dadc5ad96b9"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_POST_BASELINE_TABLES = frozenset(
    {
        "punch_children",
        "punch_logs",
        "nap_check_records",
        "nap_classroom_environments",
    }
)


def upgrade() -> None:
    """Create initial base tables from SQLModel metadata (idempotent)."""
    import models  # noqa: F401
    from sqlmodel import SQLModel

    bind = op.get_bind()
    tables = [
        table
        for table_name, table in SQLModel.metadata.tables.items()
        if table_name not in _POST_BASELINE_TABLES
    ]
    SQLModel.metadata.create_all(bind, tables=tables, checkfirst=True)


def downgrade() -> None:
    """Drop initial base tables."""
    import models  # noqa: F401
    from sqlmodel import SQLModel

    bind = op.get_bind()
    tables = [
        table
        for table_name, table in SQLModel.metadata.tables.items()
        if table_name not in _POST_BASELINE_TABLES
    ]
    SQLModel.metadata.drop_all(bind, tables=tables, checkfirst=True)
