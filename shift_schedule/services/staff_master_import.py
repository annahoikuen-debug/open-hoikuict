"""職員マスタ CSV 取込サービス。

UTF-8 / CP932 自動判別、行単位バリデーション、資格・契約 upsert。
"""

from __future__ import annotations

import csv
import io
from datetime import date
from typing import Optional
from sqlmodel import Session, select

from models import User
from shiftai.domain import EmploymentType, Role
from ..db_models import StaffContracts, StaffQualifications


def import_staff_master_csv(session: Session, content_bytes: bytes) -> str:
    # 1. エンコーディング判別 (UTF-8 with BOM / UTF-8 / CP932)
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp932"):
        try:
            text = content_bytes.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        return "エラー: CSVファイルの文字コード（UTF-8またはShift_JIS）を認識できませんでした。"

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        return "エラー: CSVが空か、有効なヘッダ行がありません。"

    # ヘッダマッピング（別名読替対応）
    def find_val(row: dict[str, str], *keys: str) -> Optional[str]:
        for k in keys:
            for field in row:
                if field and field.strip().lower() == k.lower():
                    v = row[field].strip()
                    if v:
                        return v
        return None

    all_users = session.exec(select(User)).all()
    user_by_email = {u.email.lower(): u for u in all_users if u.email}
    user_by_id = {u.id.hex: u for u in all_users}
    user_by_str = {str(u.id): u for u in all_users}

    created_quals = 0
    created_contracts = 0
    errors: list[str] = []

    today = date.today()

    for idx, row in enumerate(reader, start=2):
        staff_key = find_val(row, "職員メール", "メールアドレス", "メール", "email", "職員id", "staff_id", "id")
        if not staff_key:
            errors.append(f"{idx}行目: 職員を特定するメールアドレスまたはIDが空です")
            continue

        target_user = user_by_email.get(staff_key.lower()) or user_by_id.get(staff_key) or user_by_str.get(staff_key)
        if not target_user:
            errors.append(f"{idx}行目: 該当する職員が見つかりません ({staff_key})")
            continue

        uid_hex = target_user.id.hex if hasattr(target_user.id, "hex") else str(target_user.id)

        # 資格
        role_val = find_val(row, "資格", "資格（主）", "role")
        if role_val:
            # 正規化・検証
            matched_role = None
            for r in Role:
                if role_val in (r.value, r.name):
                    matched_role = r.value
                    break
            if matched_role:
                # 既存有効資格を確認
                existing_q = session.exec(
                    select(StaffQualifications).where(
                        StaffQualifications.staff_user_id == uid_hex,
                        StaffQualifications.role == matched_role,
                    )
                ).first()
                if not existing_q:
                    q = StaffQualifications(
                        staff_user_id=uid_hex,
                        role=matched_role,
                        effective_from=today,
                    )
                    session.add(q)
                    created_quals += 1
            else:
                errors.append(f"{idx}行目: 未知の資格区分です ({role_val})")

        # 契約
        emp_val = find_val(row, "雇用形態", "employment_type")
        if emp_val:
            matched_emp = None
            for e in EmploymentType:
                if emp_val in (e.value, e.name):
                    matched_emp = e.value
                    break
            if not matched_emp:
                matched_emp = "正職員"

            weekly_h_str = find_val(row, "週契約時間", "週所定時間", "weekly_hours")
            daily_h_str = find_val(row, "1日契約時間", "1日所定時間", "daily_hours")
            weekly_h = float(weekly_h_str) if weekly_h_str else None
            daily_h = float(daily_h_str) if daily_h_str else None

            earliest = find_val(row, "最早始業", "earliest_start")
            latest = find_val(row, "最遅終業", "latest_end")

            has_36_str = find_val(row, "36協定", "36協定締結", "has_36_agreement")
            has_36 = has_36_str.lower() in ("1", "true", "yes", "あり", "締結") if has_36_str else True

            variable_str = find_val(row, "変形労働制", "変形労働時間制", "variable_working_hours")
            variable = variable_str.lower() in ("1", "true", "yes", "あり", "対象") if variable_str else False

            # 既存契約のクローズ & 新規追加
            existing_contracts = session.exec(
                select(StaffContracts).where(
                    StaffContracts.staff_user_id == uid_hex,
                    (StaffContracts.effective_to.is_(None)) | (StaffContracts.effective_to >= today),
                )
            ).all()
            for ec in existing_contracts:
                ec.effective_to = today
                session.add(ec)

            c = StaffContracts(
                staff_user_id=uid_hex,
                employment_type=matched_emp,
                weekly_hours=weekly_h,
                daily_hours=daily_h,
                earliest_start=earliest,
                latest_end=latest,
                has_36_agreement=has_36,
                variable_working_hours=variable,
                effective_from=today,
            )
            session.add(c)
            created_contracts += 1

    session.commit()
    msg = f"取込完了: 資格{created_quals}件、契約{created_contracts}件を登録/更新しました。"
    if errors:
        msg += f" (スキップ/注意 {len(errors)}件: " + " / ".join(errors[:3]) + ")"
    return msg
