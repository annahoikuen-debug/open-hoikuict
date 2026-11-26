"""Domain models extracted from models/core.py."""

from datetime import date, datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import JSON, UniqueConstraint
from sqlmodel import Column, Field, Relationship, SQLModel

from security.crypto import EncryptedString, mask_account_number, mask_name_kana
from time_utils import utc_now

from models.core import CareTimeCategory

if TYPE_CHECKING:
    from models.core import AttendanceRecord, Child, Family, User  # noqa: F401


class ExtendedCareChargeStatus(str, Enum):
    draft = "draft"
    confirmed = "confirmed"
    manual_adjusted = "manual_adjusted"
    excluded = "excluded"

    @property
    def label(self) -> str:
        return {
            self.draft: "要確認",
            self.confirmed: "確認済み",
            self.manual_adjusted: "調整済み",
            self.excluded: "対象外",
        }[self]


class DirectDebitStatus(str, Enum):
    not_set = "not_set"
    paper_received = "paper_received"
    active = "active"
    suspended = "suspended"


class ProrationRounding(str, Enum):
    round = "round"
    floor = "floor"
    ceil = "ceil"


class ExemptionType(str, Enum):
    full = "full"
    fixed_discount = "fixed_discount"
    percentage = "percentage"


class ExtendedCareFeeRule(SQLModel, table=True):
    __tablename__ = "extended_care_fee_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    effective_from: date = Field(index=True)
    effective_to: Optional[date] = Field(default=None, index=True)
    start_time: str = Field(default="18:00")
    grace_minutes: int = Field(default=5)
    rounding_minutes: int = Field(default=15)
    unit_price: int = Field(default=100)
    daily_cap_amount: Optional[int] = None
    care_time_category: Optional[CareTimeCategory] = Field(default=None, index=True)
    normal_start_time: Optional[str] = None
    normal_end_time: Optional[str] = None
    morning_enabled: bool = Field(default=False)
    morning_grace_minutes: int = Field(default=0)
    morning_rounding_minutes: int = Field(default=15)
    morning_unit_price: int = Field(default=0)
    evening_enabled: bool = Field(default=True)
    evening_grace_minutes: Optional[int] = None
    evening_rounding_minutes: Optional[int] = None
    evening_unit_price: Optional[int] = None
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    charges: List["ExtendedCareCharge"] = Relationship(back_populates="rule")


class ExtendedCareCalculationSetting(SQLModel, table=True):
    __tablename__ = "extended_care_calculation_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    mode: str = Field(default="legacy", max_length=32)
    category_aware_from: Optional[date] = Field(default=None, index=True)
    updated_at: datetime = Field(default_factory=utc_now)
    updated_by_user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    updated_by_name: Optional[str] = Field(default=None, max_length=100)


class ExtendedCareCharge(SQLModel, table=True):
    __tablename__ = "extended_care_charges"
    __table_args__ = (
        UniqueConstraint("attendance_record_id", name="uq_extended_care_charge_attendance_record"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    attendance_record_id: int = Field(foreign_key="attendance_records.id", index=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    target_date: date = Field(index=True)
    rule_id: int = Field(foreign_key="extended_care_fee_rules.id", index=True)
    charge_start_at: datetime
    actual_check_out_at: Optional[datetime] = None
    extended_minutes: int = Field(default=0)
    billable_units: int = Field(default=0)
    auto_amount: int = Field(default=0)
    adjustment_amount: int = Field(default=0)
    final_amount: int = Field(default=0)
    status: ExtendedCareChargeStatus = Field(default=ExtendedCareChargeStatus.draft, index=True)
    adjustment_reason: Optional[str] = None
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[datetime] = None
    billing_charge_line_id: Optional[int] = Field(
        default=None,
        foreign_key="billing_charge_lines.id",
        index=True,
    )
    transferred_amount: Optional[int] = None
    transferred_at: Optional[datetime] = None
    transferred_by_user_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    transferred_by_name: Optional[str] = Field(default=None, max_length=100)
    certification_id: Optional[int] = Field(default=None, foreign_key="child_care_certifications.id", index=True)
    care_time_category_snapshot: Optional[CareTimeCategory] = Field(default=None, index=True)
    calculation_version: str = Field(default="legacy_v1", max_length=32)
    actual_check_in_at: Optional[datetime] = None
    normal_start_at: Optional[datetime] = None
    normal_end_at: Optional[datetime] = None
    morning_extended_minutes: int = Field(default=0)
    morning_billable_units: int = Field(default=0)
    morning_amount: int = Field(default=0)
    evening_extended_minutes: int = Field(default=0)
    evening_billable_units: int = Field(default=0)
    evening_amount: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    attendance_record: Optional["AttendanceRecord"] = Relationship(back_populates="extended_care_charge")
    child: Optional["Child"] = Relationship()
    rule: Optional[ExtendedCareFeeRule] = Relationship(back_populates="charges")


class ExtendedCareBillingSetting(SQLModel, table=True):
    __tablename__ = "extended_care_billing_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    is_enabled: bool = Field(default=False)
    fee_item_code: str = Field(default="monthly_childcare", max_length=64)
    description_template: str = Field(
        default="延長保育料（{year}年{month}月分）",
        max_length=200,
    )
    transfer_mode: str = Field(default="manual_monthly", max_length=32)
    target_month_rule: str = Field(default="same_month", max_length=32)
    updated_at: datetime = Field(default_factory=utc_now)
    updated_by_user_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    updated_by_name: Optional[str] = Field(default=None, max_length=100)


class ExtendedCareBillingTransferLog(SQLModel, table=True):
    __tablename__ = "extended_care_billing_transfer_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    action: str = Field(max_length=32, index=True)
    target_month: str = Field(max_length=7, index=True)
    billing_cycle_id: int = Field(foreign_key="billing_cycles.id", index=True)
    affected_child_count: int = Field(default=0)
    affected_charge_count: int = Field(default=0)
    total_amount: int = Field(default=0)
    changed_child_ids: list[int] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
    )
    executed_by_user_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    executed_by_name: str = Field(max_length=100)
    executed_at: datetime = Field(default_factory=utc_now, index=True)


class BillingPaymentMethod(str, Enum):
    direct_debit = "口座振替"
    cash = "cash"
    bank_transfer = "bank_transfer"
    exempt = "exempt"


class BillingCycleStatus(str, Enum):
    draft = "draft"
    generated = "generated"
    confirmed = "confirmed"
    exported = "exported"
    result_imported = "result_imported"
    closed = "closed"


class BillingClaimStatus(str, Enum):
    draft = "draft"
    confirmed = "confirmed"
    exported = "exported"
    paid = "paid"
    failed = "failed"
    exempted = "exempted"
    canceled = "canceled"


class BillingChargeSourceType(str, Enum):
    extension_auto = "extension_auto"
    meal_auto = "meal_auto"
    manual = "manual"
    adjustment = "adjustment"
    carryover = "carryover"


class MealFeeCalculationType(str, Enum):
    monthly_fixed = "monthly_fixed"
    attendance_count = "attendance_count"
    manual = "manual"


class MealFeeCountSource(str, Enum):
    attendance_check_in = "attendance_check_in"
    daily_contact_present = "daily_contact_present"
    attendance_verification_present = "attendance_verification_present"
    verification_then_check_in = "verification_then_check_in"
    manual = "manual"


class MealFeeProrationPolicy(str, Enum):
    none = "none"
    daily_by_enrolled_days = "daily_by_enrolled_days"
    manual_adjustment = "manual_adjustment"


class ZenginExportStatus(str, Enum):
    created = "created"
    submitted = "submitted"
    result_imported = "result_imported"
    superseded = "superseded"
    canceled = "canceled"


class BillingSetting(SQLModel, table=True):
    __tablename__ = "billing_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    facility_name: str
    collector_code: str
    collector_name_kana: str
    customer_number_facility_code: str = Field(default="000", max_length=3)
    withdrawal_bank_code: str
    withdrawal_bank_name_kana: Optional[str] = None
    withdrawal_branch_code: str
    withdrawal_branch_name_kana: Optional[str] = None
    collector_account_type: str = Field(default="1", max_length=1)
    collector_account_type_allowed_values: list[str] = Field(
        default_factory=lambda: ["1", "2"],
        sa_column=Column(JSON),
    )
    collector_account_number: str = Field(sa_column=Column(EncryptedString(128), nullable=False))
    code_type: str = Field(default="0", max_length=1)
    file_encoding: str = Field(default="cp932")
    line_separator: str = Field(default="CRLF")
    content_hash_algorithm: str = Field(default="sha256")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def collector_account_number_masked(self) -> str:
        """回収元口座番号のマスク表示（下4桁以外を * 表示）"""
        return mask_account_number(self.collector_account_number)


class FamilyBillingProfile(SQLModel, table=True):
    __tablename__ = "family_billing_profiles"
    __table_args__ = (
        UniqueConstraint("family_id", name="uq_family_billing_profile_family"),
        UniqueConstraint("customer_number", name="uq_family_billing_profile_customer_number"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    family_id: int = Field(foreign_key="families.id", index=True)
    payment_method: BillingPaymentMethod = Field(default=BillingPaymentMethod.direct_debit)
    direct_debit_status: DirectDebitStatus = Field(default=DirectDebitStatus.not_set)
    bank_code: Optional[str] = None
    bank_name_kana: Optional[str] = None
    branch_code: Optional[str] = None
    branch_name_kana: Optional[str] = None
    account_type: Optional[str] = None
    account_number: Optional[str] = Field(
        default=None, sa_column=Column(EncryptedString(128), nullable=True)
    )
    account_holder_kana: Optional[str] = None
    customer_number: str = Field(index=True)
    new_code: str = Field(default="0", max_length=1)
    new_code_consumed_by_export_id: Optional[int] = Field(
        default=None,
        foreign_key="zengin_exports.id",
        index=True,
    )
    mandate_received_on: Optional[date] = None
    note: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def account_number_masked(self) -> str:
        """保護者口座番号のマスク表示（下4桁以外を * 表示）"""
        return mask_account_number(self.account_number)

    @property
    def account_holder_kana_masked(self) -> str:
        """口座名義人カナのマスク表示（先頭・末尾以外を * 表示）"""
        return mask_name_kana(self.account_holder_kana)


class FeeItem(SQLModel, table=True):
    __tablename__ = "fee_items"
    __table_args__ = (UniqueConstraint("code", name="uq_fee_item_code"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(index=True)
    name: str
    category: str
    charge_unit: str
    default_amount: Optional[int] = None
    taxable_type: str = Field(default="non_taxable")
    is_active: bool = Field(default=True, index=True)
    display_order: int = Field(default=100, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BillingExemption(SQLModel, table=True):
    __tablename__ = "billing_exemptions"

    id: Optional[int] = Field(default=None, primary_key=True)
    child_id: int = Field(foreign_key="children.id", index=True)
    fee_item_id: Optional[int] = Field(default=None, foreign_key="fee_items.id", index=True)
    name: str = Field(default="減免措置")
    exemption_type: ExemptionType = Field(default=ExemptionType.full)
    discount_amount: int = Field(default=0)
    discount_rate: int = Field(default=100)
    valid_from: date
    valid_to: Optional[date] = None
    reason: Optional[str] = None
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ExtensionFeeRule(SQLModel, table=True):
    __tablename__ = "extension_fee_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    valid_from: date
    valid_to: Optional[date] = None
    base_end_time: str = Field(default="18:00")
    grace_minutes: int = Field(default=0)
    unit_minutes: int = Field(default=30)
    amount_per_unit: int
    rounding_mode: str = Field(default="ceil")
    max_daily_amount: Optional[int] = None
    max_monthly_amount: Optional[int] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class MealFeeRule(SQLModel, table=True):
    __tablename__ = "meal_fee_rules"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    calculation_type: MealFeeCalculationType = Field(default=MealFeeCalculationType.monthly_fixed)
    monthly_amount: Optional[int] = None
    unit_amount: Optional[int] = None
    count_source: Optional[MealFeeCountSource] = Field(default=MealFeeCountSource.verification_then_check_in)
    proration_policy: MealFeeProrationPolicy = Field(default=MealFeeProrationPolicy.none)
    proration_rounding: ProrationRounding = Field(default=ProrationRounding.round)
    valid_from: date
    valid_to: Optional[date] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BillingCycle(SQLModel, table=True):
    __tablename__ = "billing_cycles"
    __table_args__ = (UniqueConstraint("year_month", name="uq_billing_cycle_year_month"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    year_month: str = Field(index=True)
    period_start: date
    period_end: date
    withdrawal_date: date
    due_date: Optional[date] = None
    status: BillingCycleStatus = Field(default=BillingCycleStatus.draft, index=True)
    generated_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None
    confirmed_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BillingClaim(SQLModel, table=True):
    __tablename__ = "billing_claims"
    __table_args__ = (UniqueConstraint("billing_cycle_id", "family_id", name="uq_billing_claim_cycle_family"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    billing_cycle_id: int = Field(foreign_key="billing_cycles.id", index=True)
    family_id: int = Field(foreign_key="families.id", index=True)
    payment_method: BillingPaymentMethod
    total_amount: int = Field(default=0)
    status: BillingClaimStatus = Field(default=BillingClaimStatus.draft, index=True)
    zengin_export_id: Optional[int] = Field(default=None, foreign_key="zengin_exports.id", index=True)
    exported_at: Optional[datetime] = None
    result_code: Optional[str] = None
    paid_at: Optional[datetime] = None
    failed_reason: Optional[str] = None
    carried_over_to_claim_id: Optional[int] = Field(default=None, foreign_key="billing_claims.id")
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class BillingChargeLine(SQLModel, table=True):
    __tablename__ = "billing_charge_lines"

    id: Optional[int] = Field(default=None, primary_key=True)
    billing_claim_id: int = Field(foreign_key="billing_claims.id", index=True)
    fee_item_id: int = Field(foreign_key="fee_items.id", index=True)
    child_id: Optional[int] = Field(default=None, foreign_key="children.id", index=True)
    source_type: BillingChargeSourceType
    source_date: Optional[date] = None
    source_claim_id: Optional[int] = Field(default=None, foreign_key="billing_claims.id")
    source_reference: Optional[str] = Field(default=None, max_length=120, unique=True, index=True)
    description: str
    quantity: int = Field(default=1)
    unit_label: Optional[str] = None
    unit_price: int = Field(default=0)
    amount: int = Field(default=0)
    is_locked: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ZenginExport(SQLModel, table=True):
    __tablename__ = "zengin_exports"

    id: Optional[int] = Field(default=None, primary_key=True)
    billing_cycle_id: int = Field(foreign_key="billing_cycles.id", index=True)
    withdrawal_date: date
    file_name: str
    total_count: int = Field(default=0)
    total_amount: int = Field(default=0)
    status: ZenginExportStatus = Field(default=ZenginExportStatus.created, index=True)
    superseded_by_export_id: Optional[int] = Field(default=None, foreign_key="zengin_exports.id")
    reissue_reason: Optional[str] = None
    canceled_reason: Optional[str] = None
    canceled_by: Optional[str] = None
    canceled_at: Optional[datetime] = None
    reopen_confirm_requested_by: Optional[str] = None
    reopen_confirm_requested_at: Optional[datetime] = None
    reopen_confirm_payload: Optional[dict[str, Any]] = Field(
        default=None,
        description='差額あり（L1）解除の園長確認申請。{"reason_templates": [...], "reason_free": "...", "estimated_amount": int, "estimated_count": int}',
        sa_column=Column(JSON),
    )
    reopen_confirm_by: Optional[str] = None
    reopen_confirm_at: Optional[datetime] = None
    submitted_at: Optional[datetime] = None
    result_imported_at: Optional[datetime] = None
    content_hash: str
    settings_snapshot: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)


class ZenginExportLine(SQLModel, table=True):
    __tablename__ = "zengin_export_lines"
    __table_args__ = (UniqueConstraint("zengin_export_id", "billing_claim_id", name="uq_zengin_line_export_claim"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    zengin_export_id: int = Field(foreign_key="zengin_exports.id", index=True)
    billing_claim_id: int = Field(foreign_key="billing_claims.id", index=True)
    family_id: int = Field(foreign_key="families.id", index=True)
    customer_number: str = Field(index=True)
    amount: int
    bank_snapshot: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    result_code: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class FamilyBillingProfileChangeLog(SQLModel, table=True):
    __tablename__ = "family_billing_profile_change_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    family_id: int = Field(foreign_key="families.id", index=True)
    child_id: Optional[int] = Field(default=None, foreign_key="children.id", index=True)
    billing_cycle_id: Optional[int] = Field(
        default=None,
        foreign_key="billing_cycles.id",
        index=True,
    )
    changed_fields: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    changed_by_user_id: Optional[uuid.UUID] = Field(
        default=None,
        foreign_key="users.id",
        index=True,
    )
    changed_by_name_snapshot: str = Field(max_length=100)
    changed_at: datetime = Field(default_factory=utc_now, index=True)
