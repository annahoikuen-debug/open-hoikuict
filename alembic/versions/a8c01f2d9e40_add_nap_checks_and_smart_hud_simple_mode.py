"""add nap check tables and facility smart HUD / simple mode columns

Revision ID: a8c01f2d9e40
Revises: f7b91c2a4d05
Create Date: 2026-11-25 12:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a8c01f2d9e40"
down_revision: Union[str, Sequence[str], None] = "f7b91c2a4d05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    facility_cols = {c["name"] for c in inspector.get_columns("facility_settings")}
    with op.batch_alter_table("facility_settings", schema=None) as batch_op:
        if "attendance_smart_hud_enabled" not in facility_cols:
            batch_op.add_column(
                sa.Column("attendance_smart_hud_enabled", sa.Boolean(), server_default="1", nullable=False)
            )
        if "staff_simple_mode_enabled" not in facility_cols:
            batch_op.add_column(
                sa.Column("staff_simple_mode_enabled", sa.Boolean(), server_default="1", nullable=False)
            )
        if "simple_mode_custom_tiles" not in facility_cols:
            batch_op.add_column(
                sa.Column("simple_mode_custom_tiles", sa.String(), nullable=True)
            )
        if "nap_check_smart_enabled" not in facility_cols:
            batch_op.add_column(
                sa.Column("nap_check_smart_enabled", sa.Boolean(), server_default="1", nullable=False)
            )
        if "nap_check_interval_minutes" not in facility_cols:
            batch_op.add_column(
                sa.Column("nap_check_interval_minutes", sa.Integer(), server_default="5", nullable=False)
            )

    if not inspector.has_table("nap_check_records"):
        op.create_table(
            "nap_check_records",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("child_id", sa.Integer(), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column("slots", sa.JSON(), nullable=True),
            sa.Column("daily_memo", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("updated_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["child_id"], ["children.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_nap_check_records_child_id", "nap_check_records", ["child_id"], unique=False)
        op.create_index("ix_nap_check_records_target_date", "nap_check_records", ["target_date"], unique=False)

    if not inspector.has_table("nap_classroom_environments"):
        op.create_table(
            "nap_classroom_environments",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("classroom_id", sa.Integer(), nullable=False),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column("room_temperature", sa.Float(), nullable=True),
            sa.Column("humidity", sa.Float(), nullable=True),
            sa.Column("weather", sa.String(), nullable=False),
            sa.Column("notes", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("updated_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["classroom_id"], ["classrooms.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(
            "ix_nap_classroom_environments_classroom_id",
            "nap_classroom_environments",
            ["classroom_id"],
            unique=False,
        )
        op.create_index(
            "ix_nap_classroom_environments_target_date",
            "nap_classroom_environments",
            ["target_date"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("nap_classroom_environments"):
        op.drop_index("ix_nap_classroom_environments_target_date", table_name="nap_classroom_environments")
        op.drop_index("ix_nap_classroom_environments_classroom_id", table_name="nap_classroom_environments")
        op.drop_table("nap_classroom_environments")

    if inspector.has_table("nap_check_records"):
        op.drop_index("ix_nap_check_records_target_date", table_name="nap_check_records")
        op.drop_index("ix_nap_check_records_child_id", table_name="nap_check_records")
        op.drop_table("nap_check_records")

    facility_cols = {c["name"] for c in inspector.get_columns("facility_settings")}
    with op.batch_alter_table("facility_settings", schema=None) as batch_op:
        for col_name in (
            "nap_check_interval_minutes",
            "nap_check_smart_enabled",
            "simple_mode_custom_tiles",
            "staff_simple_mode_enabled",
            "attendance_smart_hud_enabled",
        ):
            if col_name in facility_cols:
                batch_op.drop_column(col_name)
