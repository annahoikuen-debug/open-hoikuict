"""与薬記録サービス（改善案8）。

- 保護者の連絡帳申告（DailyContactEntry.medication）を与薬依頼として受け付ける
- 園が与薬を実施したら実施者を記録し、**別の第2職員が確認**して確定する
- 確定済み（administered）の記録は削除不可。訂正は void（無効化）のみ
- 同一園児・同一日・同一薬・同一時刻の二重与薬を防止する
"""
from __future__ import annotations

import re

from fastapi import HTTPException
from sqlmodel import Session, select

from models import MedicationAdministration
from time_utils import utc_now

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class MedicationServiceError(Exception):
    pass


def load_medications_for_child_date(
    session: Session, child_id: int, target_date,
) -> list[MedicationAdministration]:
    return list(session.exec(
        select(MedicationAdministration)
        .where(
            MedicationAdministration.child_id == child_id,
            MedicationAdministration.target_date == target_date,
            MedicationAdministration.status != "void",
        )
        .order_by(MedicationAdministration.administration_time)
    ).all())


def request_medication(
    session: Session,
    *,
    child_id: int,
    target_date,
    medication_name: str,
    administration_time: str,
    dosage: str | None = None,
    note: str | None = None,
    daily_contact_entry_id: int | None = None,
    parent_account_id: int | None = None,
) -> MedicationAdministration:
    """保護者申告 or 職員入力による与薬依頼の登録。"""
    medication_name = (medication_name or "").strip()
    administration_time = (administration_time or "").strip()
    if not medication_name or len(medication_name) > 100:
        raise HTTPException(400, "薬名を100文字以内で入力してください")
    if not TIME_RE.match(administration_time):
        raise HTTPException(400, "与薬時刻を HH:MM 形式で入力してください")

    # 二重与薬防止: 同じ園児・日付・薬名・時刻の未処理/実施済み依頼があれば拒否
    duplicate = session.exec(
        select(MedicationAdministration).where(
            MedicationAdministration.child_id == child_id,
            MedicationAdministration.target_date == target_date,
            MedicationAdministration.medication_name == medication_name,
            MedicationAdministration.administration_time == administration_time,
            MedicationAdministration.status != "void",
        )
    ).first()
    if duplicate:
        raise HTTPException(409, "同じ日時・薬名の与薬記録が既に存在します")

    record = MedicationAdministration(
        child_id=child_id,
        target_date=target_date,
        medication_name=medication_name,
        dosage=(dosage or "").strip() or None,
        administration_time=administration_time,
        note=(note or "").strip() or None,
        daily_contact_entry_id=daily_contact_entry_id,
        requested_by_parent_account_id=parent_account_id,
        status="requested",
    )
    session.add(record)
    session.flush()
    return record


def administer_medication(
    session: Session,
    *,
    medication_id: int,
    staff_name: str,
    staff_user_id,
) -> MedicationAdministration:
    """与薬を実施した職員が実施を記録する（requested → administered）。"""
    record = session.get(MedicationAdministration, medication_id)
    if record is None:
        raise HTTPException(404, "与薬記録が見つかりません")
    if record.status != "requested":
        raise HTTPException(409, "依頼状態の記録だけ与薬実施できます")

    record.status = "administered"
    record.administered_at = utc_now()
    record.administered_by_name = staff_name
    record.administered_by_user_id = staff_user_id
    record.updated_at = utc_now()
    session.add(record)
    session.flush()
    return record


def confirm_medication(
    session: Session,
    *,
    medication_id: int,
    staff_name: str,
    staff_user_id,
) -> MedicationAdministration:
    """第2職員が与薬を確認する（二重確認）。

    実施者自身による確認は禁止する（薬の安全管理のため）。
    """
    record = session.get(MedicationAdministration, medication_id)
    if record is None:
        raise HTTPException(404, "与薬記録が見つかりません")
    if record.status != "administered":
        raise HTTPException(409, "実施済みの記録だけ確認できます")
    if record.administered_by_user_id and record.administered_by_user_id == staff_user_id:
        raise HTTPException(403, "与薬を実施した職員自身は確認できません。別の職員に確認を依頼してください")

    record.confirmed_by_name = staff_name
    record.confirmed_by_user_id = staff_user_id
    record.confirmed_at = utc_now()
    record.updated_at = utc_now()
    session.add(record)
    session.flush()
    return record


def void_medication(
    session: Session,
    *,
    medication_id: int,
    staff_name: str,
    reason: str,
) -> MedicationAdministration:
    """記録を無効化する（削除ではなく void）。確定後も訂正はこの方法のみ。"""
    reason = (reason or "").strip()
    if not reason:
        raise HTTPException(400, "無効化の理由を入力してください")
    record = session.get(MedicationAdministration, medication_id)
    if record is None:
        raise HTTPException(404, "与薬記録が見つかりません")
    if record.status == "void":
        raise HTTPException(409, "既に無効化されています")

    record.status = "void"
    record.voided_at = utc_now()
    record.voided_by_name = staff_name
    record.void_reason = reason
    record.updated_at = utc_now()
    session.add(record)
    session.flush()
    return record
