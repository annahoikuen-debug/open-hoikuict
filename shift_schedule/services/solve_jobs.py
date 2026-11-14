"""Shift schedule solve job service.

ジョブキューとバックグラウンドワーカー。CBC 求解はリクエスト経路で
起動せず、専用ワーカーで非同期実行する（統合提案 2.7, 2.14）。

月次一括階層的求解（Hierarchical MILP）に対応：
- Stage 1: 月間日次パターン割り当て（連続勤務・公休・年休平準化・パート上限）
- Stage 2: 30分スロット詳細配置 & 休憩スタッガー最適化
- 前月末実績の境界バッファ考慮
- 園定義勤務パターンマスタ（ShiftDutyPatterns）連携
"""

from __future__ import annotations

import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from pulp import PULP_CBC_CMD
from sqlmodel import Session, select

from shiftai.domain import ObjectiveWeights
from shiftai.local_rules import build_standard
from shiftai.shift_patterns import default_patterns
from shiftai.solver import is_highs_available, snap_to_patterns, solve_shift  # noqa: F401
from shiftai.standards import build_requirements

from ..bridge import (
    build_child_plan,
    build_facility_settings,
    build_staff_member,
    build_staff_preferences,
)
from ..contracts import PlanStatus, SolveJobStatus
from ..db_models import (
    ChildPlannedArrivalDefaults,
    ShiftFacilityConstraintWeights,
    ShiftPlanCells,
    ShiftPlans,
    ShiftSolveJobs,
    ShiftViolations,
    StaffContracts,
)
from ..store import ShiftRepository, ShiftRepositoryDep
from .diff_review import create_proposal
from .solver_manager import JobPriority, solver_manager
from database import engine
from models import AttendanceRecord, Child, User
from time_utils import utc_now

from .duty_patterns import (
    calculate_monthly_holiday_target,
    get_active_duty_patterns,
    to_shiftai_patterns,
)
from .monthly_engine import MonthlySolveContext, solve_monthly_hierarchical
from .prior_history import get_prior_month_duty_streaks
from .solve_inputs import build_fixed_assignments

# 統合提案 2.7: CBC はリクエスト経路で起動しない。専用ワーカー。
_solve_executor = ThreadPoolExecutor(max_workers=min(4, (os.cpu_count() or 2)))
_solve_lock = threading.Lock()
_cbc_available: bool | None = None  # 起動時セルフチェック結果


def cbc_available() -> bool:
    """PULP_CBC_CMD が利用可能か。起動時または初回呼び出し時にチェック（後方互換性）。"""
    global _cbc_available
    if _cbc_available is None:
        try:
            solver = PULP_CBC_CMD()
            _cbc_available = bool(solver.available())
        except Exception:
            _cbc_available = False
    return _cbc_available


def solver_available() -> bool:
    """利用可能な MILP ソルバー（HiGHS または PULP_CBC_CMD）が存在するか判定する。"""
    return is_highs_available() or cbc_available()


def get_configured_solver_name() -> str:
    """環境設定 HOIKUICT_SHIFT_SOLVER（既定: auto）または利用可能性に基づきソルバー名を決定する。"""
    configured = (os.getenv("HOIKUICT_SHIFT_SOLVER") or "auto").strip().lower()
    if configured in ("highs", "highspy") and is_highs_available():
        return "HiGHS"
    if configured in ("cbc", "pulp_cbc_cmd") and cbc_available():
        return "PULP_CBC_CMD"
    if configured == "auto":
        if is_highs_available():
            return "HiGHS"
        if cbc_available():
            return "PULP_CBC_CMD"
    return "HiGHS" if is_highs_available() else "PULP_CBC_CMD"


def get_cbc_solver(time_limit_sec: int | None = None) -> PULP_CBC_CMD:
    """利用可能な CBC ソルバーインスタンスを生成する。利用不可の場合は RuntimeError。"""
    solver = PULP_CBC_CMD(timeLimit=time_limit_sec, msg=False)
    if not solver.available():
        raise RuntimeError(
            "CBCソルバー (PULP_CBC_CMD) がシステムで見つかりません。"
            "Linux環境では `apt-get install coinor-cbc`、Windows環境では pulp の同梱バイナリを確認してください。"
        )
    return solver


def _run_solve_sync(
    job_id: int,
    plan_id: int,
    target_month: str,
    staffing_standard_key: str,
    time_limit_sec: int,
) -> None:
    """同期求解ループ（ワーカースレッド内で実行）。月次一括階層的求解。"""
    session = Session(engine)
    repo: ShiftRepository = ShiftRepositoryDep(session)
    try:
        job = repo.get_job(job_id)
        if job is None:
            return

        if solver_manager.is_cancelled(job_id) or job.status == SolveJobStatus.CANCELLED:
            job.status = SolveJobStatus.CANCELLED
            job.finished_at = utc_now()
            repo.save_job(job)
            return

        token = solver_manager.get_token(job_id)

        job.status = SolveJobStatus.RUNNING
        job.started_at = utc_now()
        repo.save_job(job)

        plan = repo.get_plan(plan_id)
        if plan is None:
            job.status = SolveJobStatus.FAILED
            job.error_message = f"plan {plan_id} not found"
            job.finished_at = utc_now()
            repo.save_job(job)
            return

        # 施設設定
        facility_settings_row = repo.facility_settings()
        facility_settings = build_facility_settings(facility_settings_row)
        if facility_settings is None:
            job.status = SolveJobStatus.FAILED
            job.error_message = "施設設定が未登録です"
            job.finished_at = utc_now()
            repo.save_job(job)
            return

        staffing_standard = build_standard(
            plan.staffing_standard_key,
            overrides={},
        )

        # 園定義勤務パターンマスタの取得
        duty_patterns_rows = get_active_duty_patterns(session, setting_id=facility_settings_row.id or 1)
        shiftai_patterns = to_shiftai_patterns(duty_patterns_rows)
        if not shiftai_patterns:
            shiftai_patterns = default_patterns(facility_settings.day_open, facility_settings.day_close)

        # 対象月の全日付一覧を計算
        start_date = date.fromisoformat(target_month + "-01")
        if start_date.month == 12:
            end_date = date(start_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(start_date.year, start_date.month + 1, 1) - timedelta(days=1)

        all_days: list[date] = []
        cur = start_date
        while cur <= end_date:
            all_days.append(cur)
            cur += timedelta(days=1)

        # 既存の手動固定（ピン留め）セルを取得
        existing_cells = repo.list_plan_cells(plan_id)
        fixed_assignments = build_fixed_assignments(
            existing_cells,
            facility_settings_row,
            duty_patterns=duty_patterns_rows,
        )

        all_cells: list[ShiftPlanCells] = [
            ec for ec in existing_cells if getattr(ec, "is_pinned", False) or ec.cell_state == "pinned"
        ]
        all_violations: list[ShiftViolations] = []

        # 園児・職員一覧を事前取得（N+1クエリ完全解消）
        # 園児は月末日時点で在籍しうる園児を一括取得し、日ごとに判定
        from models import ChildStatus
        candidate_children = session.exec(
            select(Child).where(
                Child.status == ChildStatus.enrolled,
                Child.enrollment_date <= end_date,
                (Child.withdrawal_date.is_(None)) | (Child.withdrawal_date >= start_date),
            )
        ).all()
        users = session.exec(select(User)).all()

        # 全日登園記録の一括プリロード
        att_records = session.exec(
            select(AttendanceRecord).where(AttendanceRecord.attendance_date.in_(all_days))
        ).all()
        att_map: dict[tuple[int, date], AttendanceRecord] = {
            (ar.child_id, ar.attendance_date): ar for ar in att_records if ar.child_id is not None
        }

        # 当該月出欠確認の一括取得
        from models import AttendanceVerification
        verif_records = session.exec(
            select(AttendanceVerification).where(AttendanceVerification.target_date.in_(all_days))
        ).all()
        verif_map: dict[tuple[int, date], AttendanceVerification] = {
            (vr.child_id, vr.target_date): vr for vr in verif_records if vr.child_id is not None
        }

        all_defaults = session.exec(
            select(ChildPlannedArrivalDefaults).where(
                ChildPlannedArrivalDefaults.effective_from <= end_date,
                (ChildPlannedArrivalDefaults.effective_to.is_(None))
                | (ChildPlannedArrivalDefaults.effective_to >= start_date),
            )
        ).all()
        defaults_by_child: dict[int, list[ChildPlannedArrivalDefaults]] = {}
        for d in all_defaults:
            defaults_by_child.setdefault(d.child_id, []).append(d)

        # 園児全件の有効認定を一括取得
        from models import ChildCareCertification
        all_certs = session.exec(
            select(ChildCareCertification).where(
                ChildCareCertification.is_active == True,  # noqa: E712
                ChildCareCertification.effective_from <= end_date,
            ).order_by(ChildCareCertification.effective_from.desc(), ChildCareCertification.id.desc())
        ).all()
        certs_by_child: dict[int, list[ChildCareCertification]] = {}
        for c in all_certs:
            certs_by_child.setdefault(c.child_id, []).append(c)

        day_plans = []
        for day_date in all_days:
            # 当該日に在籍している園児のみ抽出
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

        # 職員プラン & 希望休（有給含む）
        day_staff = []
        day_preferences = {}
        contracts_map: dict[str, StaffContracts] = {}

        all_contracts = session.exec(
            select(StaffContracts).where(
                StaffContracts.effective_from <= end_date,
                (StaffContracts.effective_to.is_(None)) | (StaffContracts.effective_to >= start_date),
            )
        ).all()
        contracts_by_user = {str(c.staff_user_id): c for c in all_contracts}

        excluded_staff_members: list[User] = []
        for user in users:
            sm = build_staff_member(session, user)
            if sm is not None:
                day_staff.append(sm)
                day_preferences[str(user.id)] = build_staff_preferences(session, user)
                if str(user.id) in contracts_by_user:
                    contracts_map[str(user.id)] = contracts_by_user[str(user.id)]
            else:
                excluded_staff_members.append(user)

        # 資格または契約が無く除外された職員を ShiftViolations (WARNING) として記録
        for ex_u in excluded_staff_members:
            ex_name = ex_u.display_name or ex_u.email
            all_violations.append(
                ShiftViolations(
                    plan_id=plan_id,
                    target_date=start_date,
                    slot_label="all",
                    severity="WARNING",
                    code="STAFF_EXCLUDED",
                    message=f"職員「{ex_name}」は有効な資格または契約情報が登録されていないため、求解対象から除外されました。",
                )
            )

        # 休園日・祝日の一括取得
        from shift_schedule.db_models import ShiftFacilityClosedDays
        closed_rows = session.exec(
            select(ShiftFacilityClosedDays).where(
                ShiftFacilityClosedDays.setting_id == (facility_settings_row.id or 1),
                ShiftFacilityClosedDays.target_date.in_(all_days),
            )
        ).all()
        closed_days = [r.target_date for r in closed_rows if r.kind == "closed"]
        holiday_dates = [r.target_date for r in closed_rows if r.kind == "holiday"]

        # 全月間の必要人員テーブルを一括構築
        requirements = build_requirements(
            day_plans,
            all_days,
            staffing_standard,
            day_open=facility_settings.day_open,
            day_close=facility_settings.day_close,
            granularity_min=facility_settings.granularity_min,
            closed_days=closed_days,
            holiday_dates=holiday_dates,
        )

        # 前月最終週の連続勤務履歴（バッファ）取得
        prior_streaks = get_prior_month_duty_streaks(session, target_month, users)

        # 月間公休目標の計算
        monthly_holiday_target = calculate_monthly_holiday_target(
            session,
            target_month,
            setting_id=facility_settings_row.id or 1,
        )

        # 階層的月次求解コンテキスト構築
        context = MonthlySolveContext(
            target_month=target_month,
            all_days=all_days,
            staff=day_staff,
            contracts=contracts_map,
            preferences=day_preferences,
            patterns=shiftai_patterns,
            requirements=requirements,
            facility_settings=facility_settings,
            fixed_assignments=fixed_assignments,
            prior_duty_history=prior_streaks,
            monthly_holiday_target=monthly_holiday_target,
            children=day_plans,
            standard=staffing_standard,
        )

        # 月次一括階層的求解の実行
        def _on_solve_progress(p: dict) -> None:
            solver_manager.update_progress(job_id, p)

        try:
            result = solve_monthly_hierarchical(
                session=session,
                context=context,
                time_limit_sec=time_limit_sec,
                solver_name=get_configured_solver_name(),
                progress_callback=_on_solve_progress,
                cancellation_token=token,
                parallel_workers=min(4, os.cpu_count() or 1),
            )
        except Exception as exc:  # noqa: BLE001
            job.status = SolveJobStatus.FAILED
            job.error_message = str(exc)
            job.finished_at = utc_now()
            repo.save_job(job)
            return

        is_job_cancelled = solver_manager.is_cancelled(job_id) or getattr(result, "stats", {}).get("cancelled", False)

        # 結果をセルに変換
        for sd in getattr(result, "shift_days", []):
            for staff_id, slot_dict in getattr(sd, "assignments", {}).items():
                sid_str = str(staff_id)
                try:
                    from uuid import UUID
                    sid_clean = UUID(sid_str).hex
                except (ValueError, AttributeError):
                    sid_clean = sid_str

                for slot_label, cell_state in slot_dict.items():
                    state_val = getattr(cell_state, "name", str(cell_state))
                    cell = ShiftPlanCells(
                        plan_id=plan_id,
                        staff_user_id=sid_clean,
                        target_date=sd.day,
                        slot_label=slot_label,
                        cell_state=state_val,
                        is_pinned=False,
                    )
                    all_cells.append(cell)

        # 違反を記録
        for v in getattr(result, "violations", []):
            violation = ShiftViolations(
                plan_id=plan_id,
                job_id=job_id,
                code=getattr(v, "code", "UNKNOWN"),
                severity=getattr(getattr(v, "severity", None), "value", "INFO"),
                target_date=getattr(v, "target_date", None),
                slot_label=getattr(v, "slot_label", None),
                message=getattr(v, "message", ""),
            )
            all_violations.append(violation)

        score_dict = {}
        if getattr(result, "score", None):
            try:
                score_dict = result.score.to_dict()
            except Exception:
                pass

        # 差分提案テーブル (ShiftPlanProposals) に記録
        proposal_id = None
        try:
            proposal = create_proposal(
                session=session,
                plan_id=plan_id,
                job_id=job_id,
                proposal_cells=all_cells,
                score_dict=score_dict,
            )
            proposal_id = proposal.id
        except Exception:
            pass

        # 既存セル・違反を保存
        for c in all_cells:
            session.add(c)
        for v in all_violations:
            session.add(v)

        plan.status = PlanStatus.GENERATED
        plan.updated_at = utc_now()
        session.add(plan)

        import json

        job.status = SolveJobStatus.CANCELLED if is_job_cancelled else SolveJobStatus.SUCCEEDED
        job.finished_at = utc_now()
        stats_payload = {
            "cells": len(all_cells),
            "violations": len(all_violations),
            "backend_solver": get_configured_solver_name(),
            "score": score_dict,
            "proposal_id": proposal_id,
            "cancelled": is_job_cancelled,
        }
        job.stats = json.dumps(stats_payload, ensure_ascii=False)
        session.add(job)

        session.commit()

    except Exception as exc:  # noqa: BLE001
        try:
            session2 = Session(engine)
            repo2: ShiftRepository = ShiftRepositoryDep(session2)
            try:
                job = repo2.get_job(job_id)
                if job:
                    job.status = SolveJobStatus.FAILED
                    job.error_message = str(exc)
                    job.finished_at = utc_now()
                    repo2.save_job(job)
            finally:
                session2.close()
        except Exception:
            pass
    finally:
        session.close()


def schedule_solve(
    plan_id: int,
    target_month: str,
    staffing_standard_key: str,
    requested_by_user_id: int | None,
    time_limit_sec: int = 30,
    priority: int = JobPriority.INTERACTIVE,
) -> int:
    """求解ジョブをキューに登録し、ジョブIDを返す。優先度（1: URGENT, 2: INTERACTIVE, 3: BATCH）を指定可能。"""
    with Session(engine) as session:
        active_job = session.exec(
            select(ShiftSolveJobs).where(
                ShiftSolveJobs.plan_id == plan_id,
                ShiftSolveJobs.status.in_([SolveJobStatus.QUEUED, SolveJobStatus.RUNNING]),
            )
        ).first()
        if active_job is not None:
            raise RuntimeError(f"Plan {plan_id} has an active solve job ({active_job.id})")

    session = Session(engine)
    repo: ShiftRepository = ShiftRepositoryDep(session)
    try:
        job = ShiftSolveJobs(
            plan_id=plan_id,
            status=SolveJobStatus.QUEUED,
            priority=priority,
            requested_by_user_id=requested_by_user_id,
            requested_at=utc_now(),
            time_limit_sec=time_limit_sec,
        )
        repo.create_solve_job(job)
        job_id = job.id
        solver_manager.register_job(job_id)
    finally:
        session.close()

    _solve_executor.submit(process_next_solve_job)
    return job_id


def process_next_solve_job() -> bool:
    """優先度付きキュー（PriorityQueue）順に QUEUED ジョブを取得して求解を実行する。"""
    with _solve_lock:
        with Session(engine) as session:
            next_job = session.exec(
                select(ShiftSolveJobs)
                .where(ShiftSolveJobs.status == SolveJobStatus.QUEUED)
                .order_by(ShiftSolveJobs.priority.asc(), ShiftSolveJobs.requested_at.asc())
            ).first()

            if next_job is None:
                return False

            job_id = next_job.id
            plan_id = next_job.plan_id
            time_limit_sec = next_job.time_limit_sec

            if solver_manager.is_cancelled(job_id):
                next_job.status = SolveJobStatus.CANCELLED
                next_job.finished_at = utc_now()
                next_job.error_message = "実行前にキャンセルされました"
                session.add(next_job)
                session.commit()
                return True

            plan = session.exec(select(ShiftPlans).where(ShiftPlans.id == plan_id)).first()
            if plan is None:
                next_job.status = SolveJobStatus.FAILED
                next_job.error_message = f"plan {plan_id} not found"
                next_job.finished_at = utc_now()
                session.add(next_job)
                session.commit()
                return True

            target_month = plan.target_month
            staffing_standard_key = plan.staffing_standard_key

            next_job.status = SolveJobStatus.RUNNING
            next_job.started_at = utc_now()
            session.add(next_job)
            session.commit()

        _run_solve_sync(
            job_id,
            plan_id,
            target_month,
            staffing_standard_key,
            time_limit_sec,
        )
        return True


def recover_stale_jobs() -> int:
    """起動時に未完了のまま残った RUNNING ジョブを FAILED に更新して回復する。"""
    recovered_count = 0
    with Session(engine) as session:
        stale_jobs = session.exec(
            select(ShiftSolveJobs).where(
                ShiftSolveJobs.status == SolveJobStatus.RUNNING,
            )
        ).all()
        for j in stale_jobs:
            j.status = SolveJobStatus.FAILED
            j.error_message = "サーバー再起動により求解処理が中断されました。再実行してください。"
            j.finished_at = utc_now()
            session.add(j)
            recovered_count += 1
        if recovered_count > 0:
            session.commit()
    return recovered_count


async def solve_worker_loop() -> None:
    """FastAPI lifespan バックグラウンドワーカー。DBキュー内の QUEUED ジョブを順次監視・実行する。"""
    while True:
        try:
            processed = await asyncio.to_thread(process_next_solve_job)
            if processed:
                await asyncio.sleep(1.0)
            else:
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(5.0)
