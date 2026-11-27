"""adopt upstream features (meeting lifecycle, extended care bands, contact fields, plan_docs, class_kiosk)

Revision ID: h9d13e4c6f27
Revises: g8c02d3b5e16
Create Date: 2026-11-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h9d13e4c6f27"
down_revision: Union[str, Sequence[str], None] = ("16e0e0b183d7", "g8c02d3b5e16")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _column_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    if not _has_table(inspector, table_name):
        return set()
    return {col["name"] for col in inspector.get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1. MeetingNote lifecycle columns + MeetingNoteAction table
    mn_cols = _column_names(inspector, "meeting_notes")
    if mn_cols:
        if "lifecycle_status" not in mn_cols:
            op.add_column("meeting_notes", sa.Column("lifecycle_status", sa.String(), nullable=False, server_default="active"))
        if "lifecycle_version" not in mn_cols:
            op.add_column("meeting_notes", sa.Column("lifecycle_version", sa.Integer(), nullable=False, server_default="0"))
    if not _has_table(inspector, "meeting_note_actions"):
        op.create_table(
            "meeting_note_actions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("note_id", sa.Integer(), sa.ForeignKey("meeting_notes.id"), nullable=False, index=True),
            sa.Column("action", sa.String(), nullable=False),
            sa.Column("from_status", sa.String(), nullable=False),
            sa.Column("to_status", sa.String(), nullable=False),
            sa.Column("actor_user_id", sa.String(), nullable=True),
            sa.Column("actor_name", sa.String(), nullable=False),
            sa.Column("reason", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )

    # 2. ExtendedCareFeeRule / ExtendedCareCharge band columns
    rule_cols = _column_names(inspector, "extended_care_fee_rules")
    if rule_cols and "fee_bands_json" not in rule_cols:
        op.add_column("extended_care_fee_rules", sa.Column("fee_bands_json", sa.Text(), nullable=True))
    charge_cols = _column_names(inspector, "extended_care_charges")
    if charge_cols and "fee_breakdown_json" not in charge_cols:
        op.add_column("extended_care_charges", sa.Column("fee_breakdown_json", sa.Text(), nullable=True))

    # 3. ParentContactFieldSetting / ParentContactFieldAudit tables
    if not _has_table(inspector, "parent_contact_field_settings"):
        op.create_table(
            "parent_contact_field_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("policy", sa.JSON(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_by_name", sa.String(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
    if not _has_table(inspector, "parent_contact_field_audits"):
        op.create_table(
            "parent_contact_field_audits",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("previous_policy", sa.JSON(), nullable=False),
            sa.Column("policy", sa.JSON(), nullable=False),
            sa.Column("revision", sa.Integer(), nullable=False),
            sa.Column("changed_by_name", sa.String(), nullable=False),
            sa.Column("changed_by_user_id", sa.Uuid(), nullable=False),
            sa.Column("changed_at", sa.DateTime(), nullable=False),
        )

    # 4. PlanDocs weekly/annual sheets, action revision_id, and reflection review tables
    pd_cols = _column_names(inspector, "plan_documents")
    if pd_cols:
        for col_name, col_type in (
            ("weekly_sheet", sa.JSON()),
            ("weekly_sheet_key", sa.String()),
            ("annual_sheet", sa.JSON()),
            ("annual_sheet_key", sa.String()),
        ):
            if col_name not in pd_cols:
                op.add_column("plan_documents", sa.Column(col_name, col_type, nullable=True))
    pda_cols = _column_names(inspector, "plan_document_actions")
    if pda_cols and "revision_id" not in pda_cols:
        op.add_column("plan_document_actions", sa.Column("revision_id", sa.Integer(), nullable=True))

    if not _has_table(inspector, "plan_reflection_drafts"):
        op.create_table(
            "plan_reflection_drafts",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("plan_documents.id"), nullable=False, index=True),
            sa.Column("period", sa.Integer(), nullable=False),
            sa.Column("values", sa.JSON(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(), nullable=False, server_default="draft"),
            sa.Column("updated_by", sa.String(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.UniqueConstraint("document_id", "period", name="uq_reflection_document_period"),
        )
    if not _has_table(inspector, "plan_reflection_reviews"):
        op.create_table(
            "plan_reflection_reviews",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("draft_id", sa.Integer(), sa.ForeignKey("plan_reflection_drafts.id"), nullable=False, index=True),
            sa.Column("document_id", sa.Integer(), sa.ForeignKey("plan_documents.id"), nullable=False, index=True),
            sa.Column("nursery_ref", sa.String(), nullable=False, index=True),
            sa.Column("draft_version", sa.Integer(), nullable=False),
            sa.Column("snapshot", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="pending", index=True),
            sa.Column("requested_by", sa.String(), nullable=False),
            sa.Column("requested_by_name", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("decided_by", sa.String(), nullable=True),
            sa.Column("decided_by_name", sa.String(), nullable=True),
            sa.Column("decision_comment", sa.String(), nullable=True),
            sa.Column("decided_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("draft_id", "draft_version", name="uq_reflection_review_version"),
        )
    if not _has_table(inspector, "plan_reflection_notifications"):
        op.create_table(
            "plan_reflection_notifications",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("review_id", sa.Integer(), sa.ForeignKey("plan_reflection_reviews.id"), nullable=False, index=True),
            sa.Column("recipient_user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
            sa.Column("kind", sa.String(), nullable=False, server_default="review_request"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("read_at", sa.DateTime(), nullable=True),
            sa.Column("resolved_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("review_id", "recipient_user_id", "kind", name="uq_reflection_notification"),
        )

    # 5. Class Kiosk tables
    import class_kiosk.models as ck_models

    for model_cls in (
        ck_models.KioskAccount,
        ck_models.KioskDevice,
        ck_models.KioskEnrollment,
        ck_models.KioskAttempt,
        ck_models.KioskOperation,
        ck_models.KioskAudit,
        ck_models.KioskMessageOwner,
        ck_models.KioskChange,
        ck_models.KioskSubscription,
        ck_models.KioskDelivery,
    ):
        if not _has_table(inspector, model_cls.__tablename__):
            model_cls.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    pass
