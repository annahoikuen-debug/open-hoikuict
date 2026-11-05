"""前月確定シフト実績から月跨ぎの連続勤務履歴（バッファ）を抽出するサービス。"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from sqlmodel import Session, select

from models import User
from ..db_models import ShiftPlanCells, ShiftPlans


def get_prior_month_duty_streaks(
    session: Session,
    target_month: str,
    users: Sequence[User],
) -> dict[str, int]:
    """target_month の前月末（直近7日間）の連続勤務日数を職員ごとに算出する。"""
    start_date = dt.date.fromisoformat(target_month + "-01")
    # 直近7日間
    history_days = [start_date - dt.timedelta(days=i) for i in range(1, 8)]
    history_days.sort()

    # 前月のプランを取得
    prev_month_str = (history_days[-1]).strftime("%Y-%m")
    prev_plan = session.exec(
        select(ShiftPlans).where(ShiftPlans.target_month == prev_month_str)
    ).first()

    streaks: dict[str, int] = {str(u.id): 0 for u in users}
    if not prev_plan or not prev_plan.id:
        return streaks

    cells = session.exec(
        select(ShiftPlanCells).where(
            ShiftPlanCells.plan_id == prev_plan.id,
            ShiftPlanCells.target_date.in_(history_days),
        )
    ).all()

    # 各日に出勤（WORK）していたかを集計
    # staff_id -> date -> is_work
    work_by_staff_date: dict[str, set[dt.date]] = {}
    for c in cells:
        state = (c.cell_state or "").upper()
        if state in ("WORK", "PINNED", "SPECIFIED"):
            sid = str(c.staff_user_id)
            work_by_staff_date.setdefault(sid, set()).add(c.target_date)

    # 月末日（history_days[-1]）から遡って連続勤務日数をカウント
    for u in users:
        sid_str = str(u.id)
        worked_dates = work_by_staff_date.get(sid_str, set())
        streak = 0
        for d in reversed(history_days):
            if d in worked_dates:
                streak += 1
            else:
                break
        streaks[sid_str] = streak

    return streaks

