from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import update
from sqlmodel import Session, select

from models import (
    BillingChargeLine,
    BillingClaim,
    BillingClaimStatus,
    BillingCycle,
    BillingCycleStatus,
    BillingPaymentMethod,
    BillingSetting,
    DirectDebitStatus,
    FamilyBillingProfile,
    ZenginExport,
    ZenginExportLine,
    ZenginExportStatus,
)
from models.core import Child, Family
from time_utils import utc_now


class ZenginError(ValueError):
    pass


class ZenginFileValidationError(ZenginError):
    def __init__(self, errors: str | list[str]):
        self.errors = [errors] if isinstance(errors, str) else list(errors)
        super().__init__(self.errors[0] if self.errors else "結果ファイルが不正です")


ZENGIN_C_ALLOWED_RE = re.compile(r"^[0-9A-Z \-.()/｡-ﾟ]*$")
DEFAULT_RESULT_CODE_MAP = {
    "0": ("paid", "振替済"),
    "1": ("failed", "資金不足"),
    "2": ("failed", "取引なし"),
    "3": ("failed", "預金者都合による振替停止"),
    "4": ("failed", "依頼書なし"),
    "8": ("failed", "委託者都合による停止"),
    "9": ("failed", "その他"),
}


@dataclass(frozen=True)
class ParsedResultRecord:
    customer_number: str
    amount: int
    result_code: str

    @property
    def status_key(self) -> str:
        return DEFAULT_RESULT_CODE_MAP[self.result_code][0]


@dataclass(frozen=True)
class ParsedResultFile:
    records: list[ParsedResultRecord]
    errors: list[str]
    warnings: list[str]


def format_n(value: str | int | None, length: int) -> str:
    raw = "" if value is None else str(value)
    if not raw.isdigit():
        raise ZenginError("N項目には数字のみ指定できます")
    if len(raw) > length:
        raise ZenginError("N項目の桁数を超過しています")
    return raw.zfill(length)


def validate_zengin_c_chars(raw: str) -> None:
    if not ZENGIN_C_ALLOWED_RE.fullmatch(raw):
        raise ZenginError("C項目に許容されない文字が含まれています")


def format_c(value: str | None, length: int, encoding: str = "cp932") -> str:
    raw = "" if value is None else value
    validate_zengin_c_chars(raw)
    encoded = raw.encode(encoding, errors="strict")
    if len(encoded) > length:
        raise ZenginError("C項目のバイト数を超過しています")
    formatted = raw + " " * (length - len(encoded))
    if len(formatted.encode(encoding, errors="strict")) != length:
        raise ZenginError("C項目の整形後バイト数が不正です")
    return formatted


def validate_record(record: str, encoding: str = "cp932") -> None:
    if len(record.encode(encoding, errors="strict")) != 120:
        raise ZenginError("レコード長が120バイトではありません")


def build_file_bytes(records: list[str], encoding: str, line_separator: str) -> bytes:
    encoded_records = []
    for record in records:
        validate_record(record, encoding)
        encoded_records.append(record.encode(encoding, errors="strict"))

    if line_separator == "CRLF":
        return b"".join(record + b"\r\n" for record in encoded_records)
    if line_separator == "NONE":
        return b"".join(encoded_records)
    raise ZenginError("未対応の改行設定です")


def calculate_content_hash(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def create_customer_number(facility_code: str, family_id: int) -> str:
    if not facility_code.isdigit() or len(facility_code) != 3:
        raise ZenginError("施設コードは3桁数字で指定してください")
    return facility_code + str(family_id).zfill(17)


def _value(source: Any, key: str) -> Any:
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key)


def _settings_snapshot(settings: BillingSetting) -> dict[str, Any]:
    return {
        "facility_name": settings.facility_name,
        "collector_code": settings.collector_code,
        "collector_name_kana": settings.collector_name_kana,
        "withdrawal_bank_code": settings.withdrawal_bank_code,
        "withdrawal_bank_name_kana": settings.withdrawal_bank_name_kana or "",
        "withdrawal_branch_code": settings.withdrawal_branch_code,
        "withdrawal_branch_name_kana": settings.withdrawal_branch_name_kana or "",
        "collector_account_type": settings.collector_account_type,
        "collector_account_type_allowed_values": settings.collector_account_type_allowed_values,
        "collector_account_number": settings.collector_account_number,
        "code_type": settings.code_type,
        "file_encoding": settings.file_encoding,
        "line_separator": settings.line_separator,
    }


def _bank_snapshot(profile: FamilyBillingProfile) -> dict[str, Any]:
    return {
        "bank_code": profile.bank_code,
        "bank_name_kana": profile.bank_name_kana or "",
        "branch_code": profile.branch_code,
        "branch_name_kana": profile.branch_name_kana or "",
        "account_type": profile.account_type,
        "account_number": profile.account_number,
        "account_holder_kana": profile.account_holder_kana,
        "customer_number": profile.customer_number,
        "new_code": profile.new_code,
    }


def validate_billing_setting(settings: BillingSetting) -> None:
    format_n(settings.collector_code, 10)
    format_c(settings.collector_name_kana, 40, settings.file_encoding)
    format_n(settings.withdrawal_bank_code, 4)
    format_n(settings.withdrawal_branch_code, 3)
    allowed = settings.collector_account_type_allowed_values or ["1", "2"]
    if settings.collector_account_type not in allowed:
        raise ZenginError("委託者口座種目が金融機関プロファイルで許可されていません")
    format_n(settings.collector_account_number, 7)
    if settings.file_encoding != "cp932":
        raise ZenginError("未対応の文字コードです")
    if settings.line_separator not in {"CRLF", "NONE"}:
        raise ZenginError("未対応の改行設定です")


def validate_profile_for_zengin(profile: FamilyBillingProfile) -> None:
    if profile.payment_method != BillingPaymentMethod.direct_debit:
        raise ZenginError("支払方法が口座振替ではありません")
    if profile.direct_debit_status != DirectDebitStatus.active:
        raise ZenginError("口座振替状態がactiveではありません")
    format_n(profile.bank_code, 4)
    format_n(profile.branch_code, 3)
    if profile.account_type not in {"1", "2", "3", "9"}:
        raise ZenginError("保護者側の預金種目が不正です")
    format_n(profile.account_number, 7)
    format_c(profile.account_holder_kana, 30)
    format_n(profile.customer_number, 20)
    if profile.new_code not in {"0", "1", "2"}:
        raise ZenginError("新規コードが不正です")


def build_header_record(settings: BillingSetting | dict[str, Any], withdrawal_date: date) -> str:
    encoding = _value(settings, "file_encoding") or "cp932"
    record = (
        "1"
        + format_n("91", 2)
        + format_n(_value(settings, "code_type") or "0", 1)
        + format_n(_value(settings, "collector_code"), 10)
        + format_c(_value(settings, "collector_name_kana"), 40, encoding)
        + withdrawal_date.strftime("%m%d")
        + format_n(_value(settings, "withdrawal_bank_code"), 4)
        + format_c(_value(settings, "withdrawal_bank_name_kana"), 15, encoding)
        + format_n(_value(settings, "withdrawal_branch_code"), 3)
        + format_c(_value(settings, "withdrawal_branch_name_kana"), 15, encoding)
        + format_n(_value(settings, "collector_account_type"), 1)
        + format_n(_value(settings, "collector_account_number"), 7)
        + format_c("", 17, encoding)
    )
    validate_record(record, encoding)
    return record


def build_data_record(line: ZenginExportLine, encoding: str = "cp932") -> str:
    snapshot = line.bank_snapshot
    record = (
        "2"
        + format_n(snapshot.get("bank_code"), 4)
        + format_c(snapshot.get("bank_name_kana"), 15, encoding)
        + format_n(snapshot.get("branch_code"), 3)
        + format_c(snapshot.get("branch_name_kana"), 15, encoding)
        + format_c("", 4, encoding)
        + format_n(snapshot.get("account_type"), 1)
        + format_n(snapshot.get("account_number"), 7)
        + format_c(snapshot.get("account_holder_kana"), 30, encoding)
        + format_n(line.amount, 10)
        + format_n(snapshot.get("new_code"), 1)
        + format_n(snapshot.get("customer_number"), 20)
        + format_n("0", 1)
        + format_c("", 8, encoding)
    )
    validate_record(record, encoding)
    return record


def build_trailer_record(lines: list[ZenginExportLine], encoding: str = "cp932", result_records: list[ParsedResultRecord] | None = None) -> str:
    total_count = len(lines)
    total_amount = sum(line.amount for line in lines)
    paid_count = paid_amount = failed_count = failed_amount = 0
    if result_records is not None:
        total_count = len(result_records)
        total_amount = sum(record.amount for record in result_records)
        paid_count = sum(1 for record in result_records if record.status_key == "paid")
        paid_amount = sum(record.amount for record in result_records if record.status_key == "paid")
        failed_count = sum(1 for record in result_records if record.status_key == "failed")
        failed_amount = sum(record.amount for record in result_records if record.status_key == "failed")

    record = (
        "8"
        + format_n(total_count, 6)
        + format_n(total_amount, 12)
        + format_n(paid_count, 6)
        + format_n(paid_amount, 12)
        + format_n(failed_count, 6)
        + format_n(failed_amount, 12)
        + format_c("", 65, encoding)
    )
    validate_record(record, encoding)
    return record


def build_end_record(encoding: str = "cp932") -> str:
    record = "9" + format_c("", 119, encoding)
    validate_record(record, encoding)
    return record


def _load_export_lines(session: Session, export_id: int) -> list[ZenginExportLine]:
    return session.exec(
        select(ZenginExportLine)
        .where(ZenginExportLine.zengin_export_id == export_id)
        .order_by(ZenginExportLine.id)
    ).all()


def build_zengin_file(session: Session, export_id: int) -> bytes:
    export = session.get(ZenginExport, export_id, populate_existing=True)
    if export is None:
        raise ZenginError("Zengin出力履歴が見つかりません")
    if export.status == ZenginExportStatus.canceled:
        raise ZenginError("取消済みのZengin出力はダウンロードできません")
    encoding = export.settings_snapshot.get("file_encoding", "cp932")
    lines = _load_export_lines(session, export_id)
    records = [build_header_record(export.settings_snapshot, export.withdrawal_date)]
    records.extend(build_data_record(line, encoding) for line in lines)
    records.append(build_trailer_record(lines, encoding))
    records.append(build_end_record(encoding))
    return build_file_bytes(records, encoding, export.settings_snapshot.get("line_separator", "CRLF"))


def lock_billing_cycle(session: Session, cycle_id: int) -> BillingCycle | None:
    """Serialize billing edits and export transitions, including on SQLite.

    A no-op UPDATE takes the database write/row lock until commit or rollback.
    Reload after acquiring it so a preloaded ORM object cannot bypass a lock.
    """
    session.execute(
        update(BillingCycle).where(BillingCycle.id == cycle_id)
        .values(updated_at=BillingCycle.updated_at)
        .execution_options(synchronize_session=False)
    )
    return session.get(BillingCycle, cycle_id, populate_existing=True)


def _lock_export_cycle(session: Session, export_id: int) -> tuple[BillingCycle, ZenginExport]:
    cycle_id = session.exec(select(ZenginExport.billing_cycle_id).where(ZenginExport.id == export_id)).first()
    if cycle_id is None:
        raise ZenginError("Zengin出力履歴が見つかりません")
    cycle = lock_billing_cycle(session, cycle_id)
    if cycle is None:
        raise ZenginError("請求月が見つかりません")
    export = session.get(ZenginExport, export_id, populate_existing=True)
    return cycle, export


def reopenable_export(cycle: BillingCycle, exports: list[ZenginExport]) -> ZenginExport | None:
    """UI eligibility; the mutation rechecks this under the cycle lock."""
    if cycle.status != BillingCycleStatus.exported or not exports:
        return None
    # Superseding a submitted file does not cancel its reception at the bank.
    if any(item.submitted_at is not None or item.result_imported_at is not None for item in exports):
        return None
    latest = max(exports, key=lambda item: item.id or 0)
    active = [item for item in exports if item.status not in {ZenginExportStatus.canceled, ZenginExportStatus.superseded}]
    if (len(active) == 1 and active[0].id == latest.id
            and latest.status == ZenginExportStatus.created
            and latest.submitted_at is None and latest.result_imported_at is None
            and latest.superseded_by_export_id is None):
        return latest
    return None


def cancel_zengin_export_for_edit(
    session: Session, export_id: int, *, reason: str, confirmed_unsubmitted: bool, canceled_by: str,
    approved_by: str | None = None,
) -> ZenginExport:
    """Invalidate an unsubmitted snapshot and reopen its claims, atomically.

    ``approved_by`` is set when a diff-bearing (L1) cancel is executed by the
    director (self-approved skip or approval of a pending request). The stamp
    is kept alongside the cancel audit columns.
    """
    reason = (reason or "").strip()
    if not reason or len(reason) > 500:
        raise ZenginError("取消理由を500文字以内で入力してください")
    if confirmed_unsubmitted is not True:
        raise ZenginError("銀行へ提出・アップロードしていないことを確認してください")
    try:
        cycle, export = _lock_export_cycle(session, export_id)
        exports = list(session.exec(select(ZenginExport).where(
            ZenginExport.billing_cycle_id == cycle.id).execution_options(populate_existing=True)).all())
        candidate = reopenable_export(cycle, exports)
        if candidate is None or candidate.id != export.id:
            raise ZenginError("銀行未提出の最新の作成済み出力だけを取消して修正できます。状態を確認してください")
        lines = _load_export_lines(session, export.id)
        claims = list(session.exec(select(BillingClaim).where(
            BillingClaim.billing_cycle_id == cycle.id).execution_options(populate_existing=True)).all())
        linked = {claim.id: claim for claim in claims if claim.zengin_export_id == export.id}
        if (not lines or set(linked) != {line.billing_claim_id for line in lines}
                or len(lines) != export.total_count or sum(line.amount for line in lines) != export.total_amount):
            raise ZenginError("出力と請求の紐付けが一致しないため、取消できません")
        for line in lines:
            claim = linked[line.billing_claim_id]
            if (claim.status != BillingClaimStatus.exported or claim.paid_at is not None
                    or claim.result_code is not None or line.result_code is not None
                    or claim.family_id != line.family_id or claim.total_amount != line.amount):
                raise ZenginError("請求の状態が出力時と異なるため、取消できません")
        now = utc_now()
        for claim in linked.values():
            claim.status = BillingClaimStatus.confirmed
            claim.zengin_export_id = None
            claim.exported_at = None
            claim.updated_at = now
            session.add(claim)
        export.status = ZenginExportStatus.canceled
        export.canceled_reason = reason
        export.canceled_by = canceled_by
        export.canceled_at = now
        if approved_by:
            export.reopen_confirm_by = approved_by
            export.reopen_confirm_at = now
            if export.reopen_confirm_payload is None:
                export.reopen_confirm_payload = {}
        cycle.status = BillingCycleStatus.confirmed
        cycle.updated_at = now
        session.add(export)
        session.add(cycle)
        session.commit()
        session.refresh(export)
        return export
    except Exception:
        session.rollback()
        raise


REOPEN_REASON_MAX = 500
REOPEN_TEMPLATE_KEYS = ("打刻漏れ", "免除・軽減の変更", "口座変更", "項目誤入力", "その他")


def estimate_reopen_delta(session: Session, export_id: int) -> dict[str, Any]:
    """Dry-run: totals the re-created export would have with current data.

    Classifies the cancel as L0 (no diff, exporter may run it directly) or
    L1 (diff-bearing, director confirmation required). Submission-state
    eligibility is decided by ``reopenable_export``; submitted exports are
    handled by the separate supersede flow (L2).
    """
    export = session.get(ZenginExport, export_id)
    if export is None:
        raise ZenginError("Zengin出力が見つかりません")
    claims = list(session.exec(select(BillingClaim).where(
        BillingClaim.billing_cycle_id == export.billing_cycle_id,
        BillingClaim.zengin_export_id == export.id,
    ).execution_options(populate_existing=True)).all())
    claim_ids = [claim.id for claim in claims if claim.id is not None]
    lines_by_claim: dict[int, list[BillingChargeLine]] = {}
    if claim_ids:
        all_lines = session.exec(select(BillingChargeLine).where(
            BillingChargeLine.billing_claim_id.in_(claim_ids))).all()
        for line in all_lines:
            lines_by_claim.setdefault(line.billing_claim_id, []).append(line)
    estimated_count = 0
    estimated_amount = 0
    changed_claims = 0
    for claim in claims:
        new_total = sum(line.amount for line in lines_by_claim.get(claim.id or 0, []))
        if new_total != claim.total_amount:
            changed_claims += 1
        # Same eligibility as _create_zengin_export_uncommitted.
        if claim.payment_method == BillingPaymentMethod.direct_debit and new_total > 0:
            estimated_count += 1
            estimated_amount += new_total
    delta_amount = estimated_amount - export.total_amount
    delta_count = estimated_count - export.total_count
    level = "L0" if (delta_amount == 0 and delta_count == 0 and changed_claims == 0) else "L1"
    return {
        "level": level,
        "current_amount": export.total_amount,
        "current_count": export.total_count,
        "estimated_amount": estimated_amount,
        "estimated_count": estimated_count,
        "delta_amount": delta_amount,
        "delta_count": delta_count,
        "changed_claims": changed_claims,
    }


def combine_reopen_reason(reason_templates: list[str] | tuple[str, ...] | None, reason_free: str | None) -> str:
    """Join template reasons and free text into the stored audit reason."""
    templates = [t for t in (reason_templates or []) if t in REOPEN_TEMPLATE_KEYS]
    free = (reason_free or "").strip()
    parts = [t for t in REOPEN_TEMPLATE_KEYS if t in templates]
    if free:
        parts.append(free)
    return "、".join(parts)


def _validate_reopen_reason(reason_templates: list[str] | None, reason_free: str | None) -> str:
    free = (reason_free or "").strip()
    if not free and not reason_templates:
        raise ZenginError("取消理由を選択または入力してください")
    if len(free) > REOPEN_REASON_MAX:
        raise ZenginError(f"取消理由は{REOPEN_REASON_MAX}文字以内で入力してください")
    for template in reason_templates or []:
        if template not in REOPEN_TEMPLATE_KEYS:
            raise ZenginError("取消理由の選択が不正です")
    if "その他" in (reason_templates or []) and not free:
        raise ZenginError("「その他」を選んだ場合は補足を入力してください")
    return combine_reopen_reason(reason_templates, free)


def has_pending_reopen_confirm(export: ZenginExport) -> bool:
    return bool(export.reopen_confirm_requested_by) and export.reopen_confirm_at is None


def request_reopen_confirm(
    session: Session,
    export_id: int,
    *,
    reason: str,
    reason_templates: list[str] | None,
    confirmed_unsubmitted: bool,
    requested_by: str,
    estimate: dict[str, Any],
) -> ZenginExport:
    """Store a director-confirmation request for a diff-bearing (L1) cancel."""
    if confirmed_unsubmitted is not True:
        raise ZenginError("銀行へ提出・アップロードしていないことを確認してください")
    _validate_reopen_reason(reason_templates, reason)
    try:
        cycle, export = _lock_export_cycle(session, export_id)
        exports = list(session.exec(select(ZenginExport).where(
            ZenginExport.billing_cycle_id == cycle.id).execution_options(populate_existing=True)).all())
        candidate = reopenable_export(cycle, exports)
        if candidate is None or candidate.id != export.id:
            raise ZenginError("銀行未提出の最新の作成済み出力だけを取消して修正できます。状態を確認してください")
        now = utc_now()
        export.reopen_confirm_requested_by = requested_by
        export.reopen_confirm_requested_at = now
        export.reopen_confirm_payload = {
            "reason_templates": list(reason_templates or []),
            "reason_free": (reason or "").strip(),
            "estimated_amount": estimate.get("estimated_amount", 0),
            "estimated_count": estimate.get("estimated_count", 0),
            "delta_amount": estimate.get("delta_amount", 0),
        }
        session.add(export)
        session.commit()
        session.refresh(export)
        return export
    except Exception:
        session.rollback()
        raise


def withdraw_reopen_request(session: Session, export_id: int) -> ZenginExport:
    """Clear a pending director-confirmation request (requester or admin)."""
    try:
        cycle, export = _lock_export_cycle(session, export_id)
        if not has_pending_reopen_confirm(export):
            raise ZenginError("確認待ちの申請がありません")
        export.reopen_confirm_requested_by = None
        export.reopen_confirm_requested_at = None
        export.reopen_confirm_payload = None
        session.add(export)
        session.commit()
        session.refresh(export)
        return export
    except Exception:
        session.rollback()
        raise


def approve_reopen_and_cancel(
    session: Session,
    export_id: int,
    *,
    approved_by: str,
    confirmed_unsubmitted: bool,
) -> ZenginExport:
    """Director approval of a pending request: run the cancel with the
    requested reason and stamp the approval columns."""
    export = session.get(ZenginExport, export_id)
    if export is None:
        raise ZenginError("Zengin出力が見つかりません")
    if not has_pending_reopen_confirm(export):
        raise ZenginError("確認待ちの申請がありません")
    payload = export.reopen_confirm_payload or {}
    reason = combine_reopen_reason(payload.get("reason_templates"), payload.get("reason_free"))
    if not reason:
        reason = (payload.get("reason_free") or "").strip() or "園長承認により取消"
    return cancel_zengin_export_for_edit(
        session,
        export_id,
        reason=reason,
        confirmed_unsubmitted=confirmed_unsubmitted,
        canceled_by=export.reopen_confirm_requested_by or approved_by,
        approved_by=approved_by,
    )


def _create_zengin_export_uncommitted(
    session: Session,
    cycle_id: int,
    *,
    created_by: str = "system",
) -> ZenginExport:
    cycle = lock_billing_cycle(session, cycle_id)
    if cycle is None:
        raise ZenginError("請求月が見つかりません")
    if cycle.status != BillingCycleStatus.confirmed:
        raise ZenginError("Zengin出力はconfirmed状態の請求月のみ可能です")

    settings = session.exec(select(BillingSetting).order_by(BillingSetting.id)).first()
    if settings is None:
        raise ZenginError("請求設定が未登録です")
    validate_billing_setting(settings)

    claims = session.exec(
        select(BillingClaim)
        .where(BillingClaim.billing_cycle_id == cycle_id)
        .where(BillingClaim.status == BillingClaimStatus.confirmed)
        .where(BillingClaim.payment_method == BillingPaymentMethod.direct_debit)
        .where(BillingClaim.total_amount > 0)
        .order_by(BillingClaim.id)
    ).all()
    if not claims:
        raise ZenginError("Zengin出力対象の請求がありません")

    family_ids = [claim.family_id for claim in claims if claim.family_id is not None]
    profiles_by_family: dict[int, FamilyBillingProfile] = {}
    if family_ids:
        all_profiles = session.exec(
            select(FamilyBillingProfile).where(FamilyBillingProfile.family_id.in_(family_ids))
        ).all()
        for profile in all_profiles:
            if profile.family_id is not None:
                profiles_by_family[profile.family_id] = profile

    export = ZenginExport(
        billing_cycle_id=cycle.id,
        withdrawal_date=cycle.withdrawal_date,
        file_name=f"zengin_{cycle.year_month.replace('-', '')}.txt",
        total_count=0,
        total_amount=0,
        status=ZenginExportStatus.created,
        content_hash="pending",
        settings_snapshot=_settings_snapshot(settings),
        created_by=created_by,
    )
    session.add(export)
    session.flush()

    for claim in claims:
        profile = profiles_by_family.get(claim.family_id) if claim.family_id is not None else None
        if profile is None:
            raise ZenginError(f"家族ID {claim.family_id} の口座振替情報が未登録です")
        validate_profile_for_zengin(profile)
        line = ZenginExportLine(
            zengin_export_id=export.id,
            billing_claim_id=claim.id,
            family_id=claim.family_id,
            customer_number=profile.customer_number,
            amount=claim.total_amount,
            bank_snapshot=_bank_snapshot(profile),
        )
        session.add(line)
        claim.status = BillingClaimStatus.exported
        claim.zengin_export_id = export.id
        claim.exported_at = utc_now()

    session.flush()
    lines = _load_export_lines(session, export.id)
    export.total_count = len(lines)
    export.total_amount = sum(line.amount for line in lines)
    file_bytes = build_zengin_file(session, export.id)
    export.content_hash = calculate_content_hash(file_bytes)
    cycle.status = BillingCycleStatus.exported
    cycle.updated_at = utc_now()
    session.add(cycle)
    session.add(export)
    session.flush()
    return export


def create_zengin_export(session: Session, cycle_id: int, *, created_by: str = "system") -> ZenginExport:
    try:
        export = _create_zengin_export_uncommitted(
            session,
            cycle_id,
            created_by=created_by,
        )
        session.commit()
        session.refresh(export)
        return export
    except Exception:
        session.rollback()
        raise


def mark_zengin_export_submitted(session: Session, export_id: int) -> ZenginExport:
    try:
        _, export = _lock_export_cycle(session, export_id)
        if export.status == ZenginExportStatus.submitted:
            session.commit()
            return export
        if export.status != ZenginExportStatus.created:
            raise ZenginError("このZengin出力は銀行提出済みに変更できません")
        export.status = ZenginExportStatus.submitted
        export.submitted_at = utc_now()
        lines = _load_export_lines(session, export_id)
        for line in lines:
            profile = session.exec(
                select(FamilyBillingProfile).where(FamilyBillingProfile.family_id == line.family_id)
            ).first()
            if profile and profile.new_code in {"1", "2"}:
                profile.new_code = "0"
                profile.new_code_consumed_by_export_id = export.id
                profile.updated_at = utc_now()
                session.add(profile)
        session.add(export)
        session.commit()
        session.refresh(export)
        return export
    except Exception:
        session.rollback()
        raise


def supersede_zengin_export(
    session: Session,
    export_id: int,
    *,
    reason: str,
    created_by: str,
) -> ZenginExport:
    normalized_reason = (reason or "").strip()
    if not normalized_reason:
        raise ZenginError("差し替え理由を入力してください")
    try:
        _, original = _lock_export_cycle(session, export_id)
        if original.status not in {ZenginExportStatus.created, ZenginExportStatus.submitted}:
            raise ZenginError("このZengin出力は差し替えできません")
        if original.result_imported_at is not None:
            raise ZenginError("結果取込済みのZengin出力は差し替えできません")
        lines = _load_export_lines(session, export_id)
        for line in lines:
            claim = session.get(BillingClaim, line.billing_claim_id)
            if claim is not None:
                claim.status = BillingClaimStatus.confirmed
                claim.zengin_export_id = None
                claim.exported_at = None
                claim.updated_at = utc_now()
                session.add(claim)

            profile = session.exec(
                select(FamilyBillingProfile).where(
                    FamilyBillingProfile.family_id == line.family_id
                )
            ).first()
            snapshot_code = str((line.bank_snapshot or {}).get("new_code") or "")
            if (
                profile is not None
                and profile.new_code == "0"
                and profile.new_code_consumed_by_export_id == original.id
                and snapshot_code in {"1", "2"}
            ):
                profile.new_code = snapshot_code
                profile.new_code_consumed_by_export_id = None
                profile.updated_at = utc_now()
                session.add(profile)

        cycle = session.get(BillingCycle, original.billing_cycle_id)
        if cycle is None:
            raise ZenginError("請求月が見つかりません")
        cycle.status = BillingCycleStatus.confirmed
        cycle.updated_at = utc_now()
        session.add(cycle)
        session.flush()

        replacement = _create_zengin_export_uncommitted(
            session,
            cycle.id,
            created_by=created_by,
        )
        original.status = ZenginExportStatus.superseded
        original.superseded_by_export_id = replacement.id
        original.reissue_reason = normalized_reason
        session.add(original)
        session.commit()
        session.refresh(replacement)
        return replacement
    except Exception:
        session.rollback()
        raise


def _normalize_result_records(file_bytes: bytes) -> list[bytes]:
    if b"\r\n" in file_bytes:
        parts = file_bytes.split(b"\r\n")
        if parts and parts[-1] == b"":
            parts = parts[:-1]
        if any((b"\r" in part or b"\n" in part) for part in parts):
            raise ZenginError("不正な改行が含まれています")
        if any(len(part) != 120 for part in parts):
            raise ZenginError("CRLF除去後のレコード長が120バイトではありません")
        return parts

    if b"\r" in file_bytes or b"\n" in file_bytes:
        raise ZenginError("CRのみ、LFのみの結果ファイルは不正です")
    if len(file_bytes) % 120 != 0:
        raise ZenginError("結果ファイル長が120バイトの倍数ではありません")
    return [file_bytes[index : index + 120] for index in range(0, len(file_bytes), 120)]


def _parse_data_result_record(record: str) -> ParsedResultRecord:
    if record[0] != "2":
        raise ZenginError("データレコードではありません")
    result_code = record[111:112]
    if result_code not in DEFAULT_RESULT_CODE_MAP:
        raise ZenginError(f"未知の結果コードです: {result_code}")
    try:
        amount = int(record[80:90])
    except ValueError as exc:
        raise ZenginFileValidationError("データレコードの引落金額が数値ではありません") from exc
    return ParsedResultRecord(
        customer_number=record[91:111],
        amount=amount,
        result_code=result_code,
    )


def _parse_trailer(record: str) -> dict[str, int]:
    if record[0] != "8":
        raise ZenginError("トレーラーレコードではありません")
    try:
        return {
            "total_count": int(record[1:7]),
            "total_amount": int(record[7:19]),
            "paid_count": int(record[19:25]),
            "paid_amount": int(record[25:37]),
            "failed_count": int(record[37:43]),
            "failed_amount": int(record[43:55]),
        }
    except ValueError as exc:
        raise ZenginFileValidationError("トレーラーレコードの数値項目が不正です") from exc


def validate_result_trailer(result_records: list[ParsedResultRecord], trailer: dict[str, int], export: ZenginExport) -> list[str]:
    errors = []
    paid = [record for record in result_records if record.status_key == "paid"]
    failed = [record for record in result_records if record.status_key == "failed"]
    checks = {
        "total_count": len(result_records),
        "total_amount": sum(record.amount for record in result_records),
        "paid_count": len(paid),
        "paid_amount": sum(record.amount for record in paid),
        "failed_count": len(failed),
        "failed_amount": sum(record.amount for record in failed),
    }
    for key, expected in checks.items():
        if trailer[key] != expected:
            errors.append(f"トレーラー{key}がデータレコード集計と一致しません")
    if export.total_count != checks["total_count"]:
        errors.append("結果ファイルのデータ件数が出力明細件数と一致しません")
    if export.total_amount != checks["total_amount"]:
        errors.append("結果ファイルの合計金額が出力合計金額と一致しません")
    return errors


def parse_result_file(session: Session, file_bytes: bytes, export_id: int) -> ParsedResultFile:
    export = session.get(ZenginExport, export_id)
    if export is None:
        raise ZenginError("Zengin出力履歴が見つかりません")
    if export.status != ZenginExportStatus.submitted:
        raise ZenginError("このZengin出力は結果取込対象ではありません")
    if export.superseded_by_export_id is not None or export.result_imported_at is not None:
        raise ZenginError("このZengin出力は結果取込対象ではありません")

    encoding = export.settings_snapshot.get("file_encoding", "cp932")
    try:
        normalized_records = _normalize_result_records(file_bytes)
        records = [record.decode(encoding, errors="strict") for record in normalized_records]
    except UnicodeDecodeError as exc:
        raise ZenginFileValidationError(
            f"結果ファイルの文字コードが設定（{encoding}）と一致しません"
        ) from exc
    except ZenginError as exc:
        raise ZenginFileValidationError(str(exc)) from exc
    try:
        for record in records:
            validate_record(record, encoding)
    except ZenginError as exc:
        raise ZenginFileValidationError(str(exc)) from exc

    errors: list[str] = []
    warnings: list[str] = []
    if len(records) < 4 or records[0][0] != "1" or records[-2][0] != "8" or records[-1][0] != "9":
        errors.append("レコード構成が不正です")
        return ParsedResultFile([], errors, warnings)

    header = records[0]
    snapshot = export.settings_snapshot
    if header[4:14] != snapshot.get("collector_code"):
        errors.append("ヘッダーの委託者コードが一致しません")
    if header[54:58] != export.withdrawal_date.strftime("%m%d"):
        errors.append("ヘッダーの引落日が一致しません")
    if header[58:62] != snapshot.get("withdrawal_bank_code"):
        errors.append("ヘッダーの取引銀行番号が一致しません")
    if header[77:80] != snapshot.get("withdrawal_branch_code"):
        errors.append("ヘッダーの取引支店番号が一致しません")

    data_records: list[ParsedResultRecord] = []
    seen_customer_numbers: set[str] = set()
    for record in records[1:-2]:
        try:
            parsed = _parse_data_result_record(record)
        except ZenginError as exc:
            errors.append(str(exc))
            continue
        if parsed.customer_number in seen_customer_numbers:
            errors.append("同一結果ファイル内に重複した顧客番号があります")
        seen_customer_numbers.add(parsed.customer_number)
        data_records.append(parsed)

    trailer = _parse_trailer(records[-2])
    errors.extend(validate_result_trailer(data_records, trailer, export))

    lines_by_customer = {line.customer_number: line for line in _load_export_lines(session, export_id)}
    for parsed in data_records:
        line = lines_by_customer.get(parsed.customer_number)
        if line is None:
            errors.append(f"顧客番号が出力明細に存在しません: {parsed.customer_number}")
            continue
        if line.amount != parsed.amount:
            errors.append(f"引落金額が一致しません: {parsed.customer_number}")

    return ParsedResultFile(data_records, errors, warnings)


def import_result_file(session: Session, file_bytes: bytes, export_id: int) -> ParsedResultFile:
    _lock_export_cycle(session, export_id)
    parsed = parse_result_file(session, file_bytes, export_id)
    if parsed.errors:
        session.rollback()
        return parsed

    export = session.get(ZenginExport, export_id)
    lines_by_customer = {line.customer_number: line for line in _load_export_lines(session, export_id)}
    for record in parsed.records:
        line = lines_by_customer[record.customer_number]
        claim = session.get(BillingClaim, line.billing_claim_id)
        if claim is None or claim.status == BillingClaimStatus.paid:
            continue
        line.result_code = record.result_code
        claim.result_code = record.result_code
        if record.status_key == "paid":
            claim.status = BillingClaimStatus.paid
            claim.paid_at = utc_now()
        else:
            claim.status = BillingClaimStatus.failed
            claim.failed_reason = DEFAULT_RESULT_CODE_MAP[record.result_code][1]
        claim.updated_at = utc_now()
        session.add(line)
        session.add(claim)

    export.result_imported_at = utc_now()
    export.status = ZenginExportStatus.result_imported
    for line in _load_export_lines(session, export_id):
        profile = session.exec(
            select(FamilyBillingProfile).where(
                FamilyBillingProfile.family_id == line.family_id
            )
        ).first()
        if profile and profile.new_code_consumed_by_export_id == export.id:
            profile.new_code_consumed_by_export_id = None
            profile.updated_at = utc_now()
            session.add(profile)
    cycle = session.get(BillingCycle, export.billing_cycle_id)
    if cycle is not None:
        cycle.status = BillingCycleStatus.result_imported
        cycle.updated_at = utc_now()
        session.add(cycle)
    session.add(export)
    session.commit()
    return parsed


def generate_zengin_validation_report(
    session: Session, export_id: int
) -> tuple[list[list[str]], list[str]]:
    """Zengin結果取込検証レポートの行データとエラーメッセージを返す。"""
    export = session.get(ZenginExport, export_id)
    if export is None:
        raise ZenginError("Zengin出力履歴が見つかりません")

    headers = [
        "出力ID",
        "顧客番号",
        "明細金額",
        "結果コード",
        "ステータス",
        "検証エラー",
    ]
    rows: list[list[str]] = [headers]

    lines = _load_export_lines(session, export_id)
    _ = {line.customer_number: line for line in lines}

    errors: list[str] = []

    # 結果取込済みの場合のみ、結果コードを照らし合わせる
    if export.status == ZenginExportStatus.result_imported:
        # ここでは簡易的に、各ラインの結果コードをレポートに反映
        pass

    for line in lines:
        claim = session.get(BillingClaim, line.billing_claim_id) if line.billing_claim_id else None
        row = [
            str(export.id),
            line.customer_number,
            str(line.amount),
            line.result_code or "",
            (claim.status.value if claim else "不明"),
            "",
        ]
        if line.result_code and claim and claim.status == BillingClaimStatus.failed:
            row[5] = f"振替失敗: {claim.failed_reason or ''}"
            errors.append(f"{line.customer_number}: 振替失敗")
        rows.append(row)

    return rows, errors


def scan_zengin_preflight(session: Session, cycle_id: int) -> dict[str, Any]:
    """Zengin振替データ作成前の整合性を事前スキャンし、不備一覧とサマリーを返す。

    1件のエラーで中断せず、全請求対象・口座プロファイルを網羅的に検証して
    具体的な修正手順と直行リンクを提供する。
    """
    cycle = session.get(BillingCycle, cycle_id)
    if cycle is None:
        raise ZenginError("請求月が見つかりません")

    settings_errors: list[str] = []
    issues: list[dict[str, Any]] = []

    if cycle.status != BillingCycleStatus.confirmed:
        settings_errors.append(f"請求月が確定状態（confirmed）ではありません（現在の状態: {cycle.status.value}）")

    settings = session.exec(select(BillingSetting).order_by(BillingSetting.id)).first()
    if settings is None:
        settings_errors.append("園の請求・口座振替設定が未登録です")
    else:
        try:
            validate_billing_setting(settings)
        except ZenginError as exc:
            settings_errors.append(f"請求設定の不備: {exc}")

    # 未転送の確定済み延長保育料の検知 (案5)
    try:
        from models.core import ExtendedCareCharge, ExtendedCareChargeStatus
        from sqlalchemy import func
        untransferred_count = session.exec(
            select(func.count(ExtendedCareCharge.id)).where(
                ExtendedCareCharge.is_transferred == False,
                ExtendedCareCharge.status == ExtendedCareChargeStatus.confirmed,
            )
        ).one()
        if untransferred_count > 0:
            issues.append({
                "type": "warning",
                "category": "extended_care",
                "message": f"未転送の確定済み延長保育料が {untransferred_count} 件あります。請求へ転送してから振替データを作成してください。",
                "action_url": "/extended-care-fees/",
            })
    except Exception:
        pass

    claims = session.exec(
        select(BillingClaim)
        .where(BillingClaim.billing_cycle_id == cycle_id)
        .where(BillingClaim.status == BillingClaimStatus.confirmed)
        .where(BillingClaim.payment_method == BillingPaymentMethod.direct_debit)
        .where(BillingClaim.total_amount > 0)
        .order_by(BillingClaim.id)
    ).all()

    total_amount = sum(claim.total_amount for claim in claims)
    family_ids = [claim.family_id for claim in claims if claim.family_id is not None]

    profiles_by_family: dict[int, FamilyBillingProfile] = {}
    if family_ids:
        all_profiles = session.exec(
            select(FamilyBillingProfile).where(FamilyBillingProfile.family_id.in_(family_ids))
        ).all()
        for p in all_profiles:
            if p.family_id is not None:
                profiles_by_family[p.family_id] = p

    # 家族・園児マッピングを事前取得
    families_by_id: dict[int, Family] = {}
    children_by_family: dict[int, list[str]] = {}
    if family_ids:
        f_list = session.exec(select(Family).where(Family.id.in_(family_ids))).all()
        for f in f_list:
            if f.id is not None:
                families_by_id[f.id] = f

        c_list = session.exec(select(Child).where(Child.family_id.in_(family_ids))).all()
        for c in c_list:
            if c.family_id is not None:
                children_by_family.setdefault(c.family_id, []).append(c.full_name)

    for claim in claims:
        fid = claim.family_id
        if fid is None:
            continue

        family = families_by_id.get(fid)
        family_name = family.family_name if family and family.family_name else f"家族ID {fid}"
        children = children_by_family.get(fid, [])
        fix_url = f"/billing/accounts?family_id={fid}#family-{fid}"

        profile = profiles_by_family.get(fid)
        if profile is None:
            issues.append(
                {
                    "family_id": fid,
                    "family_name": family_name,
                    "children_names": children,
                    "issue_type": "missing_profile",
                    "severity": "danger",
                    "message": "口座振替情報が未登録です。銀行・支店・口座番号を登録してください。",
                    "fix_url": fix_url,
                }
            )
            continue

        # 各項目の具体的チェック
        if profile.payment_method != BillingPaymentMethod.direct_debit:
            issues.append(
                {
                    "family_id": fid,
                    "family_name": family_name,
                    "children_names": children,
                    "issue_type": "invalid_payment_method",
                    "severity": "danger",
                    "message": "支払方法が口座振替に設定されていません。",
                    "fix_url": fix_url,
                }
            )

        if profile.direct_debit_status != DirectDebitStatus.active:
            status_val = profile.direct_debit_status.value if profile.direct_debit_status else "未設定"
            issues.append(
                {
                    "family_id": fid,
                    "family_name": family_name,
                    "children_names": children,
                    "issue_type": "inactive_status",
                    "severity": "danger",
                    "message": f"口座振替状態が有効（active）ではありません（現在: {status_val}）。金融機関の承認状態を確認し、有効に変更してください。",
                    "fix_url": fix_url,
                }
            )

        # 銀行コード
        try:
            format_n(profile.bank_code, 4)
        except Exception:
            issues.append(
                {
                    "family_id": fid,
                    "family_name": family_name,
                    "children_names": children,
                    "issue_type": "invalid_bank_code",
                    "severity": "danger",
                    "message": f"金融機関コードが不正です（4桁の半角数字が必要です。現在: {profile.bank_code or '未入力'}）。",
                    "fix_url": fix_url,
                }
            )

        # 支店コード
        try:
            format_n(profile.branch_code, 3)
        except Exception:
            issues.append(
                {
                    "family_id": fid,
                    "family_name": family_name,
                    "children_names": children,
                    "issue_type": "invalid_branch_code",
                    "severity": "danger",
                    "message": f"支店コードが不正です（3桁の半角数字が必要です。現在: {profile.branch_code or '未入力'}）。",
                    "fix_url": fix_url,
                }
            )

        # 預金種目
        if profile.account_type not in {"1", "2", "3", "9"}:
            issues.append(
                {
                    "family_id": fid,
                    "family_name": family_name,
                    "children_names": children,
                    "issue_type": "invalid_account_type",
                    "severity": "danger",
                    "message": f"預金種目が不正です（1:普通, 2:当座, 3:納税準備, 9:その他。現在: {profile.account_type or '未選択'}）。",
                    "fix_url": fix_url,
                }
            )

        # 口座番号
        try:
            format_n(profile.account_number, 7)
        except Exception:
            issues.append(
                {
                    "family_id": fid,
                    "family_name": family_name,
                    "children_names": children,
                    "issue_type": "invalid_account_number",
                    "severity": "danger",
                    "message": f"口座番号が不正です（7桁の半角数字が必要です。現在: {profile.account_number or '未入力'}）。",
                    "fix_url": fix_url,
                }
            )

        # 名義人カナ
        try:
            format_c(profile.account_holder_kana, 30)
        except Exception as exc:
            issues.append(
                {
                    "family_id": fid,
                    "family_name": family_name,
                    "children_names": children,
                    "issue_type": "invalid_holder_kana",
                    "severity": "danger",
                    "message": f"名義人カナが不正です（半角カタカナ・英数字・記号のみ、30文字以内。エラー: {exc}）。",
                    "fix_url": fix_url,
                }
            )

        # 顧客番号
        try:
            format_n(profile.customer_number, 20)
        except Exception:
            issues.append(
                {
                    "family_id": fid,
                    "family_name": family_name,
                    "children_names": children,
                    "issue_type": "invalid_customer_number",
                    "severity": "danger",
                    "message": f"顧客番号が不正です（20桁以内の半角数字が必要です。現在: {profile.customer_number or '未設定'}）。",
                    "fix_url": fix_url,
                }
            )

    can_export = len(settings_errors) == 0 and len(issues) == 0 and len(claims) > 0

    return {
        "cycle_id": cycle.id,
        "year_month": cycle.year_month,
        "withdrawal_date": str(cycle.withdrawal_date) if cycle.withdrawal_date else None,
        "total_claims_count": len(claims),
        "total_claims_amount": total_amount,
        "can_export": can_export,
        "settings_errors": settings_errors,
        "issues": issues,
    }

