"""計画類の連続性・転記削減に関する共通ユーティリティ。

本モジュールは純関数と読み取り系のルックアップのみを提供し、
書き込み（DB更新）は行わない。案2/3/4で共通して利用する。
"""
from __future__ import annotations

import re
from datetime import date, timedelta


def month_index(value: str) -> int:
    """YYYY-MM を総月数に変換。不正な場合は ValueError。"""
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ValueError(f"invalid month format: {value!r}")
    year_text, month_text = value.split("-", 1)
    return int(year_text) * 12 + (int(month_text) - 1)


def previous_month(target_month: str) -> str:
    """対象月の直前暦月を YYYY-MM で返す。年度替わり（4月→3月）も暦月で処理する。"""
    return f"{(month_index(target_month) - 1) // 12:04d}-{(month_index(target_month) - 1) % 12 + 1:02d}"


def iso_week_monday(target_date: date) -> date:
    """対象日付の属する ISO 週の月曜日を返す。"""
    return target_date.fromisocalendar(target_date.isocalendar()[0], target_date.isocalendar()[1], 1)


def previous_business_day(target_date: date) -> date:
    """前営業日を返す。土・日を除外し、月曜なら前週金曜日を返す。"""
    day = target_date - timedelta(days=1)
    while day.weekday() >= 5:  # 5=土, 6=日
        day -= timedelta(days=1)
    return day


def common_field_keys_for_template(age: int) -> set[str]:
    """テンプレート間で共通して存在する欄キーを返す。

    年齢跨ぎ（例：3月 2歳児 → 4月 3歳児）の引き継ぎでは、
    両テンプレートに存在する共通欄のみをコピー対象とする。
    """
    keys = {"common:goal", "common:home", "common:review"}
    if age < 3:
        keys |= {"common:events"}
    return keys


def monthly_sheet_key(nursery_ref: str, classroom_id: int, target_month: str, age: int) -> str:
    """monthly_library._scope と同一規則で monthly_sheet_key を生成する。"""
    import json

    return json.dumps(
        [nursery_ref, classroom_id, target_month, age], ensure_ascii=False
    )


def carried_from_month(target_month: str) -> str:
    """引き継ぎ元月の表示ラベルを返す。"""
    return previous_month(target_month)


__all__ = [
    "month_index",
    "previous_month",
    "iso_week_monday",
    "previous_business_day",
    "common_field_keys_for_template",
    "monthly_sheet_key",
    "carried_from_month",
]
