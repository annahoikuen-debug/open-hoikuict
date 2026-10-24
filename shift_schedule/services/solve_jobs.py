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
from shiftai.standards import build_requirements

from ..bridge import (
    build_child_plan,
    build_facility_settings,
    build_staff_member,
    build_staff_preferences,
)
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

        # 既存の手動固定（ピン留め）セルを取得し、求解の固定条件に加える
        existing_cells = repo.list_plan_cells(plan_id)
        for ec in existing_cells:
            if ec.cell_state == "pinned":
                fixed_assignments[(str(ec.staff_user_id), ec.target_date.isoformat())] = ec.slot_label
                all_cells.append(ec)

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
                        AttendanceRecord.attendance_date == current,
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

            # 職員プラン & 希望休（有給含む）
            day_preferences = {}
            users = session.exec(select(User)).all()
            for user in users:
                sm = build_staff_member(session, user)
                if sm is not None:
                    day_staff.append(sm)
                    day_preferences[str(user.id)] = build_staff_preferences(session, user)

            # 週の日付一覧
            week_days_list = []
            tmp_d = current
            while tmp_d <= week_end:
                week_days_list.append(tmp_d)
                tmp_d += timedelta(days=1)

            requirements = build_requirements(
                day_plans,
                week_days_list,
                staffing_standard,
                day_open=facility_settings.day_open,
                day_close=facility_settings.day_close,
                granularity_min=facility_settings.granularity_min,
            )

            # 求解
            try:
                result = solve_shift(
                    children=day_plans,
                    staff=day_staff,
                    requirements=requirements,
                    preferences=day_preferences,
                    settings=facility_settings,
                    standard=staffing_standard,
                    fixed_assignments=fixed_assignments,
                    time_limit_sec=time_limit_sec,
                )
            except Exception as exc:  # noqa: BLE001
                job.status = SolveJobStatus.FAILED
                job.error_message = str(exc)
                job.finished_at = utc_now()
                repo.save_job(job)
                return

            # 結果をセルに変換
            # result.shift_days: 各日・各職員・各スロットの CellState (WORK, BREAK, OFF)
            for sd in getattr(result, "shift_days", []):
                for staff_id, slot_dict in getattr(sd, "assignments", {}).items():
                    # users.id が CHAR(32)（hex形式）の場合に対応
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
                        )
                        all_cells.append(cell)
                        fixed_assignments[(str(staff_id), sd.day, slot_label)] = cell_state

            # 違反を記録
            for v in getattr(result, "violations", []):
                violation = ShiftViolations(
                    plan_id=plan_id,
                    job_id=job_id,
                    code=getattr(v, "code", "UNKNOWN"),
                    severity=getattr(getattr(v, "severity", None), "value", "INFO"),
                    target_date=getattr(v, "day", None),
                    slot_label=getattr(getattr(v, "slot", None), "label", None),
                    staff_user_id=str(v.staff_id) if getattr(v, "staff_id", None) is not None else None,
                    message=getattr(v, "message", ""),
                )
                all_violations.append(violation)

            current = week_end + timedelta(days=1)

        # 既存の未固定セル・違反をクリアし、新結果を保存
        for ec in existing_cells:
            if ec.cell_state != "pinned":
                session.delete(ec)
        for old_v in repo.list_violations(plan_id):
            session.delete(old_v)
        session.commit()

        # セルを保存（ピン留めセルは既存のままなので新規生成セルのみ追加）
        for cell in all_cells:
            if cell.id is None:
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
