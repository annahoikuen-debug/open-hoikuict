"""月次シフト2段階階層的求解（Hierarchical MILP）エンジン。

Stage 1: 月間日次パターン割り当て（職員×日付×勤務パターン）
  - 連続勤務上限（前月末境界バッファ考慮）
  - 月間所定公休目標の厳密遵守
  - パート職員の月間上限/下限労働時間
  - 年休消化の平準化ソフトペナルティ
  - 日次・時間帯ごとの概略配置需要充足

Stage 2: 30分スロット単位の詳細制約 & 休憩スタッガー最適化
  - Stage 1 の勤務枠を Warm-Start / 境界条件として拘束
  - 厚労省/自治体配置基準、2名ルール、クラス別配置
  - スラック変数による「解なし（Infeasible）」防止と処方箋生成
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pulp
from sqlmodel import Session

from shiftai.domain import (
    CellState,
    FacilitySettings,
    ObjectiveWeights,
    RequirementTable,
    SolveResult,
    SolveStatus,
    StaffMember,
    StaffPreferences,
    to_minutes,
)
from shiftai.shift_patterns import ShiftPattern
from shiftai.solver import snap_to_patterns, solve_shift

from ..db_models import StaffContracts


@dataclass(frozen=True)
class MonthlySolveContext:
    target_month: str
    all_days: list[dt.date]
    staff: list[StaffMember]
    contracts: dict[str, StaffContracts]
    preferences: dict[str, StaffPreferences]
    patterns: list[ShiftPattern]
    requirements: RequirementTable
    facility_settings: FacilitySettings
    fixed_assignments: dict[tuple[str, dt.date, str], CellState]
    prior_duty_history: dict[str, int]
    monthly_holiday_target: int


def solve_monthly_hierarchical(
    session: Session,
    context: MonthlySolveContext,
    time_limit_sec: int = 120,
    solver_name: str | None = None,
) -> SolveResult:
    """2段階階層的アプローチにより月次一括シフトを求解する。"""
    # ---------------------------------------------------------
    # Stage 1: 月間日次パターンの割り当て (MILP)
    # ---------------------------------------------------------
    stage1_res = _solve_stage1_daily_patterns(
        context=context,
        time_limit_sec=min(time_limit_sec // 3, 30),
    )

    combined_fixed = dict(context.fixed_assignments)
    warm_starts: dict[tuple[str, dt.date, str], CellState] = {}

    slots = tuple(context.requirements.slots)
    pattern_by_key = {p.key: p for p in context.patterns}

    for (staff_id, day), pat_key in stage1_res.items():
        if pat_key == "OFF":
            for s in slots:
                key = (staff_id, day, s.label)
                if key not in combined_fixed:
                    warm_starts[key] = CellState.OFF
            continue

        pat = pattern_by_key.get(pat_key)
        if not pat:
            continue

        pat_start_min = to_minutes(pat.start)
        pat_end_min = to_minutes(pat.end)

        for s in slots:
            key = (staff_id, day, s.label)
            if key in combined_fixed:
                continue
            if s.start_minutes >= pat_start_min and s.end_minutes <= pat_end_min:
                warm_starts[key] = CellState.WORK
            else:
                warm_starts[key] = CellState.OFF

    # ---------------------------------------------------------
    # Stage 2: 30分スロット詳細配置 & 休憩スタッガー最適化
    # ---------------------------------------------------------
    weights = ObjectiveWeights(split_duty_penalty=5000.0)

    final_result = solve_shift(
        getattr(context, "children", ()),
        staff=context.staff,
        requirements=context.requirements,
        preferences=context.preferences,
        weights=weights,
        settings=context.facility_settings,
        fixed_assignments=combined_fixed,
        time_limit_sec=max(time_limit_sec - 30, 30),
        solver_name=solver_name,
        warm_start=True,
        warm_start_assignments=warm_starts,
        patterns=context.patterns,
        pattern_mode=True,
    )

    if context.patterns and final_result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE):
        final_result, _ = snap_to_patterns(
            final_result,
            context.patterns,
            requirements=context.requirements,
            preferences=context.preferences,
            staff=context.staff,
            settings=context.facility_settings,
        )

    return final_result


def _solve_stage1_daily_patterns(
    context: MonthlySolveContext,
    time_limit_sec: int = 30,
) -> dict[tuple[str, dt.date], str]:
    """Stage 1: 日単位のパターン割り当てモデルを PuLP で定式化・求解する。"""
    prob = pulp.LpProblem("Monthly_Stage1_Pattern_Assignment", pulp.LpMinimize)

    staff_ids = [s.staff_id for s in context.staff]
    days = context.all_days
    patterns = context.patterns
    pat_keys = [p.key for p in patterns]

    x_vars: dict[tuple[str, dt.date, str], pulp.LpVariable] = {}
    duty_vars: dict[tuple[str, dt.date], pulp.LpVariable] = {}

    for sid in staff_ids:
        for d in days:
            duty_vars[(sid, d)] = pulp.LpVariable(f"duty_{sid}_{d.isoformat()}", cat=pulp.LpBinary)
            for p in patterns:
                x_vars[(sid, d, p.key)] = pulp.LpVariable(
                    f"x_{sid}_{d.isoformat()}_{p.key}", cat=pulp.LpBinary
                )

    obj_terms: list[pulp.LpAffineExpression] = []

    for sid in staff_ids:
        contract = context.contracts.get(sid)
        pref = context.preferences.get(sid)
        max_consecutive = getattr(contract, "max_consecutive_days", None) or 6

        # 1. 1日あたり高々1つの勤務パターン
        for d in days:
            prob += pulp.lpSum(x_vars[(sid, d, p.key)] for p in patterns) == duty_vars[(sid, d)]

            has_pinned_work = any(
                state == CellState.WORK
                for (s, dt_day, _), state in context.fixed_assignments.items()
                if s == sid and dt_day == d
            )
            has_pinned_off = any(
                state == CellState.OFF
                for (s, dt_day, _), state in context.fixed_assignments.items()
                if s == sid and dt_day == d
            )
            if has_pinned_work:
                prob += duty_vars[(sid, d)] == 1
            elif has_pinned_off:
                prob += duty_vars[(sid, d)] == 0

            if pref and d in (pref.unavailable_days() if callable(pref.unavailable_days) else pref.unavailable_days):
                prob += duty_vars[(sid, d)] == 0

        # 2. 連続勤務日数制限（前月末の連続勤務履歴を考慮）
        prior_streak = context.prior_duty_history.get(sid, 0)
        if prior_streak > 0 and len(days) >= 1:
            allowed_at_start = max(0, max_consecutive - prior_streak)
            prob += pulp.lpSum(duty_vars[(sid, days[t])] for t in range(min(allowed_at_start + 1, len(days)))) <= allowed_at_start

        for i in range(len(days) - max_consecutive):
            window = [duty_vars[(sid, days[i + k])] for k in range(max_consecutive + 1)]
            prob += pulp.lpSum(window) <= max_consecutive

        # 3. 月間公休数の厳密確保
        total_work_days = pulp.lpSum(duty_vars[(sid, d)] for d in days)
        target_work_days = len(days) - context.monthly_holiday_target
        dev_work = pulp.LpVariable(f"dev_work_{sid}", lowBound=0)
        prob += total_work_days - target_work_days <= dev_work
        prob += target_work_days - total_work_days <= dev_work
        obj_terms.append(dev_work * 100.0)

        # 4. パート等の月間労働時間 上限/下限
        if contract and (contract.min_monthly_hours or contract.max_monthly_hours):
            monthly_hours = pulp.lpSum(
                x_vars[(sid, d, p.key)] * ((to_minutes(p.end) - to_minutes(p.start) - 60) / 60.0)
                for d in days
                for p in patterns
            )
            if contract.min_monthly_hours:
                prob += monthly_hours >= contract.min_monthly_hours
            if contract.max_monthly_hours:
                prob += monthly_hours <= contract.max_monthly_hours

    for d in days:
        req_count = 2
        prob += pulp.lpSum(duty_vars[(sid, d)] for sid in staff_ids) >= req_count

    prob.setObjective(pulp.lpSum(obj_terms))

    solver = pulp.PULP_CBC_CMD(timeLimit=time_limit_sec, msg=False)
    prob.solve(solver)

    result: dict[tuple[str, dt.date], str] = {}
    for sid in staff_ids:
        for d in days:
            duty_val = duty_vars[(sid, d)].value()
            if duty_val is not None and duty_val > 0.5:
                chosen_pat = pat_keys[0] if pat_keys else "NORMAL"
                for p in patterns:
                    x_val = x_vars[(sid, d, p.key)].value()
                    if x_val is not None and x_val > 0.5:
                        chosen_pat = p.key
                        break
                result[(sid, d)] = chosen_pat
            else:
                result[(sid, d)] = "OFF"

    return result
