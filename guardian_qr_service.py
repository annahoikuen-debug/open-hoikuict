"""登降園QRコード生成・検証および兄弟一括打刻サービス。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from datetime import date
from typing import Any, Optional

from fastapi import HTTPException
from sqlmodel import Session

from attendance_checks_service import sync_attendance_alarm
from extended_care_fee_service import recalculate_attendance_charge
from models import (
    AttendanceRecord,
    Child,
    ChildStatus,
    ParentAccount,
)
from pickup_plan_service import load_pickup_record
from time_utils import local_naive_now, local_today, utc_now


def _qr_secret_key() -> bytes:
    configured = os.getenv("HOIKUICT_SECRET_KEY")
    if configured:
        return configured.encode("utf-8")
    return b"open-hoikuict-guardian-qr-secret-key-fallback"


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(raw: str) -> bytes:
    padding = 4 - (len(raw) % 4)
    if padding != 4:
        raw += "=" * padding
    return base64.urlsafe_b64decode(raw.encode("ascii"))


def generate_parent_qr_token(
    parent_account_id: int,
    family_id: Optional[int] = None,
    expires_in_days: int = 30,
) -> str:
    """保護者用のHMAC署名付き登降園QRトークンを生成する。"""
    now = int(time.time())
    exp = now + (expires_in_days * 86400)
    payload = {
        "v": 1,
        "pid": parent_account_id,
        "fid": family_id,
        "iat": now,
        "exp": exp,
    }
    payload_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)

    sig = hmac.new(_qr_secret_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{payload_b64}.{sig_b64}"


def verify_parent_qr_token(token: str) -> dict[str, Any]:
    """登降園QRトークンの署名および有効期限を検証し、ペイロードを返す。不正時はValueError。"""
    if not token or "." not in token:
        raise ValueError("QRトークンのフォーマットが不正です。")

    parts = token.split(".")
    if len(parts) != 2:
        raise ValueError("QRトークンの構成要素が不正です。")

    payload_b64, sig_b64 = parts[0], parts[1]

    # 署名検証
    expected_sig = hmac.new(_qr_secret_key(), payload_b64.encode("ascii"), hashlib.sha256).digest()
    expected_sig_b64 = _b64url_encode(expected_sig)

    if not hmac.compare_digest(sig_b64, expected_sig_b64):
        raise ValueError("QRトークンの署名が一致しません（改ざんの可能性があります）。")

    try:
        payload_bytes = _b64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError("QRトークンのデコードに失敗しました。") from exc

    # 有効期限検証
    exp = payload.get("exp")
    if exp is not None and time.time() > exp:
        raise ValueError("QRトークンの有効期限が切れています。")

    return payload


def generate_parent_qr_svg(token: str) -> str:
    """QRトークンをSVG画像形式で生成する（完全CDNフリー・ローカル生成）。"""
    import qrcode
    from qrcode.image.svg import SvgPathFillImage

    qr = qrcode.make(token, image_factory=SvgPathFillImage, border=2)
    return qr.to_string().decode("utf-8") if isinstance(qr.to_string(), bytes) else qr.to_string()


def get_sibling_qr_punch_info(
    session: Session,
    *,
    parent_account_id: int,
    target_date: Optional[date] = None,
) -> dict[str, Any]:
    """QR認識時に表示する家族・園児一覧と打刻候補ステータスを取得する。"""
    day = target_date or local_today()
    parent = session.get(ParentAccount, parent_account_id)
    if not parent:
        raise HTTPException(status_code=404, detail="保護者アカウントが見つかりません。")

    # 園児取得
    children = []
    if parent.child_links:
        children = [link.child for link in parent.child_links if link.child and link.child.status == ChildStatus.enrolled]
    elif parent.family and parent.family.children:
        children = [c for c in parent.family.children if c.status == ChildStatus.enrolled]

    children_info = []
    has_unpunched_in = False
    has_punched_in_not_out = False

    for child in children:
        rec = load_pickup_record(session, child.id, day)
        check_in_time = rec.check_in_at.strftime("%H:%M") if rec and rec.check_in_at else None
        check_out_time = rec.check_out_at.strftime("%H:%M") if rec and rec.check_out_at else None

        if not check_in_time and not check_out_time:
            status = "not_arrived"
            has_unpunched_in = True
        elif check_in_time and not check_out_time:
            status = "present"
            has_punched_in_not_out = True
        else:
            status = "left"

        children_info.append({
            "child_id": child.id,
            "full_name": child.full_name,
            "classroom_name": child.classroom.name if child.classroom else "",
            "status": status,
            "check_in_time": check_in_time,
            "check_out_time": check_out_time,
            "planned_pickup_time": rec.planned_pickup_time if rec else "",
            "pickup_person": rec.pickup_person if rec else "",
        })

    # 推奨アクションの自動判定（朝は登園、夕方は降園を優先）
    now_hour = local_naive_now().hour
    if has_unpunched_in and (now_hour < 12 or not has_punched_in_not_out):
        suggested_action = "check_in"
    elif has_punched_in_not_out:
        suggested_action = "check_out"
    else:
        suggested_action = "check_in"

    return {
        "parent_id": parent.id,
        "parent_name": parent.display_name,
        "family_name": parent.family.family_name if parent.family else "",
        "suggested_action": suggested_action,
        "target_date": day.isoformat(),
        "children": children_info,
    }


def execute_sibling_qr_punch(
    session: Session,
    *,
    child_ids: list[int],
    action: str,  # "check_in" or "check_out"
    actual_pickup_person: str = "",
    target_date: Optional[date] = None,
    actor_name: str = "保護者QR",
) -> list[AttendanceRecord]:
    """選択された兄弟姉妹に対する登園または降園を一括コミットする。"""
    if not child_ids:
        raise ValueError("打刻対象の園児が選択されていません。")

    day = target_date or local_today()
    now_naive = local_naive_now()
    audit_now = utc_now()
    updated_records: list[AttendanceRecord] = []

    for cid in child_ids:
        child = session.get(Child, cid)
        if not child:
            continue

        record = load_pickup_record(session, cid, day)
        if record is None:
            record = AttendanceRecord(child_id=cid, attendance_date=day)
            session.add(record)
            session.flush()

        if action == "check_in":
            if record.check_in_at:
                continue  # すでに登園打刻済みならスキップ
            record.check_in_at = now_naive
            record.updated_at = audit_now
        elif action == "check_out":
            if record.check_out_at:
                continue  # すでに降園打刻済みならスキップ
            record.check_out_at = now_naive
            if actual_pickup_person:
                record.actual_pickup_person = actual_pickup_person
            record.updated_at = audit_now
            recalculate_attendance_charge(session, record)

        sync_attendance_alarm(session, child_id=cid, target_date=day, record=record, now=audit_now)
        updated_records.append(record)

    session.flush()
    return updated_records
