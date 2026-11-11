"""Facility settings helpers (singleton row, defaults, change history).

仕様: docs/facility-settings-spec.md

- 設定行がなくても既定値で動く
- 参照ヘルパは勝手に ``commit()`` しない
- 料金・請求に影響しうる値は変更履歴（``FacilitySettingsHistory``）を残す
"""
from __future__ import annotations

import re

from fastapi import HTTPException
from sqlmodel import Session, select

from models import FacilitySettings, FacilitySettingsHistory
from time_utils import utc_now

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

DEFAULTS = dict(
    final_pickup_time="19:00",
    supplementary_meal_time="18:00",
    supplementary_meal_fee=100,
    parent_billing_portal_enabled=False,
)


def get_facility_settings(session: Session) -> FacilitySettings:
    """設定行を取得。無ければ既定値の行を返す（commitはしない）。"""
    settings = session.exec(select(FacilitySettings).where(FacilitySettings.id == 1)).first()
    if settings is None:
        settings = FacilitySettings(id=1, **DEFAULTS)
    return settings


def parse_hhmm(raw: str, label: str) -> str:
    if not TIME_RE.match(raw or ""):
        raise HTTPException(status_code=422, detail=f"{label}の形式が不正です (HH:MM)")
    return raw


def record_change_history(
    session: Session,
    settings: FacilitySettings,
    previous: dict[str, str],
    actor_name: str,
    actor_user_id=None,
) -> None:
    """変更のあった項目だけ履歴行として追加する（commitは呼び出し側）。"""
    current = dict(
        final_pickup_time=settings.final_pickup_time,
        supplementary_meal_time=settings.supplementary_meal_time,
        supplementary_meal_fee=str(settings.supplementary_meal_fee),
        parent_billing_portal_enabled=str(settings.parent_billing_portal_enabled),
    )
    now = utc_now()
    for field, new_value in current.items():
        if field not in previous:
            continue
        old_value = previous.get(field, "")
        if old_value == new_value:
            continue
        session.add(FacilitySettingsHistory(
            field_name=field,
            old_value=old_value,
            new_value=new_value,
            changed_by_name=actor_name,
            changed_by_user_id=actor_user_id,
            changed_at=now,
        ))


def latest_pickup_time(session: Session) -> str:
    """保護者がお迎え予定時刻として選べる上限時刻。"""
    return get_facility_settings(session).final_pickup_time


def snack_threshold_time(session: Session) -> str:
    """この時刻以降のお迎え予定は補食対象と初期判定する時刻。"""
    return get_facility_settings(session).supplementary_meal_time


def snack_fee(session: Session) -> int:
    """補食費の表示用金額。"""
    return get_facility_settings(session).supplementary_meal_fee


def auto_snack_required(session: Session, planned_pickup_time: str) -> bool:
    """予定時刻が補食判定時刻以降かどうかの初期判定。

    予定時刻が未入力の場合は補食不要と判定する。
    """
    time_value = (planned_pickup_time or "").strip()
    if not TIME_RE.match(time_value):
        return False
    return time_value >= snack_threshold_time(session)


def is_parent_billing_enabled(session: Session) -> bool:
    """施設設定で保護者ポータル請求・延長保育料確認機能が有効か判定する。"""
    settings = get_facility_settings(session)
    return bool(getattr(settings, "parent_billing_portal_enabled", False))
