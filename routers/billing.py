from __future__ import annotations

import calendar
from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from auth import get_current_staff_user, require_admin, require_can_edit
from billing_calculation_service import BillingCalculationError, recalculate_claim_total, validate_charge_amount
from billing_sibling_service import calculate_sibling_discount_for_child
from database import get_session, run_db_async
from models import (
    BillingChargeLine,
    BillingChargeSourceType,
    BillingClaim,
    BillingClaimStatus,
    BillingCycle,
    BillingCycleStatus,
    BillingExemption,
    BillingPaymentMethod,
    BillingSetting,
    Child,
    ChildStatus,
    DirectDebitStatus,
    ExemptionType,
    Family,
    FamilyBillingProfile,
    FamilyBillingProfileChangeLog,
    FeeItem,
    ZenginExport,
    ZenginExportLine,
    ZenginExportStatus,
)
from staff_permissions import (
    can_export_zengin,
    can_manage_billing_accounts,
    require_billing_account_manager,
    require_live_admin,
    require_zengin_exporter,
)
from audit_logger import record_audit_event
from time_utils import utc_now
from zengin_service import (
    ParsedResultRecord,
    ZenginError,
    approve_reopen_and_cancel,
    build_data_record,
    build_end_record,
    build_file_bytes,
    build_header_record,
    build_trailer_record,
    cancel_zengin_export_for_edit,
    combine_reopen_reason,
    create_customer_number,
    create_zengin_export,
    estimate_reopen_delta,
    has_pending_reopen_confirm,
    import_result_file,
    lock_billing_cycle,
    mark_zengin_export_submitted,
    reopenable_export,
    request_reopen_confirm,
    supersede_zengin_export,
    withdraw_reopen_request,
)

router = APIRouter(prefix="/billing", tags=["billing"])
from template_utils import create_templates

templates = create_templates()

TABLE_CHARGE_COLUMNS = [
    {
        "code": "monthly_meal",
        "label": "給食費",
        "description": "給食費（月額）",
        "category": "monthly",
        "category_label": "毎月請求",
        "source_type": BillingChargeSourceType.manual,
        "display_order": 110,
    },
    {
        "code": "monthly_childcare",
        "label": "延長保育料",
        "description": "延長保育料（月額）",
        "category": "monthly",
        "category_label": "毎月請求",
        "source_type": BillingChargeSourceType.manual,
        "display_order": 120,
    },
    {
        "code": "temp_photo",
        "label": "写真代",
        "description": "写真代",
        "category": "temporary",
        "category_label": "単発請求",
        "source_type": BillingChargeSourceType.manual,
        "display_order": 210,
    },
    {
        "code": "temp_material",
        "label": "教材費",
        "description": "教材費",
        "category": "temporary",
        "category_label": "単発請求",
        "source_type": BillingChargeSourceType.manual,
        "display_order": 220,
    },
    {
        "code": "temp_event",
        "label": "行事費",
        "description": "行事費",
        "category": "temporary",
        "category_label": "単発請求",
        "source_type": BillingChargeSourceType.manual,
        "display_order": 230,
    },
    {
        "code": "adjustment",
        "label": "調整額",
        "description": "調整額",
        "category": "adjustment",
        "category_label": "調整",
        "source_type": BillingChargeSourceType.adjustment,
        "display_order": 310,
    },
]

TABLE_CHARGE_GROUPS = [
    {
        "key": "monthly",
        "label": "毎月請求",
        "columns": [column for column in TABLE_CHARGE_COLUMNS if column["category"] == "monthly"],
    },
    {
        "key": "temporary",
        "label": "単発請求",
        "columns": [column for column in TABLE_CHARGE_COLUMNS if column["category"] == "temporary"],
    },
    {
        "key": "adjustment",
        "label": "調整",
        "columns": [column for column in TABLE_CHARGE_COLUMNS if column["category"] == "adjustment"],
    },
]

BILLING_CYCLE_STATUS_LABELS = {
    BillingCycleStatus.draft: "下書き",
    BillingCycleStatus.generated: "請求生成済み",
    BillingCycleStatus.confirmed: "確定済み",
    BillingCycleStatus.exported: "出力済み",
    BillingCycleStatus.result_imported: "結果取込済み",
    BillingCycleStatus.closed: "締め済み",
}

BILLING_CLAIM_STATUS_LABELS = {
    BillingClaimStatus.draft: "下書き",
    BillingClaimStatus.confirmed: "確定済み",
    BillingClaimStatus.exported: "出力済み",
    BillingClaimStatus.paid: "入金済み",
    BillingClaimStatus.failed: "振替失敗",
    BillingClaimStatus.exempted: "請求対象外",
    BillingClaimStatus.canceled: "取消済み",
}

BILLING_PAYMENT_METHOD_LABELS = {
    BillingPaymentMethod.direct_debit: "口座振替",
    BillingPaymentMethod.cash: "現金",
    BillingPaymentMethod.bank_transfer: "銀行振込",
    BillingPaymentMethod.exempt: "免除",
}

DIRECT_DEBIT_STATUS_LABELS = {
    DirectDebitStatus.not_set: "未設定",
    DirectDebitStatus.paper_received: "依頼書回収済",
    DirectDebitStatus.active: "利用中",
    DirectDebitStatus.suspended: "停止中",
}

ZENGIN_EXPORT_STATUS_LABELS = {
    ZenginExportStatus.created: "作成済み",
    ZenginExportStatus.submitted: "銀行提出済み",
    ZenginExportStatus.result_imported: "結果取込済み",
    ZenginExportStatus.superseded: "差し替え済み",
    ZenginExportStatus.canceled: "取消済み",
}


def _dashboard_redirect(**params: str) -> RedirectResponse:
    query = urlencode({key: value for key, value in params.items() if value})
    suffix = f"?{query}" if query else ""
    return RedirectResponse(url=f"/billing/{suffix}", status_code=303)


def _cycle_redirect(cycle_id: int, *, message: str = "", error: str = "") -> RedirectResponse:
    query = urlencode({key: value for key, value in {"message": message, "error": error}.items() if value})
    suffix = f"?{query}" if query else ""
    return RedirectResponse(url=f"/billing/cycles/{cycle_id}/child-charges{suffix}", status_code=303)


def _child_charge_redirect(cycle_id: int, child_id: int, *, message: str = "", error: str = "") -> RedirectResponse:
    query = urlencode({key: value for key, value in {"message": message, "error": error}.items() if value})
    suffix = f"?{query}" if query else ""
    return RedirectResponse(url=f"/billing/cycles/{cycle_id}/child-charges/{child_id}{suffix}", status_code=303)


def _ensure_manual_fee_item(session: Session, *, code: str = "manual_child", name: str = "園児別手動費用") -> FeeItem:
    item = session.exec(select(FeeItem).where(FeeItem.code == code)).first()
    if item is None:
        item = FeeItem(
            code=code,
            name=name,
            category="other",
            charge_unit="child",
            taxable_type="non_taxable",
            display_order=900,
        )
        session.add(item)
        session.flush()
    return item


def _ensure_table_fee_item(session: Session, column: dict) -> FeeItem:
    item = session.exec(select(FeeItem).where(FeeItem.code == column["code"])).first()
    if item is None:
        item = FeeItem(
            code=column["code"],
            name=column["description"],
            category=column["category"],
            charge_unit="child",
            taxable_type="non_taxable",
            display_order=column["display_order"],
        )
        session.add(item)
        session.flush()
    return item


def _ensure_test_billing_setting(session: Session) -> BillingSetting:
    setting = session.exec(select(BillingSetting).order_by(BillingSetting.id)).first()
    if setting is not None:
        return setting
    setting = BillingSetting(
        facility_name="open-hoikuict テスト園",
        collector_code="1234567890",
        collector_name_kana="HOIKU",
        customer_number_facility_code="001",
        withdrawal_bank_code="0001",
        withdrawal_bank_name_kana="BANK",
        withdrawal_branch_code="001",
        withdrawal_branch_name_kana="BRANCH",
        collector_account_type="1",
        collector_account_number="1234567",
    )
    session.add(setting)
    session.flush()
    return setting


def _ensure_test_billing_profile(session: Session, *, child: Child, setting: BillingSetting) -> FamilyBillingProfile:
    if child.family_id is None:
        raise BillingCalculationError("園児に家族が紐づいていません")
    profile = session.exec(
        select(FamilyBillingProfile).where(FamilyBillingProfile.family_id == child.family_id)
    ).first()
    customer_number = create_customer_number(setting.customer_number_facility_code, child.family_id)
    if profile is None:
        profile = FamilyBillingProfile(
            family_id=child.family_id,
            customer_number=customer_number,
        )
    profile.payment_method = BillingPaymentMethod.direct_debit
    profile.direct_debit_status = DirectDebitStatus.active
    profile.bank_code = profile.bank_code or "0005"
    profile.bank_name_kana = profile.bank_name_kana or "BANK"
    profile.branch_code = profile.branch_code or "123"
    profile.branch_name_kana = profile.branch_name_kana or "BRANCH"
    profile.account_type = profile.account_type or "1"
    profile.account_number = profile.account_number or "7654321"
    profile.account_holder_kana = profile.account_holder_kana or "TANAKA TARO"
    profile.new_code = profile.new_code or "1"
    profile.updated_at = utc_now()
    session.add(profile)
    session.flush()
    return profile


def _next_available_year_month(session: Session) -> str:
    existing = {cycle.year_month for cycle in session.exec(select(BillingCycle)).all()}
    year = 2026
    month = 5
    while True:
        value = f"{year:04d}-{month:02d}"
        if value not in existing:
            return value
        month += 1
        if month > 12:
            year += 1
            month = 1


def _month_bounds(year_month: str) -> tuple[date, date, date]:
    year, month = [int(part) for part in year_month.split("-")]
    last_day = calendar.monthrange(year, month)[1]
    withdrawal_month = month + 1
    withdrawal_year = year
    if withdrawal_month > 12:
        withdrawal_year += 1
        withdrawal_month = 1
    withdrawal_day = min(27, calendar.monthrange(withdrawal_year, withdrawal_month)[1])
    return (
        date(year, month, 1),
        date(year, month, last_day),
        date(withdrawal_year, withdrawal_month, withdrawal_day),
    )


def _create_blank_input_cycle(session: Session, *, created_by: str) -> BillingCycle:
    year_month = _next_available_year_month(session)
    period_start, period_end, withdrawal_date = _month_bounds(year_month)
    cycle = BillingCycle(
        year_month=year_month,
        period_start=period_start,
        period_end=period_end,
        withdrawal_date=withdrawal_date,
        status=BillingCycleStatus.confirmed,
        confirmed_at=utc_now(),
        confirmed_by=created_by,
    )
    session.add(cycle)
    session.flush()
    return cycle


def _ensure_claim_for_child(session: Session, *, cycle: BillingCycle, child: Child) -> BillingClaim:
    if child.family_id is None:
        raise HTTPException(status_code=400, detail="園児に家族が紐づいていません")
    claim = session.exec(
        select(BillingClaim)
        .where(BillingClaim.billing_cycle_id == cycle.id)
        .where(BillingClaim.family_id == child.family_id)
    ).first()
    if claim is None:
        profile = session.exec(
            select(FamilyBillingProfile).where(FamilyBillingProfile.family_id == child.family_id)
        ).first()
        payment_method = profile.payment_method if profile else BillingPaymentMethod.direct_debit
        claim = BillingClaim(
            billing_cycle_id=cycle.id,
            family_id=child.family_id,
            payment_method=payment_method,
            total_amount=0,
            status=BillingClaimStatus.confirmed if cycle.status == BillingCycleStatus.confirmed else BillingClaimStatus.draft,
        )
        session.add(claim)
        session.flush()
    return claim


def _add_child_charge(
    session: Session,
    *,
    cycle: BillingCycle,
    child: Child,
    description: str,
    amount: int,
    quantity: int,
    unit_label: str,
    source_date: date | None,
) -> BillingClaim:
    cycle = lock_billing_cycle(session, cycle.id) or cycle
    if cycle.status not in {BillingCycleStatus.draft, BillingCycleStatus.generated, BillingCycleStatus.confirmed}:
        raise BillingCalculationError("Zengin出力後の請求月には明細を追加できません")
    if not description.strip():
        raise BillingCalculationError("内容を入力してください")
    validate_charge_amount(BillingChargeSourceType.manual, amount, allow_zero_note=True)

    fee_item = _ensure_manual_fee_item(session)
    claim = _ensure_claim_for_child(session, cycle=cycle, child=child)
    if claim.status in {BillingClaimStatus.exported, BillingClaimStatus.paid}:
        raise BillingCalculationError("出力済みまたは入金済みの請求には明細を追加できません")

    line = BillingChargeLine(
        billing_claim_id=claim.id,
        fee_item_id=fee_item.id,
        child_id=child.id,
        source_type=BillingChargeSourceType.manual,
        source_date=source_date,
        description=description.strip(),
        quantity=quantity,
        unit_label=unit_label.strip() or "式",
        unit_price=amount,
        amount=amount,
        is_locked=False,
    )
    session.add(line)
    session.flush()
    lines = session.exec(select(BillingChargeLine).where(BillingChargeLine.billing_claim_id == claim.id)).all()
    recalculate_claim_total(claim, lines)
    if cycle.status == BillingCycleStatus.confirmed:
        claim.status = BillingClaimStatus.confirmed
    elif claim.status != BillingClaimStatus.confirmed:
        claim.status = BillingClaimStatus.draft
    claim.updated_at = utc_now()
    session.add(claim)
    return claim


def _parse_optional_date(raw: str | None) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(raw)


def _validate_account_digits(value: str, length: int, label: str) -> str:
    cleaned = value.strip()
    if not cleaned.isdigit() or len(cleaned) != length:
        raise BillingCalculationError(f"{label}は{length}桁の数字で入力してください")
    return cleaned


def _validate_account_number(value: str) -> str:
    cleaned = value.strip()
    if not cleaned.isdigit() or not (1 <= len(cleaned) <= 7):
        raise BillingCalculationError("口座番号は1〜7桁の数字で入力してください")
    return cleaned


def _update_profile_new_code(profile: FamilyBillingProfile, *, previous: dict[str, str | None]) -> None:
    watched_fields = ["bank_code", "branch_code", "account_type", "account_number"]
    if any(previous.get(field) != getattr(profile, field) for field in watched_fields):
        profile.new_code = "2" if profile.direct_debit_status == DirectDebitStatus.active else profile.new_code
        return
    if previous.get("account_holder_kana") != profile.account_holder_kana:
        profile.new_code = "2" if profile.direct_debit_status == DirectDebitStatus.active else profile.new_code


def _parse_table_amount(raw_value: str, *, child: Child, column: dict) -> int:
    cleaned = raw_value.strip().replace(",", "")
    if cleaned == "":
        return 0
    try:
        amount = int(cleaned)
    except ValueError as exc:
        raise BillingCalculationError(f"{child.full_name} の {column['label']} は整数で入力してください") from exc
    if amount < 0 and column["category"] != "adjustment":
        raise BillingCalculationError(f"{child.full_name} の {column['label']} は0円以上で入力してください")
    validate_charge_amount(column["source_type"], amount, allow_zero_note=True)
    return amount


def _upsert_table_charge(
    session: Session,
    *,
    cycle: BillingCycle,
    child: Child,
    column: dict,
    amount: int,
) -> BillingClaim | None:
    if child.family_id is None:
        raise BillingCalculationError(f"{child.full_name} に家族が紐づいていません")

    fee_item = session.exec(select(FeeItem).where(FeeItem.code == column["code"])).first()
    claim = session.exec(
        select(BillingClaim)
        .where(BillingClaim.billing_cycle_id == cycle.id)
        .where(BillingClaim.family_id == child.family_id)
    ).first()

    if amount == 0 and (fee_item is None or claim is None):
        return None

    if claim is None:
        claim = _ensure_claim_for_child(session, cycle=cycle, child=child)
    if claim.status in {BillingClaimStatus.exported, BillingClaimStatus.paid}:
        raise BillingCalculationError(f"{child.full_name} の請求は出力済みまたは入金済みです")

    if fee_item is None:
        fee_item = _ensure_table_fee_item(session, column)

    existing_lines = session.exec(
        select(BillingChargeLine)
        .where(BillingChargeLine.billing_claim_id == claim.id)
        .where(BillingChargeLine.child_id == child.id)
        .where(BillingChargeLine.fee_item_id == fee_item.id)
        .order_by(BillingChargeLine.id)
    ).all()
    if any(line.is_locked for line in existing_lines):
        raise BillingCalculationError(f"{child.full_name} の {column['label']} はロック済みです")

    if amount == 0:
        for line in existing_lines:
            session.delete(line)
        session.flush()
        return claim

    line = existing_lines[0] if existing_lines else None
    if line is None:
        line = BillingChargeLine(
            billing_claim_id=claim.id,
            fee_item_id=fee_item.id,
            child_id=child.id,
            source_type=column["source_type"],
            description=column["description"],
        )
    line.source_type = column["source_type"]
    line.source_date = cycle.period_start
    line.description = column["description"]
    line.quantity = 1
    line.unit_label = "式"
    line.unit_price = amount
    line.amount = amount
    line.is_locked = False
    line.updated_at = utc_now()
    session.add(line)

    for extra_line in existing_lines[1:]:
        session.delete(extra_line)
    session.flush()
    return claim


def _recalculate_touched_claims(session: Session, *, cycle: BillingCycle, claims: list[BillingClaim]) -> None:
    seen_ids: set[int] = set()
    for claim in claims:
        if claim.id is None or claim.id in seen_ids:
            continue
        seen_ids.add(claim.id)
        lines = session.exec(select(BillingChargeLine).where(BillingChargeLine.billing_claim_id == claim.id)).all()
        recalculate_claim_total(claim, lines)
        if cycle.status == BillingCycleStatus.confirmed:
            claim.status = BillingClaimStatus.confirmed
        elif claim.status != BillingClaimStatus.confirmed:
            claim.status = BillingClaimStatus.draft
        claim.updated_at = utc_now()
        session.add(claim)


@router.get("/")
async def billing_dashboard(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    def _fetch_dashboard_data():
        cycles = session.exec(select(BillingCycle).order_by(BillingCycle.year_month.desc())).all()
        claims = session.exec(select(BillingClaim)).all()
        exports = session.exec(select(ZenginExport).order_by(ZenginExport.created_at.desc())).all()

        claims_by_cycle: dict[int, list[BillingClaim]] = {}
        for claim in claims:
            claims_by_cycle.setdefault(claim.billing_cycle_id, []).append(claim)

        exports_by_cycle: dict[int, list[ZenginExport]] = {}
        for export in exports:
            exports_by_cycle.setdefault(export.billing_cycle_id, []).append(export)

        cycle_rows = []
        for cycle in cycles:
            cycle_claims = claims_by_cycle.get(cycle.id or 0, [])
            cycle_exports = exports_by_cycle.get(cycle.id or 0, [])
            reopen_export = reopenable_export(cycle, cycle_exports)
            reopen_estimate = {}
            if reopen_export is not None:
                try:
                    reopen_estimate = estimate_reopen_delta(session, reopen_export.id)
                except ZenginError:
                    reopen_estimate = {}
            cycle_rows.append(
                {
                    "cycle": cycle,
                    "claims": cycle_claims,
                    "claim_count": len(cycle_claims),
                    "total_amount": sum(claim.total_amount for claim in cycle_claims),
                    "exports": cycle_exports,
                    "status_label": BILLING_CYCLE_STATUS_LABELS.get(cycle.status, cycle.status.value),
                    "reopen_export": reopen_export,
                    "reopen_level": reopen_estimate.get("level", ""),
                    "reopen_delta_amount": reopen_estimate.get("delta_amount", 0),
                    "reopen_delta_count": reopen_estimate.get("delta_count", 0),
                }
            )

        export_rows = []
        reopen_ids = {row["reopen_export"].id for row in cycle_rows if row["reopen_export"]}
        cycles_by_id = {cycle.id: cycle for cycle in cycles}
        export_ids = [export.id for export in exports if export.id is not None]
        lines_by_export: dict[int, list[ZenginExportLine]] = {}
        if export_ids:
            all_lines = session.exec(
                select(ZenginExportLine).where(ZenginExportLine.zengin_export_id.in_(export_ids))
            ).all()
            for line in all_lines:
                lines_by_export.setdefault(line.zengin_export_id, []).append(line)
        for export in exports:
            lines = lines_by_export.get(export.id or 0, [])
            export_rows.append(
                {
                    "export": export,
                    "line_count": len(lines),
                    "status_label": ZENGIN_EXPORT_STATUS_LABELS.get(export.status, export.status.value),
                    "can_reopen": export.id in reopen_ids,
                    "year_month": cycles_by_id[export.billing_cycle_id].year_month if export.billing_cycle_id in cycles_by_id else "",
                }
            )

        setting = session.exec(select(BillingSetting).order_by(BillingSetting.id)).first()

        reopen_requests = []
        for export in exports:
            if not has_pending_reopen_confirm(export):
                continue
            payload = export.reopen_confirm_payload or {}
            reopen_requests.append(
                {
                    "export": export,
                    "year_month": cycles_by_id[export.billing_cycle_id].year_month if export.billing_cycle_id in cycles_by_id else "",
                    "requested_by": export.reopen_confirm_requested_by,
                    "requested_at": export.reopen_confirm_requested_at,
                    "reason_templates": payload.get("reason_templates", []),
                    "reason_free": payload.get("reason_free", ""),
                    "estimated_amount": payload.get("estimated_amount", export.total_amount),
                    "estimated_count": payload.get("estimated_count", export.total_count),
                    "delta_amount": payload.get("delta_amount", 0),
                }
            )

        return cycle_rows, export_rows, setting, reopen_requests

    cycle_rows, export_rows, setting, reopen_requests = await run_db_async(_fetch_dashboard_data)

    return templates.TemplateResponse(
        request,
        "billing/index.html",
        {
            "request": request,
            "current_user": current_user,
            "cycle_rows": cycle_rows,
            "export_rows": export_rows,
            "setting": setting,
            "reopen_requests": reopen_requests,
            "can_manage_billing_accounts": can_manage_billing_accounts(session, current_user),
            "can_export_zengin": can_export_zengin(session, current_user),
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.get("/accounts")
def billing_account_list(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_billing_account_manager(session, current_user)
    children = session.exec(
        select(Child)
        .where(Child.status == ChildStatus.enrolled, Child.family_id.is_not(None))
        .order_by(Child.last_name_kana, Child.first_name_kana, Child.id)
    ).all()
    family_ids = sorted({child.family_id for child in children if child.family_id is not None})
    families = (
        session.exec(select(Family).where(Family.id.in_(family_ids))).all()
        if family_ids
        else []
    )
    profiles = (
        session.exec(
            select(FamilyBillingProfile).where(FamilyBillingProfile.family_id.in_(family_ids))
        ).all()
        if family_ids
        else []
    )
    families_by_id = {family.id: family for family in families if family.id is not None}
    profiles_by_family = {profile.family_id: profile for profile in profiles}
    children_by_family: dict[int, list[Child]] = {}
    for child in children:
        if child.family_id is not None:
            children_by_family.setdefault(child.family_id, []).append(child)

    latest_cycle = session.exec(
        select(BillingCycle).order_by(BillingCycle.year_month.desc(), BillingCycle.id.desc())
    ).first()
    account_rows = []
    for family_id, family_children in children_by_family.items():
        profile = profiles_by_family.get(family_id)
        is_registered = bool(
            profile
            and profile.bank_code
            and profile.branch_code
            and profile.account_number
            and profile.account_holder_kana
        )
        account_rows.append(
            {
                "family": families_by_id.get(family_id),
                "children": family_children,
                "representative_child": family_children[0],
                "profile": profile,
                "payment_method_label": (
                    BILLING_PAYMENT_METHOD_LABELS.get(
                        profile.payment_method, profile.payment_method.value
                    )
                    if profile
                    else "未設定"
                ),
                "direct_debit_status_label": (
                    DIRECT_DEBIT_STATUS_LABELS.get(
                        profile.direct_debit_status, profile.direct_debit_status.value
                    )
                    if profile
                    else "未設定"
                ),
                "is_registered": is_registered,
            }
        )

    return templates.TemplateResponse(
        request,
        "billing/accounts.html",
        {
            "request": request,
            "current_user": current_user,
            "account_rows": account_rows,
            "latest_cycle": latest_cycle,
            "registered_count": sum(1 for row in account_rows if row["is_registered"]),
            "unregistered_count": sum(1 for row in account_rows if not row["is_registered"]),
        },
    )


@router.get("/cycles/{cycle_id}/child-charges")
def child_charge_form(
    cycle_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    cycle = session.get(BillingCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="請求月が見つかりません")

    children = session.exec(
        select(Child)
        .where(Child.status == ChildStatus.enrolled)
        .order_by(Child.last_name_kana, Child.first_name_kana, Child.id)
    ).all()
    claims = session.exec(select(BillingClaim).where(BillingClaim.billing_cycle_id == cycle_id)).all()
    claims_by_family = {claim.family_id: claim for claim in claims}
    claim_ids = [claim.id for claim in claims if claim.id is not None]
    charge_lines = []
    if claim_ids:
        charge_lines = session.exec(
            select(BillingChargeLine)
            .where(BillingChargeLine.billing_claim_id.in_(claim_ids))
            .order_by(BillingChargeLine.created_at.desc(), BillingChargeLine.id.desc())
        ).all()
    table_codes = [column["code"] for column in TABLE_CHARGE_COLUMNS]
    table_fee_items = session.exec(select(FeeItem).where(FeeItem.code.in_(table_codes))).all()
    table_item_codes_by_id = {item.id: item.code for item in table_fee_items if item.id is not None}
    table_amounts: dict[tuple[int, str], int] = {}
    table_locked_codes: dict[int, set[str]] = {}
    for line in charge_lines:
        if line.child_id is None:
            continue
        code = table_item_codes_by_id.get(line.fee_item_id)
        if code is None:
            continue
        key = (line.child_id, code)
        table_amounts[key] = table_amounts.get(key, 0) + line.amount
        if line.is_locked:
            table_locked_codes.setdefault(line.child_id, set()).add(code)

    profiles = session.exec(select(FamilyBillingProfile).order_by(FamilyBillingProfile.family_id)).all()
    profiles_by_family = {profile.family_id: profile for profile in profiles}
    children_by_id = {child.id: child for child in children}
    line_rows = []
    for line in charge_lines:
        child = children_by_id.get(line.child_id)
        claim = next((item for item in claims if item.id == line.billing_claim_id), None)
        line_rows.append(
            {
                "line": line,
                "child": child,
                "claim": claim,
                "claim_status_label": (
                    BILLING_CLAIM_STATUS_LABELS.get(claim.status, claim.status.value)
                    if claim
                    else "-"
                ),
            }
        )

    table_rows = []
    for child in children:
        amounts = {column["code"]: table_amounts.get((child.id, column["code"]), 0) for column in TABLE_CHARGE_COLUMNS}
        claim = claims_by_family.get(child.family_id) if child.family_id is not None else None
        profile = profiles_by_family.get(child.family_id) if child.family_id is not None else None
        table_rows.append(
            {
                "child": child,
                "claim": claim,
                "profile": profile,
                "profile_status_label": (
                    DIRECT_DEBIT_STATUS_LABELS.get(
                        profile.direct_debit_status, profile.direct_debit_status.value
                    )
                    if profile
                    else "未設定"
                ),
                "amounts": amounts,
                "locked_codes": table_locked_codes.get(child.id, set()),
                "row_total": sum(amounts.values()),
            }
        )

    editable = cycle.status in {
        BillingCycleStatus.draft,
        BillingCycleStatus.generated,
        BillingCycleStatus.confirmed,
    }
    return templates.TemplateResponse(
        request,
        "billing/child_charges.html",
        {
            "request": request,
            "current_user": current_user,
            "cycle": cycle,
            "cycle_status_label": BILLING_CYCLE_STATUS_LABELS.get(cycle.status, cycle.status.value),
            "children": children,
            "claims_by_family": claims_by_family,
            "charge_columns": TABLE_CHARGE_COLUMNS,
            "charge_column_groups": TABLE_CHARGE_GROUPS,
            "table_rows": table_rows,
            "line_rows": line_rows,
            "editable": editable,
            "reopen_export": reopenable_export(cycle, list(session.exec(select(ZenginExport).where(ZenginExport.billing_cycle_id == cycle_id)).all())),
            "can_export_zengin": can_export_zengin(session, current_user),
            "can_manage_billing_accounts": can_manage_billing_accounts(session, current_user),
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
            "return_month": request.query_params.get("return_month", ""),
        },
    )


@router.post("/cycles/{cycle_id}/child-charges/table")
async def update_child_charge_table(
    cycle_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    form = await request.form()
    cycle = lock_billing_cycle(session, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="請求月が見つかりません")
    if cycle.status not in {BillingCycleStatus.draft, BillingCycleStatus.generated, BillingCycleStatus.confirmed}:
        return _cycle_redirect(cycle_id, error="Zengin出力後の請求月は表入力できません")

    children = session.exec(
        select(Child)
        .where(Child.status == ChildStatus.enrolled)
        .order_by(Child.last_name_kana, Child.first_name_kana, Child.id)
    ).all()
    children_by_id = {child.id: child for child in children if child.id is not None}
    return_month = str(form.get("return_month", "")).strip()
    touched_claims: list[BillingClaim] = []

    try:
        for child_id, child in children_by_id.items():
            for column in TABLE_CHARGE_COLUMNS:
                field_name = f"amount_{column['code']}_{child_id}"
                if field_name not in form:
                    continue
                raw_value = str(form.get(field_name, ""))
                amount = _parse_table_amount(raw_value, child=child, column=column)
                touched_claim = _upsert_table_charge(
                    session,
                    cycle=cycle,
                    child=child,
                    column=column,
                    amount=amount,
                )
                if touched_claim is not None:
                    touched_claims.append(touched_claim)
        _recalculate_touched_claims(session, cycle=cycle, claims=touched_claims)
        cycle.updated_at = utc_now()
        session.add(cycle)
        session.commit()
    except BillingCalculationError as exc:
        session.rollback()
        response = child_charge_form(cycle_id, request, session, current_user)
        context = dict(response.context, error=str(exc), return_month=return_month)
        for row in context.get("table_rows", []):
            for column in TABLE_CHARGE_COLUMNS:
                field = f"amount_{column['code']}_{row['child'].id}"
                if field in form and column['code'] not in row.get('locked_codes', set()):
                    row['amounts'][column['code']] = str(form[field])
        return templates.TemplateResponse(request, "billing/child_charges.html", context, status_code=400)

    if len(return_month) == 7 and return_month[4] == "-":
        return RedirectResponse(
            url=(
                "/extended-care-fees/billing-transfer?"
                + urlencode(
                    {
                        "month": return_month,
                        "message": "請求入力を修正しました。転送内容を再確認してください。",
                    }
                )
            ),
            status_code=303,
        )
    return _cycle_redirect(cycle_id, message="表入力を保存しました")


@router.get("/cycles/{cycle_id}/child-charges/{child_id}")
def child_charge_input(
    cycle_id: int,
    child_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    cycle = session.get(BillingCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="請求月が見つかりません")
    child = session.get(Child, child_id)
    if child is None:
        raise HTTPException(status_code=404, detail="園児が見つかりません")

    claim = None
    profile = None
    line_rows = []
    if child.family_id is not None:
        profile = session.exec(
            select(FamilyBillingProfile).where(FamilyBillingProfile.family_id == child.family_id)
        ).first()
        claim = session.exec(
            select(BillingClaim)
            .where(BillingClaim.billing_cycle_id == cycle_id)
            .where(BillingClaim.family_id == child.family_id)
        ).first()
        if claim is not None:
            lines = session.exec(
                select(BillingChargeLine)
                .where(BillingChargeLine.billing_claim_id == claim.id)
                .where(BillingChargeLine.child_id == child.id)
                .order_by(BillingChargeLine.created_at.desc(), BillingChargeLine.id.desc())
            ).all()
            line_rows = [
                {
                    "line": line,
                    "claim": claim,
                    "claim_status_label": BILLING_CLAIM_STATUS_LABELS.get(
                        claim.status, claim.status.value
                    ),
                }
                for line in lines
            ]

    editable = cycle.status in {
        BillingCycleStatus.draft,
        BillingCycleStatus.generated,
        BillingCycleStatus.confirmed,
    }
    can_manage_account = can_manage_billing_accounts(session, current_user)
    profile_summary = {
        "payment_method": (
            BILLING_PAYMENT_METHOD_LABELS.get(profile.payment_method, profile.payment_method.value)
            if profile
            else "-"
        ),
        "direct_debit_status": (
            DIRECT_DEBIT_STATUS_LABELS.get(
                profile.direct_debit_status, profile.direct_debit_status.value
            )
            if profile
            else "-"
        ),
        "is_registered": bool(
            profile
            and (
                profile.bank_code
                or profile.branch_code
                or profile.account_number
                or profile.account_holder_kana
            )
        ),
    }
    return templates.TemplateResponse(
        request,
        "billing/child_charge_input.html",
        {
            "request": request,
            "current_user": current_user,
            "cycle": cycle,
            "cycle_status_label": BILLING_CYCLE_STATUS_LABELS.get(cycle.status, cycle.status.value),
            "child": child,
            "profile": profile if can_manage_account else None,
            "profile_summary": profile_summary,
            "can_manage_billing_accounts": can_manage_account,
            "claim": claim,
            "claim_status_label": (
                BILLING_CLAIM_STATUS_LABELS.get(claim.status, claim.status.value)
                if claim
                else "-"
            ),
            "line_rows": line_rows,
            "editable": editable,
            "reopen_export": reopenable_export(cycle, list(session.exec(select(ZenginExport).where(ZenginExport.billing_cycle_id == cycle_id)).all())),
            "can_export_zengin": can_export_zengin(session, current_user),
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/cycles/{cycle_id}/child-charges/{child_id}/profile")
def update_child_billing_profile(
    cycle_id: int,
    child_id: int,
    payment_method: str = Form(...),
    direct_debit_status: str = Form(...),
    bank_code: str = Form(""),
    bank_name_kana: str = Form(""),
    branch_code: str = Form(""),
    branch_name_kana: str = Form(""),
    account_type: str = Form(""),
    account_number: str = Form(""),
    account_holder_kana: str = Form(""),
    new_code: str = Form("0"),
    mandate_received_on: str = Form(""),
    note: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    billing_account_manager = require_billing_account_manager(session, current_user)
    cycle = session.get(BillingCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="請求月が見つかりません")
    child = session.get(Child, child_id)
    if child is None:
        raise HTTPException(status_code=404, detail="園児が見つかりません")
    if child.family_id is None:
        return _child_charge_redirect(cycle_id, child_id, error="園児に家族が紐づいていません")

    try:
        try:
            method = BillingPaymentMethod[payment_method]
        except KeyError:
            method = BillingPaymentMethod(payment_method)
        status = DirectDebitStatus(direct_debit_status)
        if new_code not in {"0", "1", "2"}:
            raise BillingCalculationError("新規コードは0, 1, 2のいずれかで入力してください")

        setting = _ensure_test_billing_setting(session)
        profile = session.exec(
            select(FamilyBillingProfile).where(FamilyBillingProfile.family_id == child.family_id)
        ).first()
        if profile is None:
            profile = FamilyBillingProfile(
                family_id=child.family_id,
                customer_number=create_customer_number(setting.customer_number_facility_code, child.family_id),
            )
            previous = {}
        else:
            previous = {
                "bank_code": profile.bank_code,
                "branch_code": profile.branch_code,
                "account_type": profile.account_type,
                "account_number": profile.account_number,
                "account_holder_kana": profile.account_holder_kana,
            }

        audit_before = {
            "payment_method": profile.payment_method.value,
            "direct_debit_status": profile.direct_debit_status.value,
            "bank_code": profile.bank_code,
            "bank_name_kana": profile.bank_name_kana,
            "branch_code": profile.branch_code,
            "branch_name_kana": profile.branch_name_kana,
            "account_type": profile.account_type,
            "account_number": profile.account_number,
            "account_holder_kana": profile.account_holder_kana,
            "new_code": profile.new_code,
            "mandate_received_on": profile.mandate_received_on.isoformat() if profile.mandate_received_on else None,
            "note": profile.note,
        }

        profile.payment_method = method
        profile.direct_debit_status = status
        profile.bank_code = _validate_account_digits(bank_code, 4, "銀行コード") if bank_code.strip() else None
        profile.bank_name_kana = bank_name_kana.strip() or None
        profile.branch_code = _validate_account_digits(branch_code, 3, "支店コード") if branch_code.strip() else None
        profile.branch_name_kana = branch_name_kana.strip() or None
        if account_type.strip() and account_type.strip() not in {"1", "2", "3", "9"}:
            raise BillingCalculationError("預金種目は1, 2, 3, 9のいずれかで入力してください")
        profile.account_type = account_type.strip() or None
        profile.account_number = _validate_account_number(account_number) if account_number.strip() else None
        profile.account_holder_kana = account_holder_kana.strip() or None
        profile.new_code = new_code
        profile.mandate_received_on = _parse_optional_date(mandate_received_on)
        profile.note = note.strip() or None
        if not previous and status == DirectDebitStatus.active and profile.new_code == "0":
            profile.new_code = "1"
        elif previous:
            _update_profile_new_code(profile, previous=previous)
        profile.updated_at = utc_now()
        session.add(profile)
        audit_after = {
            "payment_method": profile.payment_method.value,
            "direct_debit_status": profile.direct_debit_status.value,
            "bank_code": profile.bank_code,
            "bank_name_kana": profile.bank_name_kana,
            "branch_code": profile.branch_code,
            "branch_name_kana": profile.branch_name_kana,
            "account_type": profile.account_type,
            "account_number": profile.account_number,
            "account_holder_kana": profile.account_holder_kana,
            "new_code": profile.new_code,
            "mandate_received_on": profile.mandate_received_on.isoformat() if profile.mandate_received_on else None,
            "note": profile.note,
        }
        changed_fields = [
            field_name
            for field_name, previous_value in audit_before.items()
            if audit_after[field_name] != previous_value
        ]
        if changed_fields:
            session.add(
                FamilyBillingProfileChangeLog(
                    family_id=child.family_id,
                    child_id=child.id,
                    billing_cycle_id=cycle.id,
                    changed_fields=changed_fields,
                    changed_by_user_id=billing_account_manager.id,
                    changed_by_name_snapshot=billing_account_manager.display_name,
                )
            )
        session.commit()
    except (BillingCalculationError, ValueError) as exc:
        return _child_charge_redirect(cycle_id, child_id, error=str(exc))

    return _child_charge_redirect(cycle_id, child_id, message="口座情報を保存しました")


@router.post("/cycles/{cycle_id}/child-charges/{child_id}")
def add_child_charge_for_child(
    cycle_id: int,
    child_id: int,
    description: str = Form(...),
    amount: int = Form(...),
    quantity: int = Form(default=1),
    unit_label: str = Form(default="式"),
    source_date: date | None = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    cycle = session.get(BillingCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="請求月が見つかりません")
    child = session.get(Child, child_id)
    if child is None:
        raise HTTPException(status_code=404, detail="園児が見つかりません")
    try:
        _add_child_charge(
            session,
            cycle=cycle,
            child=child,
            description=description,
            amount=amount,
            quantity=quantity,
            unit_label=unit_label,
            source_date=source_date,
        )
    except BillingCalculationError as exc:
        return _child_charge_redirect(cycle_id, child_id, error=str(exc))
    session.commit()
    return _child_charge_redirect(cycle_id, child_id, message="請求明細を追加しました")


@router.post("/child-charges/new-editable-cycle")
def create_editable_cycle_for_table(
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    cycle = _create_blank_input_cycle(session, created_by=current_user.name)
    session.commit()
    return _cycle_redirect(cycle.id, message=f"{cycle.year_month} の新規請求月を作成しました")


@router.post("/child-charges/{child_id}/new-editable-cycle")
def create_editable_cycle_for_child(
    child_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    child = session.get(Child, child_id)
    if child is None:
        raise HTTPException(status_code=404, detail="園児が見つかりません")
    cycle = _create_blank_input_cycle(session, created_by=current_user.name)
    session.commit()
    return _child_charge_redirect(
        cycle.id,
        child.id,
        message=f"{cycle.year_month} の新規請求月を作成しました",
    )


@router.post("/cycles/{cycle_id}/child-charges")
def add_child_charge(
    cycle_id: int,
    child_id: int = Form(...),
    description: str = Form(...),
    amount: int = Form(...),
    quantity: int = Form(default=1),
    unit_label: str = Form(default="式"),
    source_date: date | None = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    cycle = session.get(BillingCycle, cycle_id)
    if cycle is None:
        raise HTTPException(status_code=404, detail="請求月が見つかりません")

    child = session.get(Child, child_id)
    if child is None:
        return _cycle_redirect(cycle_id, error="園児が見つかりません")
    try:
        _add_child_charge(
            session,
            cycle=cycle,
            child=child,
            description=description,
            amount=amount,
            quantity=quantity,
            unit_label=unit_label,
            source_date=source_date,
        )
    except BillingCalculationError as exc:
        return _cycle_redirect(cycle_id, error=str(exc))

    session.commit()
    return _cycle_redirect(cycle_id, message="園児別の請求明細を追加しました")


@router.post("/cycles/new-input")
def create_new_billing_cycle_from_dashboard(
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    cycle = _create_blank_input_cycle(session, created_by=current_user.name)
    session.commit()
    return _cycle_redirect(cycle.id, message=f"{cycle.year_month} の新規請求月を作成しました")


@router.post("/dev/seed")
def seed_demo_billing_data(
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    cycle = _create_blank_input_cycle(session, created_by=current_user.name)
    session.commit()
    return _cycle_redirect(cycle.id, message=f"{cycle.year_month} の新規請求月を作成しました")


@router.post("/zengin/{cycle_id}/create-ui")
def create_zengin_export_from_ui(
    cycle_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_zengin_exporter(session, current_user)
    try:
        export = create_zengin_export(session, cycle_id, created_by=current_user.name)
    except ZenginError as exc:
        return _dashboard_redirect(error=str(exc))
    return _dashboard_redirect(message=f"Zengin出力を作成しました: export_id={export.id}")


@router.post("/zengin/exports/{export_id}/mark-submitted-ui")
def mark_zengin_export_submitted_from_ui(
    export_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_zengin_exporter(session, current_user)
    try:
        mark_zengin_export_submitted(session, export_id)
    except ZenginError as exc:
        return _dashboard_redirect(error=str(exc))
    return _dashboard_redirect(message=f"銀行提出済みにしました: export_id={export_id}")


@router.post("/zengin/exports/{export_id}/cancel-ui")
async def cancel_zengin_export_from_ui(
    export_id: int,
    request: Request,
    reason: str = Form(default=""),
    reason_tpl: list[str] = Form(default=[]),
    confirmed_unsubmitted: bool = Form(default=False),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_zengin_exporter(session, current_user)
    audit_detail: dict = {}
    try:
        estimate = estimate_reopen_delta(session, export_id)
        combined_reason = combine_reopen_reason(reason_tpl, reason) or (reason or "").strip()
        audit_detail = {
            "level": estimate["level"],
            "delta_amount": estimate["delta_amount"],
            "delta_count": estimate["delta_count"],
            "reason": combined_reason,
        }
        if estimate["level"] == "L1" and not current_user.is_admin:
            # L1: diff-bearing cancel by a non-admin exporter requires director confirmation.
            export = request_reopen_confirm(
                session,
                export_id,
                reason=reason,
                reason_templates=list(reason_tpl),
                confirmed_unsubmitted=confirmed_unsubmitted,
                requested_by=current_user.name,
                estimate=estimate,
            )
            record_audit_event(
                actor_user_id=current_user.staff_id,
                actor_role=getattr(current_user.role, "value", None),
                target_resource="billing_reopen",
                resource_id=str(export_id),
                action="REQUEST",
                detail={**audit_detail, "requested_by": current_user.name},
            )
            delta = estimate["delta_amount"]
            delta_label = f"{delta:+,}円" if delta else "差額なし"
            return _cycle_redirect(
                export.billing_cycle_id,
                message=f"園長確認を依頼しました（差額 {delta_label}）。承認されるまで解除は実行されません。",
            )
        export = cancel_zengin_export_for_edit(
            session,
            export_id,
            reason=combined_reason or reason,
            confirmed_unsubmitted=confirmed_unsubmitted,
            canceled_by=current_user.name,
            approved_by=current_user.name if (estimate["level"] == "L1" and current_user.is_admin) else None,
        )
        if estimate["level"] == "L1":
            audit_detail["approved_by"] = current_user.name
        record_audit_event(
            actor_user_id=current_user.staff_id,
            actor_role=getattr(current_user.role, "value", None),
            target_resource="billing_reopen",
            resource_id=str(export_id),
            action="UPDATE",
            detail=audit_detail,
        )
    except ZenginError as exc:
        response = await billing_dashboard(request, session, current_user)
        context = dict(response.context, error=str(exc))
        row = next((row for row in context.get("export_rows", []) if row["export"].id == export_id), None)
        if row and row.get("can_reopen"):
            item = row["export"]
            try:
                estimate = estimate_reopen_delta(session, export_id)
            except ZenginError:
                estimate = {}
            context["reopen_initial"] = dict(
                id=item.id,
                month=row.get("year_month", ""),
                count=item.total_count,
                amount=item.total_amount,
                reason=reason,
                reason_templates=list(reason_tpl),
                checked=confirmed_unsubmitted,
                level=estimate.get("level", ""),
                delta_amount=estimate.get("delta_amount", 0),
                error=str(exc),
            )
        return templates.TemplateResponse(request, "billing/index.html", context, status_code=409)
    return _cycle_redirect(
        export.billing_cycle_id,
        message=f"出力 #{export.id} を取消しました。請求金額を修正・保存し、請求一覧からZenginを再作成してください。",
    )


@router.post("/zengin/exports/{export_id}/reopen-approve-ui")
def approve_reopen_confirm_from_ui(
    export_id: int,
    confirmed_unsubmitted: bool = Form(default=False),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_live_admin(session, current_user)
    try:
        export = approve_reopen_and_cancel(
            session,
            export_id,
            approved_by=current_user.name,
            confirmed_unsubmitted=confirmed_unsubmitted,
        )
    except ZenginError as exc:
        return _dashboard_redirect(error=str(exc))
    record_audit_event(
        actor_user_id=current_user.staff_id,
        actor_role=getattr(current_user.role, "value", None),
        target_resource="billing_reopen",
        resource_id=str(export_id),
        action="UPDATE",
        detail={
            "approved_by": current_user.name,
            "requested_by": export.reopen_confirm_requested_by,
            "reason": export.canceled_reason,
        },
    )
    return _cycle_redirect(
        export.billing_cycle_id,
        message=f"園長承認により出力 #{export.id} を取消しました。請求金額を修正・保存し、請求一覧からZenginを再作成してください。",
    )


@router.post("/zengin/exports/{export_id}/reopen-request-cancel-ui")
def cancel_reopen_request_from_ui(
    export_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_zengin_exporter(session, current_user)
    export = session.get(ZenginExport, export_id)
    if export is None:
        return _dashboard_redirect(error="Zengin出力が見つかりません")
    if not has_pending_reopen_confirm(export):
        return _dashboard_redirect(error="確認待ちの申請がありません")
    if export.reopen_confirm_requested_by != current_user.name and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="申請者または管理者のみ申請を取り消せます")
    withdraw_reopen_request(session, export_id)
    record_audit_event(
        actor_user_id=current_user.staff_id,
        actor_role=getattr(current_user.role, "value", None),
        target_resource="billing_reopen",
        resource_id=str(export_id),
        action="CANCEL",
        detail={"withdrawn_by": current_user.name},
    )
    return _dashboard_redirect(message=f"出力 #{export_id} の園長確認申請を取り消しました。")


@router.post("/zengin/exports/{export_id}/supersede-ui")
def supersede_zengin_export_from_ui(
    export_id: int,
    reason: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_zengin_exporter(session, current_user)
    try:
        replacement = supersede_zengin_export(
            session,
            export_id,
            reason=reason,
            created_by=current_user.name,
        )
    except ZenginError as exc:
        return _dashboard_redirect(error=str(exc))
    return _dashboard_redirect(
        message=f"Zengin出力を差し替えました: export_id={replacement.id}"
    )


@router.post("/zengin/exports/{export_id}/import-paid-demo")
def import_paid_demo_result(
    export_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_zengin_exporter(session, current_user)
    export = session.get(ZenginExport, export_id)
    if export is None:
        raise HTTPException(status_code=404, detail="Zengin出力履歴が見つかりません")
    lines = session.exec(
        select(ZenginExportLine)
        .where(ZenginExportLine.zengin_export_id == export_id)
        .order_by(ZenginExportLine.id)
    ).all()
    result_records = [
        ParsedResultRecord(customer_number=line.customer_number, amount=line.amount, result_code="0")
        for line in lines
    ]
    encoding = export.settings_snapshot.get("file_encoding", "cp932")
    records = [build_header_record(export.settings_snapshot, export.withdrawal_date)]
    records.extend(build_data_record(line, encoding) for line in lines)
    records.append(build_trailer_record(lines, encoding, result_records=result_records))
    records.append(build_end_record(encoding))
    file_bytes = build_file_bytes(records, encoding, export.settings_snapshot.get("line_separator", "CRLF"))
    try:
        parsed = import_result_file(session, file_bytes, export_id)
    except ZenginError as exc:
        return _dashboard_redirect(error=str(exc))
    if parsed.errors:
        return _dashboard_redirect(error=" / ".join(parsed.errors))
    return _dashboard_redirect(message=f"疑似結果ファイルを取り込みました: {len(parsed.records)}件")


@router.post("/cycles")
def create_cycle(
    year_month: str = Form(...),
    period_start: date = Form(...),
    period_end: date = Form(...),
    withdrawal_date: date = Form(...),
    due_date: date | None = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    if period_end < period_start:
        raise HTTPException(status_code=400, detail="対象期間が不正です")
    existing = session.exec(select(BillingCycle).where(BillingCycle.year_month == year_month)).first()
    if existing:
        raise HTTPException(status_code=409, detail="同一請求月は既に存在します")
    cycle = BillingCycle(
        year_month=year_month,
        period_start=period_start,
        period_end=period_end,
        withdrawal_date=withdrawal_date,
        due_date=due_date,
    )
    session.add(cycle)
    session.commit()
    session.refresh(cycle)
    return {"id": cycle.id, "year_month": cycle.year_month, "status": cycle.status.value}


@router.post("/cycles/{cycle_id}/confirm")
def confirm_cycle(
    cycle_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    cycle = session.get(BillingCycle, cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="請求月が見つかりません")
    if cycle.status != BillingCycleStatus.generated:
        raise HTTPException(status_code=400, detail="generated状態の請求月のみ確定できます")
    now = utc_now()
    cycle.status = BillingCycleStatus.confirmed
    cycle.confirmed_at = now
    cycle.confirmed_by = current_user.name
    cycle.updated_at = now
    session.add(cycle)

    # 配下の draft 請求明細も一括で confirmed へ昇格させ、全銀出力可能な状態に連動させる
    draft_claims = session.exec(
        select(BillingClaim).where(
            BillingClaim.billing_cycle_id == cycle_id,
            BillingClaim.status == BillingClaimStatus.draft,
        )
    ).all()
    for claim in draft_claims:
        claim.status = BillingClaimStatus.confirmed
        claim.updated_at = now
        session.add(claim)

    session.commit()
    return {
        "id": cycle.id,
        "status": cycle.status.value,
        "confirmed_claims_count": len(draft_claims),
    }


@router.post("/cycles/{cycle_id}/unconfirm")
def unconfirm_cycle(
    cycle_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    cycle = session.get(BillingCycle, cycle_id)
    if not cycle:
        raise HTTPException(status_code=404, detail="請求月が見つかりません")
    if cycle.status != BillingCycleStatus.confirmed:
        raise HTTPException(status_code=400, detail="confirmed状態の請求月のみ確定取消できます")
    locked_claim = session.exec(
        select(BillingClaim).where(
            BillingClaim.billing_cycle_id == cycle_id,
            BillingClaim.status.in_([BillingClaimStatus.exported, BillingClaimStatus.paid]),
        )
    ).first()
    if locked_claim:
        raise HTTPException(status_code=400, detail="全銀出力済みまたは入金済みの明細があるため確定取消できません")

    now = utc_now()
    cycle.status = BillingCycleStatus.generated
    cycle.confirmed_at = None
    cycle.confirmed_by = None
    cycle.updated_at = now
    session.add(cycle)

    confirmed_claims = session.exec(
        select(BillingClaim).where(
            BillingClaim.billing_cycle_id == cycle_id,
            BillingClaim.status == BillingClaimStatus.confirmed,
        )
    ).all()
    for claim in confirmed_claims:
        claim.status = BillingClaimStatus.draft
        claim.updated_at = now
        session.add(claim)

    session.commit()
    return {
        "id": cycle.id,
        "status": cycle.status.value,
        "reverted_claims_count": len(confirmed_claims),
    }


# ==========================================
# P8-1: 料金マスタ & 全銀口座振替設定
# ==========================================

@router.get("/settings")
def billing_settings_page(
    request: Request,
    message: str = "",
    error: str = "",
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """料金マスタ一覧、全銀設定、減免措置マスタの管理画面 (P8-1, P8-3)。"""
    require_can_edit(current_user)
    fee_items = session.exec(select(FeeItem).order_by(FeeItem.display_order, FeeItem.id)).all()
    setting = _ensure_test_billing_setting(session)
    exemptions = session.exec(
        select(BillingExemption).where(BillingExemption.is_active == True).order_by(BillingExemption.valid_from.desc(), BillingExemption.id.desc())
    ).all()
    children = session.exec(
        select(Child).where(Child.status == ChildStatus.enrolled).order_by(Child.last_name_kana, Child.first_name_kana, Child.id)
    ).all()
    children_map = {c.id: c for c in session.exec(select(Child)).all()}
    fee_items_map = {f.id: f for f in fee_items}

    return templates.TemplateResponse(
        request,
        "billing/settings.html",
        {
            "request": request,
            "current_user": current_user,
            "fee_items": fee_items,
            "setting": setting,
            "exemptions": exemptions,
            "children": children,
            "children_map": children_map,
            "fee_items_map": fee_items_map,
            "message": message,
            "error": error,
        },
    )


@router.post("/settings/exemptions")
def create_exemption_action(
    child_id: int = Form(...),
    name: str = Form(...),
    fee_item_id: int | None = Form(default=None),
    exemption_type: str = Form(default="full"),
    discount_amount: int = Form(default=0),
    discount_rate: int = Form(default=100),
    valid_from: str = Form(...),
    valid_to: str | None = Form(default=None),
    reason: str | None = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """園児ごとの減免・免除措置を登録する (P8-3)。"""
    require_admin(current_user)
    child = session.get(Child, child_id)
    if not child:
        raise HTTPException(404, "園児が見つかりません")

    from_d = date.fromisoformat(valid_from.strip())
    to_d = date.fromisoformat(valid_to.strip()) if valid_to and valid_to.strip() else None

    exemption = BillingExemption(
        child_id=child_id,
        name=name.strip(),
        fee_item_id=fee_item_id if fee_item_id and fee_item_id > 0 else None,
        exemption_type=ExemptionType(exemption_type),
        discount_amount=max(0, discount_amount),
        discount_rate=max(0, min(100, discount_rate)),
        valid_from=from_d,
        valid_to=to_d,
        reason=reason.strip() if reason and reason.strip() else None,
        is_active=True,
    )
    session.add(exemption)
    session.commit()
    return RedirectResponse(url="/billing/settings?message=減免・免除措置を登録しました", status_code=303)


@router.post("/settings/exemptions/{exemption_id}/delete")
def delete_exemption_action(
    exemption_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """減免・免除措置を削除する (P8-3)。"""
    require_admin(current_user)
    exemption = session.get(BillingExemption, exemption_id)
    if not exemption:
        raise HTTPException(404, "減免設定が見つかりません")

    session.delete(exemption)
    session.commit()
    return RedirectResponse(url="/billing/settings?message=減免・免除設定を削除しました", status_code=303)


@router.post("/settings/fee-items")
def create_fee_item_action(
    request: Request,
    code: str = Form(...),
    name: str = Form(...),
    category: str = Form("other"),
    charge_unit: str = Form("monthly"),
    default_amount: int = Form(0),
    taxable_type: str = Form("non_taxable"),
    display_order: int = Form(100),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """新しい料金項目を登録する (P8-1)。"""
    require_admin(current_user)
    clean_code = code.strip()
    clean_name = name.strip()
    if not clean_code or not clean_name:
        raise HTTPException(400, "項目コードと項目名は必須です")

    existing = session.exec(select(FeeItem).where(FeeItem.code == clean_code)).first()
    if existing:
        raise HTTPException(400, f"コード '{clean_code}' は既に使用されています")

    item = FeeItem(
        code=clean_code,
        name=clean_name,
        category=category,
        charge_unit=charge_unit,
        default_amount=max(0, default_amount),
        taxable_type=taxable_type,
        display_order=display_order,
    )
    session.add(item)
    session.commit()
    return RedirectResponse(url="/billing/settings?message=料金項目を追加しました", status_code=303)


@router.post("/settings/fee-items/{item_id}/edit")
def edit_fee_item_action(
    item_id: int,
    name: str = Form(...),
    default_amount: int = Form(0),
    taxable_type: str = Form("non_taxable"),
    is_active: bool = Form(True),
    display_order: int = Form(100),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """既存の料金項目を編集・有効無効切り替えする (P8-1)。"""
    require_admin(current_user)
    item = session.get(FeeItem, item_id)
    if not item:
        raise HTTPException(404, "料金項目が見つかりません")

    item.name = name.strip()
    item.default_amount = max(0, default_amount)
    item.taxable_type = taxable_type
    item.is_active = is_active
    item.display_order = display_order
    item.updated_at = utc_now()
    session.add(item)
    session.commit()
    return RedirectResponse(url="/billing/settings?message=料金項目を更新しました", status_code=303)


@router.post("/settings/zengin")
def update_zengin_setting_action(
    facility_name: str = Form(...),
    collector_code: str = Form(...),
    collector_name_kana: str = Form(...),
    withdrawal_bank_code: str = Form(...),
    withdrawal_branch_code: str = Form(...),
    collector_account_number: str = Form(...),
    collector_account_type: str = Form("1"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """全銀口座振替の基本設定を更新する (P8-1)。"""
    require_admin(current_user)
    setting = _ensure_test_billing_setting(session)
    setting.facility_name = facility_name.strip()
    setting.collector_code = collector_code.strip()
    setting.collector_name_kana = collector_name_kana.strip()
    setting.withdrawal_bank_code = withdrawal_bank_code.strip()
    setting.withdrawal_branch_code = withdrawal_branch_code.strip()
    setting.collector_account_number = collector_account_number.strip()
    setting.collector_account_type = collector_account_type
    setting.updated_at = utc_now()
    session.add(setting)
    session.commit()
    return RedirectResponse(url="/billing/settings?message=全銀設定を更新しました", status_code=303)


# ==========================================
# P8-5: 確定前自動検算レポート
# ==========================================

def audit_billing_cycle(session: Session, cycle_id: int) -> dict[str, object]:
    """請求確定前の整合性チェックと異常抽出レポートを生成する (P8-5)。"""
    cycle = session.get(BillingCycle, cycle_id)
    if not cycle:
        raise HTTPException(404, "請求月が見つかりません")

    claims = session.exec(select(BillingClaim).where(BillingClaim.billing_cycle_id == cycle_id)).all()

    warnings: list[dict[str, str]] = []
    total_claims_amount = 0
    total_lines_amount = 0
    zero_amount_count = 0
    carryover_count = 0
    prorated_count = 0

    for claim in claims:
        lines = session.exec(select(BillingChargeLine).where(BillingChargeLine.billing_claim_id == claim.id)).all()
        lines_sum = sum(line.amount for line in lines)
        total_lines_amount += lines_sum
        total_claims_amount += claim.total_amount

        # 1. 明細合計と請求額の不一致チェック
        if lines_sum != claim.total_amount:
            warnings.append({
                "type": "mismatch",
                "level": "error",
                "message": f"家族ID {claim.family_id}: 明細合計 (¥{lines_sum:,}) と請求合計 (¥{claim.total_amount:,}) が一致しません。",
            })

        # 2. 0円請求のチェック
        if claim.total_amount == 0:
            zero_amount_count += 1

        # 3. 繰越明細・日割り明細のチェック
        for line in lines:
            if "繰越" in (line.description or ""):
                carryover_count += 1
            if "日割り" in (line.description or ""):
                prorated_count += 1

    if zero_amount_count > 0:
        warnings.append({
            "type": "zero_amount",
            "level": "warning",
            "message": f"請求合計が 0 円の家族が {zero_amount_count} 件あります（口座振替依頼データからは自動除外されます）。",
        })

    if carryover_count > 0:
        warnings.append({
            "type": "carryover_detected",
            "level": "info",
            "message": f"前月からの振替不能繰越明細が {carryover_count} 件含まれています。",
        })

    # 4. 減免・免除措置の適用状況・期限満了チェック (P8-3)
    active_exemptions = session.exec(
        select(BillingExemption).where(BillingExemption.is_active == True)
    ).all()
    exemptions_count = len(active_exemptions)
    for ex in active_exemptions:
        if ex.valid_to and cycle.period_start <= ex.valid_to <= cycle.period_end:
            child = session.get(Child, ex.child_id)
            c_name = child.full_name if child else f"園児ID:{ex.child_id}"
            warnings.append({
                "type": "exemption_expiring",
                "level": "info",
                "message": f"減免期限満了: {c_name}（{ex.name}）の適用期限が {ex.valid_to.strftime('%Y/%m/%d')} で満了します。翌月以降の更新要否を確認してください。",
            })

    # 5. 兄弟割引・出生順位自動判定チェック (P8-6 / B2軽量版不一致チェック)
    sibling_discount_count = 0
    sibling_mismatch_count = 0
    claim_lines_by_child: dict[int, list[BillingChargeLine]] = {}
    for claim in claims:
        lines = session.exec(
            select(BillingChargeLine).where(BillingChargeLine.billing_claim_id == claim.id)
        ).all()
        for line in lines:
            if line.child_id:
                claim_lines_by_child.setdefault(line.child_id, []).append(line)

    active_exemption_child_ids = {
        ex.child_id
        for ex in active_exemptions
        if ex.valid_from <= cycle.period_end and (ex.valid_to is None or ex.valid_to >= cycle.period_start)
    }

    for cid, child_lines in claim_lines_by_child.items():
        s_info = calculate_sibling_discount_for_child(session, cid, cycle.year_month)
        discount_pct = s_info.get("discount_percentage", 0)
        child = session.get(Child, cid)
        c_name = child.full_name if child else f"園児ID:{cid}"
        has_sibling_note = any("多子" in (ln.description or "") for ln in child_lines)
        has_manual_exemption = cid in active_exemption_child_ids

        if discount_pct > 0:
            sibling_discount_count += 1
            warnings.append({
                "type": "sibling_discount_applied",
                "level": "info",
                "message": f"兄弟割引判定: {c_name}（{s_info['rank_label']} - 軽減率{discount_pct}%）",
            })
            if not has_sibling_note and not has_manual_exemption and any(ln.amount > 0 for ln in child_lines):
                sibling_mismatch_count += 1
                warnings.append({
                    "type": "sibling_discount_mismatch",
                    "level": "warning",
                    "message": f"兄弟割引不一致: {c_name} は自動判定で {s_info['rank_label']}（{discount_pct}%軽減）ですが、請求明細に多子軽減の適用が見当たりません。再計算または個別減免を確認してください。",
                })
        elif has_sibling_note and not has_manual_exemption:
            sibling_mismatch_count += 1
            warnings.append({
                "type": "sibling_discount_mismatch",
                "level": "warning",
                "message": f"兄弟割引不一致: {c_name} は自動判定では対象外（{s_info['rank_label']}）ですが、請求明細に多子軽減が含まれています。在園変動を確認してください。",
            })

    is_valid = not any(w["level"] == "error" for w in warnings)

    return {
        "cycle_id": cycle.id,
        "year_month": cycle.year_month,
        "is_valid": is_valid,
        "claims_count": len(claims),
        "total_amount": total_claims_amount,
        "lines_amount": total_lines_amount,
        "zero_amount_count": zero_amount_count,
        "carryover_count": carryover_count,
        "prorated_count": prorated_count,
        "exemptions_count": exemptions_count,
        "sibling_discount_count": sibling_discount_count,
        "sibling_mismatch_count": sibling_mismatch_count,
        "warnings": warnings,
    }


def apply_child_exemptions(
    session: Session,
    child_id: int,
    fee_item_id: int | None,
    original_amount: int,
    target_date: date,
) -> tuple[int, str]:
    """園児の減免措置を適用した金額と適用理由を返す (P8-3 / P8-6)。

    個別登録の減免措置（BillingExemption）を優先適用し、
    残額がある場合は兄弟出生順位に基づく多子軽減（P8-6）を自動適用します。

    返り値: (減免後金額, 備考メッセージ)
    """
    exemptions = session.exec(
        select(BillingExemption)
        .where(
            BillingExemption.child_id == child_id,
            BillingExemption.is_active == True,
            BillingExemption.valid_from <= target_date,
        )
    ).all()

    applied_amount = original_amount
    notes = []

    for ex in exemptions:
        if ex.valid_to and ex.valid_to < target_date:
            continue
        if ex.fee_item_id is not None and ex.fee_item_id != fee_item_id:
            continue

        if ex.exemption_type == ExemptionType.full:
            applied_amount = 0
            notes.append(f"{ex.name}(全額免除)")
            break
        elif ex.exemption_type == ExemptionType.fixed_discount:
            applied_amount = max(0, applied_amount - ex.discount_amount)
            notes.append(f"{ex.name}(-¥{ex.discount_amount:,})")
        elif ex.exemption_type == ExemptionType.percentage:
            discount = int(applied_amount * ex.discount_rate / 100)
            applied_amount = max(0, applied_amount - discount)
            notes.append(f"{ex.name}({ex.discount_rate}%減額)")

    # 兄弟割引・出生順位自動判定の適用 (P8-6)
    if applied_amount > 0:
        target_month_str = target_date.strftime("%Y-%m")
        s_info = calculate_sibling_discount_for_child(session, child_id, target_month_str)
        if s_info.get("discount_percentage", 0) > 0:
            if s_info.get("discount_type") == "full":
                applied_amount = 0
                notes.append(f"{s_info['rank_label']}(多子無償化)")
            elif s_info.get("discount_type") == "percentage":
                discount = int(applied_amount * s_info["discount_percentage"] / 100)
                applied_amount = max(0, applied_amount - discount)
                notes.append(f"{s_info['rank_label']}(多子{s_info['discount_percentage']}%軽減)")

    note_str = " / ".join(notes) if notes else ""
    return applied_amount, note_str


@router.get("/cycles/{cycle_id}/audit")
def cycle_audit_api(
    cycle_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """請求確定前の自動検算結果を返す (P8-5)。"""
    require_can_edit(current_user)
    return audit_billing_cycle(session, cycle_id)


# ==========================================
# P8-4: 振替不能（残高不足等）の翌月繰越
# ==========================================

@router.post("/claims/{claim_id}/carryover")
def carryover_unpaid_claim(
    claim_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """振替不能となった未収明細を翌月の請求サイクルへ繰り越す (P8-4)。"""
    require_can_edit(current_user)
    claim = session.get(BillingClaim, claim_id)
    if not claim:
        raise HTTPException(404, "請求が見つかりません")

    cycle = session.get(BillingCycle, claim.billing_cycle_id)
    if not cycle:
        raise HTTPException(404, "請求サイクルが見つかりません")

    carryover_amount = claim.total_amount
    if carryover_amount <= 0:
        raise HTTPException(400, "繰り越す未収金額がありません")

    # 翌月のサイクルを探す（なければ直近の未確定サイクル、または自動生成）
    all_cycles = session.exec(select(BillingCycle).order_by(BillingCycle.year_month)).all()
    next_cycle = None
    for c in all_cycles:
        if c.year_month > cycle.year_month and c.status == BillingCycleStatus.generated:
            next_cycle = c
            break

    if not next_cycle:
        # 新しい未確定サイクルを生成
        next_cycle = _create_blank_input_cycle(session, created_by=current_user.name)

    # 翌月サイクルでの該当家族の請求を取得または作成
    next_claim = session.exec(
        select(BillingClaim).where(
            BillingClaim.billing_cycle_id == next_cycle.id,
            BillingClaim.family_id == claim.family_id,
        )
    ).first()

    if not next_claim:
        next_claim = BillingClaim(
            billing_cycle_id=next_cycle.id,
            family_id=claim.family_id,
            claim_number=f"CLAIM-{next_cycle.year_month}-{claim.family_id:04d}",
            total_amount=0,
            status=BillingClaimStatus.draft,
            payment_method=claim.payment_method,
        )
        session.add(next_claim)
        session.flush()

    # 繰越明細を追加
    carryover_item = _ensure_manual_fee_item(session, code="carryover", name="振替不能分繰越")
    carryover_line = BillingChargeLine(
        billing_claim_id=next_claim.id,
        fee_item_id=carryover_item.id,
        source_type=BillingChargeSourceType.manual,
        description=f"{cycle.year_month}分 振替不能分繰越",
        amount=carryover_amount,
        quantity=1,
    )
    session.add(carryover_line)
    session.flush()

    # 再計算
    next_claim.total_amount += carryover_amount
    next_claim.updated_at = utc_now()
    session.add(next_claim)
    session.commit()

    return {
        "status": "ok",
        "message": f"{cycle.year_month}分 の未収額 ¥{carryover_amount:,} を {next_cycle.year_month} へ繰り越しました",
        "next_cycle_year_month": next_cycle.year_month,
        "carried_amount": carryover_amount,
    }


# ==========================================
# P8-2: 月途中入退園の自動日割り算定ヘルパー
# ==========================================

def calculate_prorated_meal_fee(
    full_amount: int,
    start_date: date,
    end_date: date,
    enrollment_date: date | None,
    withdrawal_date: date | None,
) -> tuple[int, int, int]:
    """月途中入退園の実開園平日日数に基づく日割り給食費を計算する (P8-2)。

    返り値: (日割り金額, 在園開園日数, 全開園日数)
    """
    from datetime import timedelta
    cur = start_date
    total_weekdays = 0
    enrolled_weekdays = 0

    while cur <= end_date:
        # 土日を除外（平日を開園日と仮定）
        if cur.weekday() < 5:
            total_weekdays += 1
            is_enrolled = True
            if enrollment_date and cur < enrollment_date:
                is_enrolled = False
            if withdrawal_date and cur > withdrawal_date:
                is_enrolled = False
            if is_enrolled:
                enrolled_weekdays += 1
        cur += timedelta(days=1)

    if total_weekdays == 0:
        return full_amount, 0, 0

    if enrolled_weekdays >= total_weekdays:
        return full_amount, total_weekdays, total_weekdays

    # 四捨五入
    prorated = int(round((full_amount * enrolled_weekdays) / total_weekdays))
    return prorated, enrolled_weekdays, total_weekdays
