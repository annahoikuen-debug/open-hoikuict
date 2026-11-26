"""Facility settings helpers (singleton row, defaults, change history).

仕様: docs/facility-settings-spec.md

- 設定行がなくても既定値で動く
- 参照ヘルパは勝手に ``commit()`` しない
- 料金・請求に影響しうる値は変更履歴（``FacilitySettingsHistory``）を残す
"""
from __future__ import annotations

import json
import re

from fastapi import HTTPException
from sqlmodel import Session, select

from models import FacilitySettings, FacilitySettingsHistory
from time_utils import utc_now

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")

AVAILABLE_SIMPLE_TILES = [
    {"key": "attendance_checks", "label": "出欠確認", "icon": "📝", "url": "/attendance-checks/", "desc": "朝の点呼・目視確認・HUD"},
    {"key": "attendance", "label": "登降園管理", "icon": "🕒", "url": "/attendance/", "desc": "園児の登園・降園打刻"},
    {"key": "daily_contacts", "label": "日次連絡", "icon": "📖", "url": "/daily-contacts/", "desc": "保護者連絡・返信作成"},
    {"key": "health", "label": "健康・午睡", "icon": "🌡️", "url": "/nap-checks", "desc": "検温・SIDS午睡チェック"},
    {"key": "notices", "label": "お知らせ", "icon": "📢", "url": "/notices/", "desc": "保護者向け連絡・掲示"},
    {"key": "plans", "label": "指導計画", "icon": "📋", "url": "/plans/", "desc": "月案・週案・日案作成"},
    {"key": "calendar", "label": "カレンダー", "icon": "📅", "url": "/calendar", "desc": "行事予定・シフト確認"},
    {"key": "staff_rooms", "label": "職員ルーム", "icon": "💬", "url": "/staff-rooms/", "desc": "園内掲示板・情報共有"},
]

DEFAULT_SIMPLE_TILES = [
    "attendance_checks",
    "attendance",
    "daily_contacts",
    "health",
    "notices",
    "plans",
]

DEFAULTS = dict(
    final_pickup_time="19:00",
    supplementary_meal_time="18:00",
    supplementary_meal_fee=100,
    parent_billing_portal_enabled=False,
    dinner_reminder_time="19:00",
    medical_consent_auto_approve=False,
    attendance_smart_hud_enabled=True,
    staff_simple_mode_enabled=True,
    simple_mode_custom_tiles=json.dumps(DEFAULT_SIMPLE_TILES),
    nap_check_smart_enabled=True,
    nap_check_interval_minutes=5,
    board_qr_enabled=True,
    board_qr_version=1,
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
        attendance_smart_hud_enabled=str(settings.attendance_smart_hud_enabled),
        staff_simple_mode_enabled=str(settings.staff_simple_mode_enabled),
        simple_mode_custom_tiles=str(settings.simple_mode_custom_tiles or ""),
        nap_check_smart_enabled=str(settings.nap_check_smart_enabled),
        nap_check_interval_minutes=str(settings.nap_check_interval_minutes),
        board_qr_enabled=str(settings.board_qr_enabled),
        board_qr_version=str(settings.board_qr_version),
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


def dinner_reminder_time(session: Session) -> str:
    """夕食リマインド通知の既定送信時刻（HH:MM）。"""
    settings = get_facility_settings(session)
    return getattr(settings, "dinner_reminder_time", "19:00")


def medical_consent_auto_approve(session: Session) -> bool:
    """医療同意のゼロ差分自動承認が有効か判定する。"""
    settings = get_facility_settings(session)
    return bool(getattr(settings, "medical_consent_auto_approve", False))


def is_smart_hud_enabled(session: Session) -> bool:
    """スマート・モーニング点呼HUDモードが施設設定で有効か判定する（改善案1）。"""
    settings = get_facility_settings(session)
    return bool(getattr(settings, "attendance_smart_hud_enabled", True))


def is_simple_mode_enabled(session: Session) -> bool:
    """かんたんモード・コマンドバーが施設設定で有効か判定する（改善案9）。"""
    settings = get_facility_settings(session)
    return bool(getattr(settings, "staff_simple_mode_enabled", True))


def get_simple_mode_tiles(session: Session) -> list[dict[str, str]]:
    """かんたんモードで表示するタイルのリストを返す（カスタマイズ対応）。"""
    settings = get_facility_settings(session)
    tile_keys_raw = getattr(settings, "simple_mode_custom_tiles", None)
    selected_keys = None
    if tile_keys_raw:
        try:
            parsed = json.loads(tile_keys_raw)
            if isinstance(parsed, list):
                selected_keys = set(parsed)
        except Exception:
            selected_keys = None

    if selected_keys is None:
        selected_keys = set(DEFAULT_SIMPLE_TILES)

    return [tile for tile in AVAILABLE_SIMPLE_TILES if tile["key"] in selected_keys]


def is_nap_check_smart_enabled(session: Session) -> bool:
    """スマート午睡チェック（コドモン互換タイムライン）が施設設定で有効か判定する（改善案2）。"""
    settings = get_facility_settings(session)
    return bool(getattr(settings, "nap_check_smart_enabled", True))


def nap_check_interval_minutes(session: Session) -> int:
    """午睡チェック間隔（分: 5 または 10）。"""
    settings = get_facility_settings(session)
    return int(getattr(settings, "nap_check_interval_minutes", 5))


def is_board_qr_enabled(session: Session) -> bool:
    """掲示板QRコードでの登降園打刻が有効か判定する。"""
    settings = get_facility_settings(session)
    return bool(getattr(settings, "board_qr_enabled", True))


def get_board_qr_version(session: Session) -> int:
    """現在有効な掲示板QRコードの世代番号を返す。"""
    settings = get_facility_settings(session)
    return int(getattr(settings, "board_qr_version", 1) or 1)

