"""Timefold 思想に基づくリアルタイム部分再計画サービス (Real-time Replan)。

当日の突発欠勤（病欠・インフルエンザ等）や急な希望休変更に対し、
月全体を解き直すことなく「対象日のみ」かつ「出勤可能職員のみ」を 1〜2秒で局所再計画し、
差分提案（Proposal）または即時反映を行う。
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from datetime import date
from typing import Any

from sqlmodel import Session, select

from database import engine
from models import (
    AttendanceRecord,
    AttendanceVerification,
    Child,
    ChildCareCertification,
    ChildStatus,
    User,
)
from shift_schedule.contracts import SolveJobStatus
from shift_schedule.db_models import (
    ChildPlannedArrivalDefaults,
    ShiftFacilityConstraintWeights,
    ShiftPlanCells,
    ShiftPlanningAudits,
    ShiftPlanProposals,
    ShiftPlans,
    ShiftSolveJobs,
    StaffContracts,
)
from shift_schedule.store import ShiftRepository, ShiftRepositoryDep
from time_utils import utc_now
from shift_schedule.services.diff_review import apply_proposal, create_proposal
from shift_schedule.services.weights import build_runtime_objective_weights
from shift_schedule.bridge import (
    build_child_plan,
    build_facility_settings,
    build_staff_member,
    build_staff_preferences,
)
from shift_schedule.services.duty_patterns import (
    get_active_duty_patterns,
    to_shiftai_patterns,
)
from vendor.nushift.shiftai.local_rules import build_standard
from vendor.nushift.shiftai.shift_patterns import default_patterns
from vendor.nushift.shiftai.standards import build_requirements
from shift_schedule.services.solver_manager import JobPriority, solver_manager
from vendor.nushift.shiftai.domain import (
    CellState,
    Contract,
    ObjectiveWeights,
    RequirementTable,
    SolveResult,
    SolveStatus,
    to_minutes,
)
from vendor.nushift.shiftai.local_search import ruin_and_recreate
from vendor.nushift.shiftai.monthly import MonthlySolveContext
from vendor.nushift.shiftai.solver import is_highs_available, snap_to_patterns, solve_shift


def execute_realtime_replan(
    session: Session,
    plan_id: int,
    target_dates: Sequence[date],
    absent_staff_user_ids: Sequence[str],
    time_limit_sec: int = 5,
    direct_apply: bool = False,
    requested_by_user_id: int | None = None,
) -> dict[str, Any]:
    """突発欠勤に対応する部分再計画を高速（1〜3秒）に実行する。"""
    plan = session.exec(select(ShiftPlans).where(ShiftPlans.id == plan_id)).first()
    if not plan:
        raise ValueError(f"Plan {plan_id} not found")

    target_dates_set = set(target_dates)
    absent_staff_set = {str(uid).replace("-", "") for uid in absent_staff_user_ids}

    # ジョブを作成（URGENT 優先度）
    job = ShiftSolveJobs(
        plan_id=plan_id,
        status=SolveJobStatus.RUNNING,
        priority=JobPriority.URGENT_REPLAN,
        requested_by_user_id=requested_by_user_id,
        requested_at=utc_now(),
        started_at=utc_now(),
        time_limit_sec=time_limit_sec,
    )
    session.add(job)

    # 監査ログを記録
    audit = ShiftPlanningAudits(
        actor_user_id=requested_by_user_id,
        target_plan_id=plan_id,
        action="REALTIME_REPLAN_STARTED",
        summary=f"突発欠勤再計画を開始 (欠勤 {len(absent_staff_set)}名, 日数 {len(target_dates)}日)",
    )
    session.add(audit)
    session.commit()
    session.refresh(job)

    # 既存セルを取得
    existing_cells = session.exec(
        select(ShiftPlanCells).where(ShiftPlanCells.plan_id == plan_id)
    ).all()

    # 固定辞書を作成
    # 1. target_dates 以外の日付はすべて現在状態で固定
    # 2. target_dates 内で absent_staff は全スロット OFF に固定
    # 3. target_dates 内で is_pinned=True のセルはそのまま固定
    fixed_assignments: dict[tuple[str, date, str], CellState] = {}
    warm_starts: dict[tuple[str, date, str], CellState] = {}

    for c in existing_cells:
        sid = str(c.staff_user_id).replace("-", "")
        key = (sid, c.target_date, c.slot_label)
        state_enum = CellState[c.cell_state] if c.cell_state in CellState.__members__ else CellState.OFF

        if c.target_date not in target_dates_set:
            # 対象外日は完全固定
            fixed_assignments[key] = state_enum
            warm_starts[key] = state_enum
        else:
            if sid in absent_staff_set:
                # 突発欠勤者は OFF 固定
                fixed_assignments[key] = CellState.OFF
                warm_starts[key] = CellState.OFF
            elif c.is_pinned:
                # 手動固定セルは保護
                fixed_assignments[key] = state_enum
                warm_starts[key] = state_enum
            else:
                # 再計画対象スロット（ウォームスタートとして既存解を活用）
                warm_starts[key] = state_enum

    # 施設設定と標準
    repo: ShiftRepository = ShiftRepositoryDep(session)
    facility_settings_row = repo.facility_settings()
    facility_settings = build_facility_settings(facility_settings_row)
    staffing_standard = build_standard(plan.staffing_standard_key, overrides={})

    # 職員・契約・希望
    min_target_date = min(target_dates)
    max_target_date = max(target_dates)

    users = session.exec(select(User)).all()
    placeable_staff = []
    day_preferences = {}
    for u in users:
        sm = build_staff_member(session, u)
        if sm is not None:
            placeable_staff.append(sm)
            day_preferences[str(u.id)] = build_staff_preferences(session, u)

    # 職員契約
    all_contracts = session.exec(
        select(StaffContracts).where(
            StaffContracts.effective_from <= max_target_date,
            (StaffContracts.effective_to.is_(None)) | (StaffContracts.effective_to >= min_target_date),
        )
    ).all()
    contracts_by_user = {str(c.staff_user_id): c for c in all_contracts}

    # パターン
    facility_setting_id = facility_settings_row.id if facility_settings_row else 1
    duty_patterns = get_active_duty_patterns(session, setting_id=facility_setting_id)
    shiftai_patterns = to_shiftai_patterns(duty_patterns) if duty_patterns else default_patterns()

    # 園児予定（本番データパイプライン完全準拠）
    candidate_children = session.exec(
        select(Child).where(
            Child.status == ChildStatus.enrolled,
            Child.enrollment_date <= max_target_date,
            (Child.withdrawal_date.is_(None)) | (Child.withdrawal_date >= min_target_date),
        )
    ).all()

    att_records = session.exec(
        select(AttendanceRecord).where(AttendanceRecord.attendance_date.in_(list(target_dates)))
    ).all()
    att_map: dict[tuple[int, date], AttendanceRecord] = {
        (ar.child_id, ar.attendance_date): ar for ar in att_records if ar.child_id is not None
    }

    verif_records = session.exec(
        select(AttendanceVerification).where(AttendanceVerification.target_date.in_(list(target_dates)))
    ).all()
    verif_map: dict[tuple[int, date], AttendanceVerification] = {
        (vr.child_id, vr.target_date): vr for vr in verif_records if vr.child_id is not None
    }

    all_defaults = session.exec(
        select(ChildPlannedArrivalDefaults).where(
            ChildPlannedArrivalDefaults.effective_from <= max_target_date,
            (ChildPlannedArrivalDefaults.effective_to.is_(None))
            | (ChildPlannedArrivalDefaults.effective_to >= min_target_date),
        )
    ).all()
    defaults_by_child: dict[int, list[ChildPlannedArrivalDefaults]] = {}
    for d in all_defaults:
        defaults_by_child.setdefault(d.child_id, []).append(d)

    all_certs = session.exec(
        select(ChildCareCertification).where(
            ChildCareCertification.is_active == True,  # noqa: E712
            ChildCareCertification.effective_from <= max_target_date,
        ).order_by(ChildCareCertification.effective_from.desc(), ChildCareCertification.id.desc())
    ).all()
    certs_by_child: dict[int, list[ChildCareCertification]] = {}
    for c in all_certs:
        certs_by_child.setdefault(c.child_id, []).append(c)

    day_plans = []
    for day_date in target_dates:
        active_kids = [
            c
            for c in candidate_children
            if c.enrollment_date <= day_date
            and (c.withdrawal_date is None or c.withdrawal_date > day_date)
        ]
        for child in active_kids:
            attendance_record = att_map.get((child.id, day_date)) if child.id else None
            planned_default = None
            child_defs = defaults_by_child.get(child.id, []) if child.id else []
            for cd in child_defs:
                if cd.effective_from <= day_date and (
                    cd.effective_to is None or cd.effective_to >= day_date
                ):
                    planned_default = cd
                    break
            effective_cert = None
            child_certs = certs_by_child.get(child.id, []) if child.id else []
            for cc in child_certs:
                if cc.effective_from <= day_date and (
                    cc.effective_to is None or cc.effective_to >= day_date
                ):
                    effective_cert = cc
                    break

            cp = build_child_plan(
                session,
                child,
                day_date,
                attendance_record=attendance_record,
                planned_arrival_default=planned_default,
                certification=effective_cert,
                verification=verif_map.get((child.id, day_date)),
            )
            if cp is not None:
                day_plans.append(cp)

    requirements = build_requirements(
        children=day_plans,
        days=list(target_dates),
        standard=staffing_standard,
        day_open=facility_settings.day_open if facility_settings else dt.time(7, 30),
        day_close=facility_settings.day_close if facility_settings else dt.time(19, 30),
    )

    # 園別制約重みの注入 (Timefold: Runtime Constraint Weights)
    weights = build_runtime_objective_weights(session, facility_id=facility_setting_id)

    # 対象日スライス求解の実行
    solver_name = "HiGHS" if is_highs_available() else "PULP_CBC_CMD"

    sub_res = solve_shift(
        day_plans,
        staff=placeable_staff,
        requirements=requirements,
        preferences=day_preferences,
        weights=weights,
        settings=facility_settings,
        fixed_assignments=fixed_assignments,
        time_limit_sec=time_limit_sec,
        solver_name=solver_name,
        warm_start=True,
        warm_start_assignments=warm_starts,
        patterns=shiftai_patterns,
        pattern_mode=True,
        standard=staffing_standard,
    )

    if shiftai_patterns and sub_res.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE):
        sub_res, _ = snap_to_patterns(
            sub_res,
            shiftai_patterns,
            requirements=requirements,
            preferences=day_preferences,
            staff=placeable_staff,
            settings=facility_settings,
        )

    # Timefold 思想: 解なし・タイムアウト時の局所探索自動フォールバック
    if sub_res.status not in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE) or not sub_res.shift_days:
        try:
            ls_res = ruin_and_recreate(
                initial_result=sub_res,
                requirements=requirements,
                staff=placeable_staff,
                preferences=day_preferences,
                standard=staffing_standard,
                settings=facility_settings,
                fixed_assignments=fixed_assignments,
                patterns=shiftai_patterns,
                weights=weights,
            )
            if ls_res.shift_days:
                sub_res = ls_res
        except Exception as e:
            sub_res.messages.append(f"Local search fallback error: {e}")

    # 求解結果をセルに変換
    proposal_cells: list[ShiftPlanCells] = []
    # まず対象外の既存セルを引き継ぎ
    for c in existing_cells:
        if c.target_date not in target_dates_set:
            proposal_cells.append(c)

    # 次に対象日の新解を追加
    for sd in getattr(sub_res, "shift_days", []):
        for sid_raw, slot_dict in sd.assignments.items():
            sid_str = str(sid_raw)
            try:
                from uuid import UUID
                sid_clean = UUID(sid_str).hex
            except (ValueError, AttributeError):
                sid_clean = sid_str

            for slot_label, cell_state in slot_dict.items():
                st_val = getattr(cell_state, "name", str(cell_state))
                proposal_cells.append(
                    ShiftPlanCells(
                        plan_id=plan_id,
                        staff_user_id=sid_clean,
                        target_date=sd.day,
                        slot_label=slot_label,
                        cell_state=st_val,
                        is_pinned=False,
                    )
                )

    score_dict = {}
    if getattr(sub_res, "score", None):
        try:
            score_dict = sub_res.score.to_dict()
        except Exception:
            pass

    # 提案を作成
    proposal = create_proposal(
        session=session,
        plan_id=plan_id,
        job_id=job.id,
        proposal_cells=proposal_cells,
        score_dict=score_dict,
    )

    job.status = SolveJobStatus.SUCCEEDED
    job.finished_at = utc_now()
    import json
    job.stats = json.dumps({
        "mode": "realtime_replan",
        "target_dates": [d.isoformat() for d in target_dates],
        "absent_staff": list(absent_staff_set),
        "proposal_id": proposal.id,
        "score": score_dict,
    }, ensure_ascii=False)
    session.add(job)

    # 監査ログを記録
    audit = ShiftPlanningAudits(
        actor_user_id=requested_by_user_id,
        target_plan_id=plan_id,
        action="REALTIME_REPLAN_COMPLETED",
        summary=f"突発欠勤再計画を完了 (欠勤 {len(absent_staff_set)}名, 日数 {len(target_dates)}日)",
    )
    session.add(audit)
    session.commit()

    applied_count = 0
    if direct_apply:
        applied_count = apply_proposal(session, proposal.id)

    return {
        "job_id": job.id,
        "proposal_id": proposal.id,
        "status": proposal.status,
        "target_dates": [d.isoformat() for d in target_dates],
        "absent_staff_count": len(absent_staff_set),
        "direct_applied": direct_apply,
        "applied_count": applied_count,
        "diff_summary": json.loads(proposal.diff_summary) if proposal.diff_summary else {},
    }
