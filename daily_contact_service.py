"""連絡帳サービス（日次連絡のコピーおよび一括連絡処理）。"""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from home_care_details import validate_home_care
from models import (
    AttendanceRecord,
    Child,
    ChildStatus,
    DailyContactEntry,
    DailyContactEntryStatus,
    ParentAccount,
    ParentContactType,
)
from pickup_plan_service import load_pickup_record, pickup_revision, save_pickup_plan
from time_utils import local_today, utc_now

PRESENT_TEMPERATURE_LIMIT = Decimal("37.5")
PRESENT_TEMPERATURE_ERROR = "37.5℃以上は出席として登録できません。病欠を選択してください。"
TEMPERATURE_FORMAT_ERROR = "体温は 36.5 の形式で入力してください。"


def validate_temperature_value(raw: str, *, check_limit: bool = True) -> str:
    """体温の文字列を正規化し、形式および上限（37.5℃）を検証する。エラー時はメッセージを返す。"""
    normalized = unicodedata.normalize("NFKC", raw or "").strip()
    if not normalized:
        return ""
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(?:°[cC]|[cC]|度)?", normalized)
    if match is None:
        return TEMPERATURE_FORMAT_ERROR
    if check_limit and Decimal(match.group(1)) >= PRESENT_TEMPERATURE_LIMIT:
        return PRESENT_TEMPERATURE_ERROR
    return ""


def load_latest_previous_contact(
    session: Session,
    *,
    child_id: int,
    before_date: date,
) -> Optional[DailyContactEntry]:
    """指定日より前の直近の提出済み連絡帳レコードを取得する。"""
    return session.exec(
        select(DailyContactEntry)
        .where(
            DailyContactEntry.child_id == child_id,
            DailyContactEntry.target_date < before_date,
            DailyContactEntry.status == DailyContactEntryStatus.submitted,
        )
        .order_by(DailyContactEntry.target_date.desc())
    ).first()


def extract_copyable_fields(
    entry: Optional[DailyContactEntry],
    pickup_record: Optional[AttendanceRecord] = None,
) -> dict[str, str]:
    """連絡帳レコードおよびお迎え記録から安全に再利用可能なフィールドのみを抽出する。

    体温、症状、日々のメモ等の可変・健康リスク情報は空欄としてクリアする。
    """
    if not entry and not pickup_record:
        return {key: "" for key in [
            "bedtime", "wakeup_time", "breakfast_contents", "stool_consistency", "stool_count",
            "breakfast_status", "mood", "sleep_notes", "temperature", "cough", "runny_nose",
            "medication", "condition_note", "contact_note", "absence_temperature",
            "absence_symptoms", "absence_diagnosis", "absence_note", "planned_pickup_time",
            "pickup_person", "snack_required",
        ]}

    extra = entry.extra_data if entry and entry.extra_data else {}

    result = {
        # 生活リズム・定常情報（安全にコピー可能）
        "bedtime": str(extra.get("bedtime") or ""),
        "wakeup_time": str(extra.get("wakeup_time") or ""),
        "breakfast_status": str(entry.breakfast_status or "") if entry else "",
        "breakfast_contents": str(extra.get("breakfast_contents") or ""),
        "mood": str(entry.mood or "") if entry else "",
        "stool_consistency": str(extra.get("stool_consistency") or ""),
        "stool_count": str(extra.get("stool_count") or ""),
        "sleep_notes": str(entry.sleep_notes or "") if entry else "",

        # 安全のため常に空欄とする項目（日々の検温・症状・一時的連絡）
        "temperature": "",
        "bowel_movement_status": "",
        "cough": "",
        "runny_nose": "",
        "medication": "",
        "condition_note": "",
        "contact_note": "",
        "absence_temperature": "",
        "absence_symptoms": "",
        "absence_diagnosis": "",
        "absence_note": "",

        # お迎え予定
        "planned_pickup_time": str(pickup_record.planned_pickup_time or "") if pickup_record else "",
        "pickup_person": str(pickup_record.pickup_person or "") if pickup_record else "",
        "snack_required": ("1" if pickup_record.snack_required else "0") if pickup_record and pickup_record.pickup_snack_confirmed else "",
    }
    return result


def save_bulk_parent_contacts(
    session: Session,
    *,
    current_parent_user: ParentAccount,
    target_date: date,
    common_data: dict[str, Any],
    children_data: list[dict[str, Any]],
) -> list[DailyContactEntry]:
    """兄弟姉妹の連絡帳およびお迎え予定をアトミックに検証・保存する。

    いずれかの園児で検証エラーが発生した場合は ValueError または HTTPException を送出し、
    一切の変更をコミットしない。
    """
    if not children_data:
        raise ValueError("保存対象の園児が選択されていません。")

    # 1. 認可検証: 保護者に紐づく園児であることを確認
    accessible_child_ids = set()
    for link in current_parent_user.child_links or []:
        if link.child and link.child.id:
            accessible_child_ids.add(link.child.id)
    if not accessible_child_ids and current_parent_user.family and current_parent_user.family.children:
        accessible_child_ids = {c.id for c in current_parent_user.family.children if c.id}

    target_child_ids = [c["child_id"] for c in children_data]
    for cid in target_child_ids:
        if cid not in accessible_child_ids:
            raise HTTPException(status_code=403, detail=f"園児ID {cid} へのアクセス権限がありません。")

    all_target_ids = list(target_child_ids)

    # 共通データのお迎え予定パラメータ
    planned_pickup_time = str(common_data.get("planned_pickup_time") or "").strip()
    pickup_person = str(common_data.get("pickup_person") or "").strip()
    snack_required = str(common_data.get("snack_required") or "").strip()
    common_breakfast_contents = str(common_data.get("breakfast_contents") or "").strip()
    common_contact_note = str(common_data.get("contact_note") or "").strip()

    # Pass 1: 事前検証（すべての園児データをまずチェックし、問題があればDB変更前に即座に例外を発生させる）
    validated_specs = []
    for cdata in children_data:
        cid = cdata["child_id"]
        child = session.get(Child, cid)
        if not child:
            raise ValueError(f"園児 (ID: {cid}) が見つかりません。")

        mode = cdata.get("attendance_mode", "present")
        absence_reason = cdata.get("absence_reason", "")
        temp = str(cdata.get("temperature") or "").strip()
        absence_temp = str(cdata.get("absence_temperature") or "").strip()

        if mode == "present":
            contact_type = ParentContactType.present
            if temp:
                err = validate_temperature_value(temp, check_limit=True)
                if err:
                    raise ValueError(f"{child.full_name}: {err}")
        elif mode == "absent":
            if absence_reason == "absent_sick":
                contact_type = ParentContactType.absent_sick
                if absence_temp:
                    err = validate_temperature_value(absence_temp, check_limit=False)
                    if err:
                        raise ValueError(f"{child.full_name}: {err}")
                if not str(cdata.get("absence_symptoms") or "").strip():
                    raise ValueError(f"{child.full_name}: 病欠の場合は症状を入力してください。")
            elif absence_reason == "absent_private":
                contact_type = ParentContactType.absent_private
            else:
                contact_type = ParentContactType.absent_private
        else:
            raise ValueError(f"{child.full_name}: 出席または欠席を選択してください。")

        # 構造化ケア情報
        care_payload = {
            "bedtime": cdata.get("bedtime", ""),
            "wakeup_time": cdata.get("wakeup_time", ""),
            "breakfast_contents": cdata.get("breakfast_contents") or common_breakfast_contents,
            "stool_consistency": cdata.get("stool_consistency", ""),
            "stool_count": cdata.get("stool_count", ""),
        }
        care_values = validate_home_care(care_payload)

        validated_specs.append({
            "child": child,
            "cid": cid,
            "mode": mode,
            "contact_type": contact_type,
            "temp": temp,
            "absence_temp": absence_temp,
            "care_values": care_values,
            "cdata": cdata,
        })

    # Pass 2: DBへの作成・更新
    saved_entries: list[DailyContactEntry] = []
    now = utc_now()
    try:
        for spec in validated_specs:
            child = spec["child"]
            cid = spec["cid"]
            mode = spec["mode"]
            contact_type = spec["contact_type"]
            temp = spec["temp"]
            absence_temp = spec["absence_temp"]
            care_values = spec["care_values"]
            cdata = spec["cdata"]

            # お迎え予定の保存（出席時かつ登録可能日）
            if mode == "present" and target_date >= local_today() and child.status == ChildStatus.enrolled:
                pickup_rec = load_pickup_record(session, cid, target_date)
                if not (pickup_rec and pickup_rec.check_out_at):
                    rev = pickup_revision(pickup_rec)
                    save_pickup_plan(
                        session,
                        child_id=cid,
                        day=target_date,
                        revision=rev,
                        planned_pickup_time=planned_pickup_time,
                        pickup_person=pickup_person,
                        snack_required=snack_required == "1" if snack_required in {"0", "1"} else None,
                        snack_confirmed=snack_required != "",
                        allow_partial=True,
                        actor_name=current_parent_user.display_name,
                        parent_account_id=current_parent_user.id,
                        source="parent_portal_bulk",
                    )

            # 既存エントリーの確認
            entry = session.exec(
                select(DailyContactEntry).where(
                    DailyContactEntry.child_id == cid,
                    DailyContactEntry.target_date == target_date,
                )
            ).first()

            extra_data = {
                **care_values,
                "bulk_submission": True,
                "bulk_with_children": all_target_ids,
            }

            entry_contact_note = cdata.get("contact_note") or common_contact_note

            if not entry:
                entry = DailyContactEntry(
                    child_id=cid,
                    parent_account_id=current_parent_user.id,
                    target_date=target_date,
                    contact_type=contact_type,
                    temperature=temp if mode == "present" else None,
                    sleep_notes=cdata.get("sleep_notes") or None,
                    breakfast_status=cdata.get("breakfast_status") or None,
                    mood=cdata.get("mood") or None,
                    bowel_movement_status=cdata.get("bowel_movement_status") or None,
                    cough=cdata.get("cough") or None,
                    runny_nose=cdata.get("runny_nose") or None,
                    medication=cdata.get("medication") or None,
                    condition_note=cdata.get("condition_note") or None,
                    contact_note=entry_contact_note or None,
                    absence_temperature=absence_temp if mode == "absent" and contact_type == ParentContactType.absent_sick else None,
                    absence_symptoms=cdata.get("absence_symptoms") or None,
                    absence_diagnosis=cdata.get("absence_diagnosis") or None,
                    absence_note=cdata.get("absence_note") or None,
                    status=DailyContactEntryStatus.submitted,
                    extra_data=extra_data,
                    submitted_at=now,
                    created_at=now,
                    updated_at=now,
                )
                session.add(entry)
            else:
                entry.contact_type = contact_type
                entry.temperature = temp if mode == "present" else None
                entry.sleep_notes = cdata.get("sleep_notes") or None
                entry.breakfast_status = cdata.get("breakfast_status") or None
                entry.mood = cdata.get("mood") or None
                entry.bowel_movement_status = cdata.get("bowel_movement_status") or None
                entry.cough = cdata.get("cough") or None
                entry.runny_nose = cdata.get("runny_nose") or None
                entry.medication = cdata.get("medication") or None
                entry.condition_note = cdata.get("condition_note") or None
                entry.contact_note = entry_contact_note or None
                entry.absence_temperature = absence_temp if mode == "absent" and contact_type == ParentContactType.absent_sick else None
                entry.absence_symptoms = cdata.get("absence_symptoms") or None
                entry.absence_diagnosis = cdata.get("absence_diagnosis") or None
                entry.absence_note = cdata.get("absence_note") or None
                entry.status = DailyContactEntryStatus.submitted
                entry.extra_data = extra_data
                entry.submitted_at = now
                entry.updated_at = now

            saved_entries.append(entry)

        session.flush()
        return saved_entries
    except Exception:
        session.rollback()
        raise
