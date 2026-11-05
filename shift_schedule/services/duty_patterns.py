"""園定義勤務パターンマスタおよび契約マッチング、月間公休計算のヘルパーサービス。"""

from __future__ import annotations

import calendar
from datetime import date, time
from typing import TYPE_CHECKING, Sequence
from sqlmodel import Session, select

from ..db_models import ShiftDutyPatterns, ShiftFacilityClosedDays, ShiftFacilitySettings, StaffContracts

if TYPE_CHECKING:
    from shiftai.shift_patterns import ShiftPattern


def get_active_duty_patterns(session: Session, setting_id: int = 1) -> list[ShiftDutyPatterns]:
    """園で有効な勤務パターンマスタ一覧を取得する。未登録の場合は既定パターンを生成・登録する。"""
    patterns = session.exec(
        select(ShiftDutyPatterns)
        .where(ShiftDutyPatterns.setting_id == setting_id, ShiftDutyPatterns.is_active.is_(True))
        .order_by(ShiftDutyPatterns.start_time)
    ).all()
    if patterns:
        return list(patterns)

    # 既定パターンの初期化
    facility = session.get(ShiftFacilitySettings, setting_id)
    day_open = getattr(facility, "day_open", "07:30") if facility else "07:30"
    day_close = getattr(facility, "day_close", "19:30") if facility else "19:30"

    default_defs = [
        ShiftDutyPatterns(
            setting_id=setting_id,
            name="早番",
            symbol="早",
            start_time=day_open,
            end_time="16:30",
            break_minutes=60,
            is_opening=True,
            is_closing=False,
            color="#E3F2FD",
        ),
        ShiftDutyPatterns(
            setting_id=setting_id,
            name="日勤",
            symbol="日",
            start_time="08:30",
            end_time="17:30",
            break_minutes=60,
            is_opening=False,
            is_closing=False,
            color="#E8F5E9",
        ),
        ShiftDutyPatterns(
            setting_id=setting_id,
            name="遅番",
            symbol="遅",
            start_time="10:30",
            end_time=day_close,
            break_minutes=60,
            is_opening=False,
            is_closing=True,
            color="#FFF3E0",
        ),
    ]
    for p in default_defs:
        session.add(p)
    session.commit()
    return default_defs


def to_shiftai_patterns(duty_patterns: Sequence[ShiftDutyPatterns]) -> list[ShiftPattern]:
    """DBの ShiftDutyPatterns を shiftai.shift_patterns.ShiftPattern のリストに変換する。"""
    from shiftai.shift_patterns import ShiftPattern

    res: list[ShiftPattern] = []
    for dp in duty_patterns:
        try:
            sh, sm = map(int, dp.start_time.split(":"))
            eh, em = map(int, dp.end_time.split(":"))
            start_t = time(sh, sm)
            end_t = time(eh, em)
        except Exception:
            continue

        res.append(
            ShiftPattern(
                key=dp.symbol or dp.name,
                label=dp.name,
                start=start_t,
                end=end_t,
                symbol=dp.symbol or "",
            )
        )
    return res


def match_staff_patterns(
    contract: StaffContracts | None,
    duty_patterns: Sequence[ShiftDutyPatterns],
) -> list[ShiftDutyPatterns]:
    """職員の契約条件（最早出勤、最遅退勤）に適合するパターン候補を絞り込む。"""
    if contract is None:
        return list(duty_patterns)

    matched: list[ShiftDutyPatterns] = []
    for p in duty_patterns:
        if contract.earliest_start and p.start_time < contract.earliest_start:
            continue
        if contract.latest_end and p.end_time > contract.latest_end:
            continue
        matched.append(p)
    return matched


def calculate_monthly_holiday_target(
    session: Session,
    target_month: str,
    setting_id: int = 1,
) -> int:
    """指定月の標準公休数（日祝および園休園日の日数）を算出する。"""
    year, month = map(int, target_month.split("-"))
    num_days = calendar.monthrange(year, month)[1]
    start_date = date(year, month, 1)
    end_date = date(year, month, num_days)

    closed_days = session.exec(
        select(ShiftFacilityClosedDays.target_date).where(
            ShiftFacilityClosedDays.setting_id == setting_id,
            ShiftFacilityClosedDays.target_date >= start_date,
            ShiftFacilityClosedDays.target_date <= end_date,
        )
    ).all()
    closed_set = set(closed_days)

    holidays = 0
    for day in range(1, num_days + 1):
        d = date(year, month, day)
        if d.weekday() == 6 or d in closed_set:
            holidays += 1
    return max(holidays, 8)
