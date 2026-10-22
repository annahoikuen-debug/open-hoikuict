"""Shift schedule gap detector service.

Detects staffing shortfalls and gaps between child requirements and
scheduled staff when child arrival/pickup plans change.
"""
from __future__ import annotations

from datetime import date
from typing import NamedTuple

from sqlmodel import Session, select

from models import AttendanceRecord, Child, User
from shiftai.domain import ChildPlan
from shiftai.standards import build_requirements
from shiftai.local_rules import build_standard
from ..bridge import age_class_on, build_facility_settings, build_staff_member
from ..db_models import ShiftPlanCells, ChildPlannedArrivalDefaults
from ..store import ShiftRepositoryDep


class GapWarning(NamedTuple):
    target_date: date
    slot_label: str
    required_count: int
    actual_count: int
    shortfall: int
    message: str


def detect_day_gap(
    session: Session,
    plan_id: int,
    target_date: date,
) -> list[GapWarning]:
    """指定日における園児必要人員とシフト配置人員の乖離（配置割れ）を検査する。"""
    repo = ShiftRepositoryDep(session)
    plan = repo.get_plan(plan_id)
    if plan is None:
        return []

    # 施設設定
    facility_row = repo.facility_settings()
    facility_settings = build_facility_settings(facility_row)
    if facility_settings is None:
        return []

    standard = build_standard(plan.staffing_standard_key)

    # 園児プランの収集
    children = session.exec(select(Child)).all()
    child_plans: list[ChildPlan] = []
    for c in children:
        rec = session.exec(
            select(AttendanceRecord).where(
                AttendanceRecord.child_id == c.id,
                AttendanceRecord.target_date == target_date,
            )
        ).first()
        planned_def = session.exec(
            select(ChildPlannedArrivalDefaults).where(
                ChildPlannedArrivalDefaults.child_id == c.id,
                (ChildPlannedArrivalDefaults.effective_to.is_(None))
                | (ChildPlannedArrivalDefaults.effective_to >= target_date),
                ChildPlannedArrivalDefaults.effective_from <= target_date,
            )
        ).first()

        arrive = None
        if rec and rec.check_in_at:
            arrive = rec.check_in_at.time()
        elif rec and rec.planned_check_in_time:
            from datetime import time
            arrive = time.fromisoformat(rec.planned_check_in_time)
        elif planned_def:
            from datetime import time
            arrive = time.fromisoformat(planned_def.planned_check_in_time)

        depart = None
        if rec and rec.planned_pickup_time:
            from datetime import time
            depart = time.fromisoformat(rec.planned_pickup_time)

        from datetime import time
        arrive = arrive or time(8, 0)
        depart = depart or time(18, 0)

        if depart > arrive:
            child_plans.append(
                ChildPlan(
                    child_id=str(c.id),
                    name=c.full_name,
                    day=target_date,
                    age_class=age_class_on(target_date, c.birth_date),
                    arrive=arrive,
                    depart=depart,
                    is_short_time=bool(c.care_time_category == "short"),
                    absent=bool(rec and rec.is_absent),
                )
            )

    # 必要人員要件の算出
    requirements = build_requirements(
        settings=facility_settings,
        standard=standard,
        plans=child_plans,
    )

    # シフト表からの供給人員集計
    cells = session.exec(
        select(ShiftPlanCells).where(
            ShiftPlanCells.plan_id == plan_id,
            ShiftPlanCells.target_date == target_date,
        )
    ).all()

    work_staff_ids = {
        c.staff_user_id for c in cells if c.slot_label not in ("OFF", "unspecified", "休み")
    }

    # 供給可能保育士数
    actual_count = 0
    for uid in work_staff_ids:
        user = session.get(User, uid)
        if user:
            sm = build_staff_member(session, user)
            if sm and sm.is_placeable:
                actual_count += 1

    warnings: list[GapWarning] = []
    # 各スロットでの不足チェック
    for req in requirements:
        if req.day == target_date:
            needed = req.required_staff
            if actual_count < needed:
                shortfall = needed - actual_count
                warnings.append(
                    GapWarning(
                        target_date=target_date,
                        slot_label=req.slot.label,
                        required_count=needed,
                        actual_count=actual_count,
                        shortfall=shortfall,
                        message=f"{target_date.isoformat()} {req.slot.label}: 保育士が {shortfall}名 不足しています (必要 {needed}名 / 配置 {actual_count}名)",
                    )
                )

    return warnings
