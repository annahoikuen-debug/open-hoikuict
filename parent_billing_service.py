"""Parent Billing & Extended Care Service.

Provides real-time extended care charge aggregations and confirmed billing claim
statements for the Parent Portal, with strict family ID scoping (IDOR defense)
and facility-level ON/OFF gating.
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any, Optional

from sqlmodel import Session, select

from models import (
    AttendanceRecord,
    BillingChargeLine,
    BillingClaim,
    BillingClaimStatus,
    BillingCycle,
    BillingCycleStatus,
    Child,
    ExtendedCareCharge,
    FamilyBillingProfile,
)
from time_utils import local_today

WEEKDAY_JA = ("月", "火", "水", "木", "金", "土", "日")

CLAIM_STATUS_LABELS = {
    BillingClaimStatus.draft: "作成中",
    BillingClaimStatus.confirmed: "確定",
    BillingClaimStatus.exported: "振替手配中",
    BillingClaimStatus.paid: "決済完了",
    BillingClaimStatus.failed: "引落不能",
    BillingClaimStatus.exempted: "免除",
    BillingClaimStatus.canceled: "取消",
}


def get_parent_realtime_extended_care_summary(
    session: Session,
    *,
    family_id: int,
    year_month: Optional[str] = None,
) -> dict[str, Any]:
    """当月の登降園実績から日次の延長保育料速報と累計を集計する。

    打刻実績に基づく ExtendedCareCharge レコードから、暫定延長料金と分数を集計して返却する。
    """
    today = local_today()
    if not year_month:
        target_ym = today.strftime("%Y-%m")
    else:
        target_ym = year_month.strip()

    try:
        parts = target_ym.split("-")
        year = int(parts[0])
        month = int(parts[1])
        _, last_day = monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)
    except (ValueError, IndexError):
        year, month = today.year, today.month
        _, last_day = monthrange(year, month)
        start_date = date(year, month, 1)
        end_date = date(year, month, last_day)
        target_ym = today.strftime("%Y-%m")

    if not family_id:
        return {
            "year_month": target_ym,
            "start_date": start_date,
            "end_date": end_date,
            "total_extended_minutes": 0,
            "total_estimated_amount": 0,
            "charges": [],
        }

    # 家族に所属する園児を取得
    children = session.exec(select(Child).where(Child.family_id == family_id)).all()
    child_map = {c.id: f"{c.last_name} {c.first_name}" for c in children if c.id is not None}
    child_ids = list(child_map.keys())

    if not child_ids:
        return {
            "year_month": target_ym,
            "start_date": start_date,
            "end_date": end_date,
            "total_extended_minutes": 0,
            "total_estimated_amount": 0,
            "charges": [],
        }

    charges = session.exec(
        select(ExtendedCareCharge)
        .where(
            ExtendedCareCharge.child_id.in_(child_ids),
            ExtendedCareCharge.target_date >= start_date,
            ExtendedCareCharge.target_date <= end_date,
        )
        .order_by(ExtendedCareCharge.target_date.desc(), ExtendedCareCharge.id.desc())
    ).all()

    att_ids = [c.attendance_record_id for c in charges if c.attendance_record_id]
    att_map: dict[int, AttendanceRecord] = {}
    if att_ids:
        atts = session.exec(select(AttendanceRecord).where(AttendanceRecord.id.in_(att_ids))).all()
        att_map = {a.id: a for a in atts if a.id is not None}

    items = []
    total_minutes = 0
    total_amount = 0

    for charge in charges:
        total_minutes += charge.extended_minutes or 0
        total_amount += charge.final_amount or 0

        att = att_map.get(charge.attendance_record_id)
        check_out_time_str = "—"
        has_snack = False

        if att:
            if att.check_out_at:
                check_out_time_str = att.check_out_at.strftime("%H:%M")
            has_snack = bool(att.pickup_snack_confirmed or att.snack_required)
        elif charge.actual_check_out_at:
            check_out_time_str = charge.actual_check_out_at.strftime("%H:%M")

        weekday_str = WEEKDAY_JA[charge.target_date.weekday()]
        formatted_date = f"{charge.target_date.month}/{charge.target_date.day:02d} ({weekday_str})"

        items.append({
            "id": charge.id,
            "child_id": charge.child_id,
            "child_name": child_map.get(charge.child_id, "園児"),
            "target_date": charge.target_date,
            "formatted_date": formatted_date,
            "check_out_time": check_out_time_str,
            "extended_minutes": charge.extended_minutes or 0,
            "amount": charge.final_amount or 0,
            "has_snack": has_snack,
            "status": charge.status.value if hasattr(charge.status, "value") else str(charge.status),
        })

    return {
        "year_month": target_ym,
        "start_date": start_date,
        "end_date": end_date,
        "total_extended_minutes": total_minutes,
        "total_estimated_amount": total_amount,
        "charges": items,
    }


def get_parent_billing_claims_list(
    session: Session,
    *,
    family_id: int,
) -> list[dict[str, Any]]:
    """保護者家庭の確定済み月次請求一覧を取得する（ドラフト非公開制御）。"""
    if not family_id:
        return []

    rows = session.exec(
        select(BillingClaim, BillingCycle)
        .join(BillingCycle, BillingClaim.billing_cycle_id == BillingCycle.id)
        .where(
            BillingClaim.family_id == family_id,
            BillingCycle.status != BillingCycleStatus.draft,
            BillingClaim.status != BillingClaimStatus.draft,
            BillingClaim.status != BillingClaimStatus.canceled,
        )
        .order_by(BillingCycle.year_month.desc())
    ).all()

    result = []
    for claim, cycle in rows:
        status_enum = claim.status
        status_label = CLAIM_STATUS_LABELS.get(status_enum, str(status_enum))
        result.append({
            "id": claim.id,
            "year_month": cycle.year_month,
            "period_start": cycle.period_start,
            "period_end": cycle.period_end,
            "withdrawal_date": cycle.withdrawal_date,
            "due_date": cycle.due_date,
            "payment_method": claim.payment_method.value if hasattr(claim.payment_method, "value") else str(claim.payment_method),
            "total_amount": claim.total_amount,
            "formatted_total_amount": f"{claim.total_amount:,}",
            "status": claim.status.value if hasattr(claim.status, "value") else str(claim.status),
            "status_label": status_label,
            "paid_at": claim.paid_at,
        })
    return result


def get_parent_claim_detail(
    session: Session,
    *,
    family_id: int,
    claim_id: int,
) -> Optional[dict[str, Any]]:
    """指定された請求書の園児別・項目別内訳明細を取得する（家族ID認可検証付き）。

    IDOR対策として、family_id が一致しない場合や、ドラフト状態の場合は None を返す。
    """
    if not family_id or not claim_id:
        return None

    claim = session.get(BillingClaim, claim_id)
    if not claim or claim.family_id != family_id:
        return None

    if claim.status in (BillingClaimStatus.draft, BillingClaimStatus.canceled):
        return None

    cycle = session.get(BillingCycle, claim.billing_cycle_id)
    if not cycle or cycle.status == BillingCycleStatus.draft:
        return None

    # 口座プロファイルの取得（マスキング対応）
    profile = session.exec(
        select(FamilyBillingProfile).where(FamilyBillingProfile.family_id == family_id)
    ).first()

    account_info = None
    if profile:
        raw_num = profile.account_number or ""
        masked_num = f"***{raw_num[-4:]}" if len(raw_num) >= 4 else raw_num
        account_info = {
            "payment_method": profile.payment_method.value if hasattr(profile.payment_method, "value") else str(profile.payment_method),
            "bank_name": profile.bank_name_kana or "",
            "branch_name": profile.branch_name_kana or "",
            "account_type": profile.account_type or "普通",
            "account_number_masked": masked_num,
            "account_holder": profile.account_holder_kana or "",
        }

    # 園児情報
    children = session.exec(select(Child).where(Child.family_id == family_id)).all()
    child_map = {c.id: f"{c.last_name} {c.first_name}" for c in children if c.id is not None}

    # 明細行の取得
    lines = session.exec(
        select(BillingChargeLine)
        .where(BillingChargeLine.billing_claim_id == claim.id)
        .order_by(BillingChargeLine.child_id, BillingChargeLine.id)
    ).all()

    # 園児別グルーピング
    child_sections: dict[Optional[int], dict[str, Any]] = {}
    for line in lines:
        c_id = line.child_id
        if c_id not in child_sections:
            child_name = child_map.get(c_id, "家庭共通") if c_id else "家庭共通"
            child_sections[c_id] = {
                "child_id": c_id,
                "child_name": child_name,
                "subtotal": 0,
                "lines": [],
            }
        child_sections[c_id]["subtotal"] += line.amount
        child_sections[c_id]["lines"].append({
            "id": line.id,
            "description": line.description,
            "quantity": line.quantity,
            "unit_label": line.unit_label or "式",
            "unit_price": line.unit_price,
            "amount": line.amount,
            "source_date": line.source_date,
        })

    status_label = CLAIM_STATUS_LABELS.get(claim.status, str(claim.status))

    return {
        "claim_id": claim.id,
        "year_month": cycle.year_month,
        "period_start": cycle.period_start,
        "period_end": cycle.period_end,
        "withdrawal_date": cycle.withdrawal_date,
        "due_date": cycle.due_date,
        "total_amount": claim.total_amount,
        "formatted_total_amount": f"{claim.total_amount:,}",
        "status": claim.status.value if hasattr(claim.status, "value") else str(claim.status),
        "status_label": status_label,
        "paid_at": claim.paid_at,
        "account_info": account_info,
        "child_sections": list(child_sections.values()),
    }
