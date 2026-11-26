"""merge multiple alembic heads

Revision ID: 16e0e0b183d7
Revises: a1b2c3d4e5f6, a8c01f2d9e40, g8c02d3b5e16
Create Date: 2026-11-26 15:58:45.056459

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '16e0e0b183d7'
down_revision: Union[str, Sequence[str], None] = ('a1b2c3d4e5f6', 'a8c01f2d9e40', 'g8c02d3b5e16')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
