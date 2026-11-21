"""Adapter between ShiftSolveRequest and NuShift shiftai core solver.

リクエストJSONを shiftai.monthly.MonthlySolveContext にマッピングし、
数理最適化求解を実行して ShiftSolveResponse に変換するステートレスアダプター。
"""

from __future__ import annotations

import logging
import time
from datetime import date, datetime, time as dt_time, timedelta
from typing import Any

from shiftai.domain import (
    CellState,
    Contract,
    EmploymentType,
    FacilitySettings,
    Role,
    StaffMember,
    StaffPreferences,
    Unavailability,
)
from shiftai.local_rules import build_standard
from shiftai.monthly import MonthlySolveContext, SolveResult, solve_monthly_hierarchical
from shiftai.shift_patterns import default_patterns

from .schema import (
    ComplianceReportSchema,
    ScoreReportSchema,
    ShiftSlotSchema,
    ShiftSolveRequest,
    ShiftSolveResponse,
)

logger = logging.getLogger("serverless_solver.adapter")


def _parse_time(time_str: str) -> dt_time:
    """HH:MM 形式の文字列を datetime.time に変換。"""
    parts = time_str.strip().split(":")
    return dt_time(int(parts[0]), int(parts[1]))


def execute_solve(request: ShiftSolveRequest) -> ShiftSolveResponse:
    """ShiftSolveRequest を受け取り、NuShift 数理最適化を実行して ShiftSolveResponse を返す純粋関数。"""
    start_t = time.perf_counter()

    # 1. 対象月全日付の構築
    start_date = date.fromisoformat(f"{request.target_month}-01")
    if start_date.month == 12:
        end_date = date(start_date.year + 1, 1, 1) - timedelta(days=1)
    else:
        end_date = date(start_date.year, start_date.month + 1, 1) - timedelta(days=1)

    all_days: list[date] = []
    cur = start_date
    while cur <= end_date:
        all_days.append(cur)
        cur += timedelta(days=1)

    # 2. 施設設定の復元
    cfg = request.facility_config
    closed_dates = frozenset(date.fromisoformat(d) for d in cfg.closed_days)
    holiday_dates = frozenset(date.fromisoformat(d) for d in cfg.holiday_dates)

    day_open = _parse_time(cfg.opening_time)
    day_close = _parse_time(cfg.closing_time)

    facility_settings = FacilitySettings(
        facility_name=f"Facility_{request.facility_id}",
        day_open=day_open,
        day_close=day_close,
        granularity_min=cfg.granularity_min,
        capacity=30,
        closed_days=closed_dates,
        holiday_dates=holiday_dates,
    )

    # 3. 職員リストおよび契約・希望休の復元
    staff_members: list[StaffMember] = []
    contracts_map: dict[str, Contract] = {}
    preferences_map: dict[str, StaffPreferences] = {}

    for s in request.staff_list:
        emp_type = (
            EmploymentType.SEI
            if s.employment_type.upper() in ("FULL_TIME", "REGULAR", "SEI", "常勤", "正職員")
            else EmploymentType.PART
        )
        roles = frozenset([Role.HOIKUSHI] if s.is_qualified else [Role.SHIENSHIIN])

        contract = Contract(
            weekly_hours=s.weekly_contract_hours,
            daily_hours=8.0 if emp_type == EmploymentType.SEI else 6.0,
            employment_type=emp_type,
            max_consecutive_days=s.max_consecutive_days,
            earliest_start=day_open if s.can_work_early else dt_time(8, 30),
            latest_end=day_close if s.can_work_late else dt_time(17, 30),
        )

        member = StaffMember(
            staff_id=s.staff_id,
            name=s.name,
            roles=roles,
            contract=contract,
        )
        staff_members.append(member)
        contracts_map[s.staff_id] = contract

        # 希望休（Unavailability: 終日の場合は 00:00〜23:59）
        unavail_list = [
            Unavailability(
                day=date.fromisoformat(ud),
                start=dt_time(0, 0),
                end=dt_time(23, 59),
                reason="REQUESTED_OFF",
            )
            for ud in s.unavailable_dates
        ]
        preferences_map[s.staff_id] = StaffPreferences(
            unavailable=frozenset(unavail_list),
        )

    # 4. パターンおよび基準
    patterns = default_patterns(day_open, day_close)
    standard = build_standard(request.staffing_standard_key, overrides={})

    # 5. 固定セル（ピン留め）の復元
    fixed_assignments: dict[tuple[str, date, str], CellState] = {}
    for staff_id, date_map in request.pinned_assignments.items():
        for d_str, slot in date_map.items():
            slot_date = date.fromisoformat(d_str)
            if slot.code in ("休", "公休", "OFF"):
                fixed_assignments[(staff_id, slot_date, "all")] = CellState.OFF
            elif slot.start and slot.end:
                fixed_assignments[(staff_id, slot_date, f"{slot.start}-{slot.end}")] = CellState.WORK
            else:
                fixed_assignments[(staff_id, slot_date, slot.code)] = CellState.WORK

    # 6. 必要人員テーブル（RequirementTable）の構築
    from shiftai.standards import build_requirements

    requirements = build_requirements(
        children=[],
        days=all_days,
        standard=standard,
        day_open=day_open,
        day_close=day_close,
        granularity_min=cfg.granularity_min,
        closed_days=closed_dates,
        holiday_dates=holiday_dates,
        enforce_min_two=cfg.eleven_hour_rule,
    )

    # 7. MonthlySolveContext の構築
    context = MonthlySolveContext(
        target_month=request.target_month,
        all_days=all_days,
        staff=staff_members,
        contracts=contracts_map,
        preferences=preferences_map,
        patterns=patterns,
        requirements=requirements,
        facility_settings=facility_settings,
        fixed_assignments=fixed_assignments,
        prior_duty_history=request.prior_duty_streaks,
        monthly_holiday_target=8,
        children=[],
        standard=standard,
        weights=None,
    )

    # 8. 階層的月次求解の実行
    time_limit = min(request.options.time_limit_sec, 60)
    solver_name = request.options.solver_name

    logger.info(
        "サーバーレス求解開始: facility=%s, target_month=%s, staff=%d, time_limit=%ds",
        request.facility_id,
        request.target_month,
        len(staff_members),
        time_limit,
    )

    try:
        res: SolveResult = solve_monthly_hierarchical(
            context=context,
            time_limit_sec=time_limit,
            solver_name=solver_name,
            parallel_workers=request.options.parallel_workers,
        )
    except Exception as exc:
        logger.exception("求解中に例外が発生しました: %s", exc)
        elapsed = round(time.perf_counter() - start_t, 3)
        return ShiftSolveResponse(
            status="FAILED",
            elapsed_sec=elapsed,
            error_message=str(exc),
        )

    elapsed = round(time.perf_counter() - start_t, 3)

    # 9. 結果マトリクスへの整形
    schedule_matrix: dict[str, dict[str, ShiftSlotSchema]] = {}
    for staff in staff_members:
        schedule_matrix[staff.staff_id] = {}

    if res.shift_days:
        for sday in res.shift_days:
            d_str = sday.day.isoformat()
            for staff_id, staff_slots in sday.assignments.items():
                sid_str = str(staff_id)
                pinned_info = request.pinned_assignments.get(sid_str, {}).get(d_str)

                if isinstance(staff_slots, dict):
                    work_slots = [
                        sl_name for sl_name, c_state in staff_slots.items() if c_state == CellState.WORK
                    ]
                    if work_slots:
                        start_str = work_slots[0].split("-")[0] if "-" in work_slots[0] else None
                        end_str = work_slots[-1].split("-")[1] if "-" in work_slots[-1] else None
                        if pinned_info:
                            slot_code = pinned_info.code
                        elif start_str and start_str <= "08:00":
                            slot_code = "早"
                        elif end_str and end_str >= "18:00":
                            slot_code = "遅"
                        else:
                            slot_code = "日"
                    else:
                        start_str = None
                        end_str = None
                        slot_code = pinned_info.code if pinned_info else "休"
                else:
                    slot_code = pinned_info.code if pinned_info else str(staff_slots)
                    start_str = None
                    end_str = None

                schedule_matrix.setdefault(sid_str, {})[d_str] = ShiftSlotSchema(
                    code=slot_code,
                    start=start_str,
                    end=end_str,
                    is_pinned=bool(pinned_info and pinned_info.is_pinned),
                )
    elif res.assignments:
        for (staff_id, a_date), pattern in res.assignments.items():
            sid_str = str(staff_id)
            d_str = a_date.isoformat() if hasattr(a_date, "isoformat") else str(a_date)
            pinned_info = request.pinned_assignments.get(sid_str, {}).get(d_str)
            p_code = pinned_info.code if pinned_info else (getattr(pattern, "name", str(pattern)) if pattern else "休")
            schedule_matrix.setdefault(sid_str, {})[d_str] = ShiftSlotSchema(
                code=p_code,
                is_pinned=bool(pinned_info and pinned_info.is_pinned),
            )

    # スコアと充足率
    score_hard = 0
    score_medium = 0
    score_soft = 0
    if hasattr(res, "score") and res.score is not None:
        score_hard = getattr(res.score, "hard_score", getattr(res.score, "hard", 0))
        score_medium = getattr(res.score, "medium_score", getattr(res.score, "medium", 0))
        score_soft = getattr(res.score, "soft_score", getattr(res.score, "soft", 0))

    violations_str = [str(v) for v in (res.violations or [])]
    status_str = str(getattr(res.status, "name", res.status))

    # 処方箋サジェスト
    suggestions = []
    if getattr(res, "overconstrained_shortfalls", None):
        for sf in res.overconstrained_shortfalls:
            suggestions.append(f"不足コマ検知: {sf}。パート職員の延長または希望休調整を推奨します。")

    return ShiftSolveResponse(
        status=status_str,
        elapsed_sec=elapsed,
        score=ScoreReportSchema(hard=score_hard, medium=score_medium, soft=score_soft),
        schedule_matrix=schedule_matrix,
        compliance_report=ComplianceReportSchema(
            coverage_ratio=1.0 if score_medium == 0 else max(0.0, 1.0 - (abs(score_medium) * 0.01)),
            shortfall_hours=float(abs(score_medium)),
            labor_standards_violations=violations_str,
        ),
        actionable_suggestions=suggestions,
    )
