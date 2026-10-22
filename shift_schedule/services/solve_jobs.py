"""Shift schedule solve job service.

ジョブキューとバックグラウンドワーカー。CBC 求解はリクエスト経路で
起動せず、専用ワーカーで非同期実行する（統合提案 2.7, 2.14）。
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

from pulp import PULP_CBC_CMD
from sqlmodel import Session, select

from shiftai.local_rules import build_standard
from shiftai.solver import solve_shift

from ..bridge import build_child_plan, build_facility_settings, build_staff_member
from ..contracts import PlanStatus, SolveJobStatus
from ..db_models import (
    ShiftPlanCells,
    ShiftSolveJobs,
    ShiftViolations,
    ChildPlannedArrivalDefaults,
)
from ..store import ShiftRepository, ShiftRepositoryDep
from database import engine
from models import AttendanceRecord, Child, User
from time_utils import utc_now

# 統合提案 2.14: 計算単位は週（固定7日）。月一括求解は不可。
WEEK_DAYS = 7

# 統合提案 2.7: CBC はリクエスト経路で起動しない。専用ワーカー。
_solve_executor = ThreadPoolExecutor(max_workers=1)
_solve_lock = threading.Lock()
_cbc_available: bool | None = None  # 起動時セルフチェック結果


def cbc_available() -> bool:
    """PULP_CBC_CMD が利用可能か。起動時または初回呼び出し時にチェック。"""
    global _cbc_available
    if _cbc_available is None:
        try:
            solver = PULP_CBC_CMD()
            _cbc_available = bool(solver.available())
        except Exception:
            _cbc_available = False
    return _cbc_available


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
    """同期求解ループ（ワーカースレッド内で実行）。

    1 週間ずつ順に求解し、前週の結果を fixed_assignments として次週に渡す。
    """
    from shiftai.domain import ChildPlan, StaffMember

    session = Session(engine)
    repo: ShiftRepository = ShiftRepositoryDep(session)
    try:
        job = repo.get_job(job_id)
        if job is None:
            return
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

        # 対象月の各週を順に求解
        start_date = date.fromisoformat(target_month + "-01")
        # 月末を計算
        if start_date.month == 12:
            end_date = date(start_date.year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = date(start_date.year, start_date.month + 1, 1) - timedelta(days=1)

        all_cells: list[ShiftPlanCells] = []
        all_violations: list[ShiftViolations] = []
        fixed_assignments: dict[tuple[str, str], str] = {}  # (staff_id, date) -> slot_label

        current = start_date
        while current <= end_date:
            week_end = min(current + timedelta(days=WEEK_DAYS - 1), end_date)

            # 週内の各日を組み立て
            day_plans: list[ChildPlan] = []
            day_staff: list[StaffMember] = []

            # 園児プラン
            children = session.exec(select(Child)).all()
            for child in children:
                # その日の attendance_record を取得
                attendance_record = session.exec(
                    select(AttendanceRecord).where(
                        AttendanceRecord.child_id == child.id,
                        AttendanceRecord.target_date == current,
                    )
                ).first()
                # 既定登園時刻
                planned_default = session.exec(
                    select(ChildPlannedArrivalDefaults).where(
                        ChildPlannedArrivalDefaults.child_id == child.id,
                        (ChildPlannedArrivalDefaults.effective_to.is_(None))
                        | (ChildPlannedArrivalDefaults.effective_to >= current),
                        ChildPlannedArrivalDefaults.effective_from <= current,
                    )
                ).first()
                cp = build_child_plan(
                    session,
                    child,
                    current,
                    attendance_record=attendance_record,
                    planned_arrival_default=planned_default,
                )
                if cp is not None:
                    day_plans.append(cp)

            # 職員プラン
            users = session.exec(select(User)).all()
            for user in users:
                sm = build_staff_member(session, user)
                if sm is not None:
                    day_staff.append(sm)

            # 求解
            try:
                result = solve_shift(
                    settings=facility_settings,
                    standard=staffing_standard,
                    child_plans=day_plans,
                    staff_members=day_staff,
                    fixed_assignments=fixed_assignments,
                    time_limit_sec=time_limit_sec,
                )
            except Exception as exc:  # noqa: BLE001
                job.status = SolveJobStatus.FAILED
                job.error_message = str(exc)
                job.finished_at = utc_now()
                repo.save_job(job)
                return

            # 結果をセルに変換（簡易実装：staff_assignments から）
            # shiftai の solve_shift 戻り値の構造に合わせる
            for staff_assignment in getattr(result, "staff_assignments", []):
                staff_id = staff_assignment.get("staff_id", "")
                for day_assign in staff_assignment.get("assignments", []):
                    assign_date = day_assign.get("date")
                    slot_label = day_assign.get("slot_label", "")
                    cell = ShiftPlanCells(
                        plan_id=plan_id,
                        staff_user_id=int(staff_id) if staff_id.isdigit() else 0,
                        target_date=date.fromisoformat(assign_date) if assign_date else current,
                        slot_label=slot_label,
                        cell_state="specified",
                    )
                    all_cells.append(cell)
                    fixed_assignments[(staff_id, assign_date)] = slot_label

            # 違反を記録
            for v in getattr(result, "violations", []):
                violation = ShiftViolations(
                    plan_id=plan_id,
                    job_id=job_id,
                    code=v.get("code", "UNKNOWN"),
                    severity=v.get("severity", "INFO"),
                    target_date=date.fromisoformat(v.get("target_date")) if v.get("target_date") else None,
                    slot_label=v.get("slot_label"),
                    staff_user_id=int(v.get("staff_user_id")) if v.get("staff_user_id", "").isdigit() else None,
                    message=v.get("message", ""),
                )
                all_violations.append(violation)

            current = week_end + timedelta(days=1)

        # セルを保存
        for cell in all_cells:
            repo.create_plan_cell(cell)
        for v in all_violations:
            repo.create_violation(v)

        # プランステータス更新
        plan.status = PlanStatus.GENERATED
        repo.save_plan(plan)

        job.status = SolveJobStatus.SUCCEEDED
        job.finished_at = utc_now()
        job.stats = f"cells={len(all_cells)} violations={len(all_violations)}"
        repo.save_job(job)

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
) -> int:
    """求解ジョブをキューに登録し、ジョブIDを返す。"""
    session = Session(engine)
    repo: ShiftRepository = ShiftRepositoryDep(session)
    try:
        job = ShiftSolveJobs(
            plan_id=plan_id,
            status=SolveJobStatus.QUEUED,
            requested_by_user_id=requested_by_user_id,
            requested_at=utc_now(),
            time_limit_sec=time_limit_sec,
        )
        repo.create_solve_job(job)
        job_id = job.id
    finally:
        session.close()

    # ワーカーに投入（同期関数をスレッドプールで実行）
    _solve_executor.submit(
        _run_solve_sync,
        job_id,
        plan_id,
        target_month,
        staffing_standard_key,
        time_limit_sec,
    )
    return job_id


async def solve_worker_loop() -> None:
    """FastAPI lifespan バックグラウンドタスク。

    現状はスレッドプール経由で同期求解するだけだが、
    将来のジョブキュー（Redis/DBポーリング）への移行を見越して
    非同期関数として定義する。
    """
    # 現状の実装では solve_jobs をスレッドプールで直接実行するため、
    # このループはプレースホルダーとして待機し続ける。
    # 実際の求解は schedule_solve から _solve_executor に投入される。
    while True:
        await asyncio.sleep(3600)
