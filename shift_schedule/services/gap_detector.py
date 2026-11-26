"""Shift schedule gap detector service.

Detects staffing shortfalls and gaps between child requirements and
scheduled staff when child arrival/pickup plans change.
"""
from __future__ import annotations

from datetime import date, time
import re
import uuid
from typing import NamedTuple

from sqlmodel import Session, select

from models import (
    AttendanceRecord,
    AttendanceVerification,
    ChildCareCertification,
    User,
)
from shiftai.domain import ChildPlan
from shiftai.standards import build_requirements
from shiftai.local_rules import build_standard
from ..bridge import (
    active_children,
    build_child_plan,
    build_facility_settings,
    build_staff_member,
)
from ..db_models import (
    ChildPlannedArrivalDefaults,
    ShiftDutyPatterns,
    ShiftFacilityClosedDays,
    ShiftPlanCells,
)
from ..store import ShiftRepositoryDep


class GapWarning(NamedTuple):
    target_date: date
    slot_label: str
    required_count: int
    actual_count: int
    shortfall: int
    message: str


_TIME_RANGE_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*[-–〜]\s*(\d{1,2}):(\d{2})$")


def _parse_time_range(label: str) -> tuple[time, time] | None:
    m = _TIME_RANGE_RE.match((label or "").strip())
    if not m:
        return None
    try:
        return (
            time(int(m.group(1)), int(m.group(2))),
            time(int(m.group(3)), int(m.group(4))),
        )
    except ValueError:
        return None


def _cell_covers_slot(
    cell_label: str,
    slot_label: str,
    slot_start: time,
    slot_end: time,
    pattern_map: dict[str, tuple[time, time]],
) -> bool:
    """シフトセルの勤務枠が対象 30 分スロットをカバーしているか判定する。"""
    if cell_label == slot_label:
        return True
    rng = _parse_time_range(cell_label) or pattern_map.get(cell_label)
    if rng is not None:
        c_start, c_end = rng
        return c_start < slot_end and c_end > slot_start
    # 時間帯情報を持たないレガシーラベル（例: WORK）は在勤とみなす
    return True


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

    # 園児プランの収集（bridge.build_child_plan の再利用に統一）
    children = active_children(session, target_date)
    child_plans: list[ChildPlan] = []
    for c in children:
        rec = session.exec(
            select(AttendanceRecord).where(
                AttendanceRecord.child_id == c.id,
                AttendanceRecord.attendance_date == target_date,
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
        cert = session.exec(
            select(ChildCareCertification).where(
                ChildCareCertification.child_id == c.id,
                ChildCareCertification.is_active == True,  # noqa: E712
                ChildCareCertification.effective_from <= target_date,
                (ChildCareCertification.effective_to.is_(None))
                | (ChildCareCertification.effective_to >= target_date),
            )
        ).first()
        verif = session.exec(
            select(AttendanceVerification).where(
                AttendanceVerification.child_id == c.id,
                AttendanceVerification.target_date == target_date,
            )
        ).first()

        cp = build_child_plan(
            session,
            c,
            target_date,
            attendance_record=rec,
            planned_arrival_default=planned_def,
            certification=cert,
            verification=verif,
        )
        if cp is not None:
            child_plans.append(cp)

    # 休園日・祝日
    closed_rows = session.exec(
        select(ShiftFacilityClosedDays).where(
            ShiftFacilityClosedDays.setting_id == (facility_row.id or 1),
            ShiftFacilityClosedDays.target_date == target_date,
        )
    ).all()
    closed_days = [r.target_date for r in closed_rows if r.kind == "closed"]
    holiday_dates = [r.target_date for r in closed_rows if r.kind == "holiday"]

    # 必要人員要件の算出（正シグネチャ）
    req_table = build_requirements(
        child_plans,
        [target_date],
        standard,
        day_open=facility_settings.day_open,
        day_close=facility_settings.day_close,
        granularity_min=facility_settings.granularity_min,
        closed_days=closed_days,
        holiday_dates=holiday_dates,
    )

    # シフト表からの供給人員集計（時間帯別）
    cells = session.exec(
        select(ShiftPlanCells).where(
            ShiftPlanCells.plan_id == plan_id,
            ShiftPlanCells.target_date == target_date,
        )
    ).all()

    active_cells = [
        c for c in cells if c.slot_label not in ("OFF", "unspecified", "休み") and c.cell_state != "OFF"
    ]

    pattern_map: dict[str, tuple[time, time]] = {}
    for pat in session.exec(select(ShiftDutyPatterns)).all():
        try:
            s_t = time.fromisoformat(pat.start_time) if isinstance(pat.start_time, str) else pat.start_time
            e_t = time.fromisoformat(pat.end_time) if isinstance(pat.end_time, str) else pat.end_time
            if pat.code:
                pattern_map[pat.code] = (s_t, e_t)
            if pat.name:
                pattern_map[pat.name] = (s_t, e_t)
        except Exception:
            continue

    # 職員ごとの配置可能フラグをキャッシュ（N+1防止）
    placeable_cache: dict[str, bool] = {}
    for c in active_cells:
        uid_str = str(c.staff_user_id)
        if uid_str in placeable_cache:
            continue
        user = None
        target_uuid = None
        if isinstance(c.staff_user_id, uuid.UUID):
            target_uuid = c.staff_user_id
        elif isinstance(c.staff_user_id, str):
            try:
                target_uuid = uuid.UUID(hex=c.staff_user_id) if len(c.staff_user_id) == 32 else uuid.UUID(c.staff_user_id)
            except Exception:
                target_uuid = None
        if target_uuid is not None:
            user = session.get(User, target_uuid)
        is_ok = False
        if user:
            sm = build_staff_member(session, user)
            is_ok = bool(sm and sm.is_placeable)
        placeable_cache[uid_str] = is_ok

    warnings: list[GapWarning] = []
    # 各 30 分スロットでの実在勤人員ベースの不足チェック
    for req in req_table.for_day(target_date):
        needed = req.needed_staff
        covering_staff_ids = {
            str(c.staff_user_id)
            for c in active_cells
            if placeable_cache.get(str(c.staff_user_id), False)
            and _cell_covers_slot(
                c.slot_label,
                req.slot.label,
                req.slot.start,
                req.slot.end,
                pattern_map,
            )
        }
        actual_count = len(covering_staff_ids)
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
