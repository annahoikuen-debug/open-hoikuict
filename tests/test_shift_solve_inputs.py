"""Step 1-5: シフト求解入力、ピン留め契約、日ごと園児予定、ジョブ中断回復テスト。"""

from __future__ import annotations

from datetime import date
from sqlmodel import Session

from database import engine
from shift_schedule.contracts import PlanStatus, SolveJobStatus
from shift_schedule.db_models import ShiftPlanCells, ShiftPlans, ShiftSolveJobs
from shift_schedule.services.solve_inputs import (
    build_fixed_assignments,
    normalize_staff_id,
    resolve_slot_to_time_window,
)
from shift_schedule.services.solve_jobs import recover_stale_jobs
from shift_schedule.store import SqlModelShiftRepository
from shiftai.domain import CellState


def test_normalize_staff_id():
    """UUIDおよび文字列が小文字hex/文字列に正規化されること。"""
    raw_uuid = "a9ee02c0-8b94-4d4c-9356-03e7c446c8f1"
    assert normalize_staff_id(raw_uuid) == "a9ee02c08b944d4c935603e7c446c8f1"
    assert normalize_staff_id("user123") == "user123"


def test_resolve_slot_to_time_window():
    """区分名（EARLY, NORMAL, LATE）が時間帯ラベルに解決されること。"""
    assert resolve_slot_to_time_window("09:00-17:00") == ["09:00-17:00"]
    early_res = resolve_slot_to_time_window("EARLY")
    assert len(early_res) == 1
    assert "09:00" in early_res[0]


def test_build_fixed_assignments_contract():
    """build_fixed_assignments が (staff_id, date, slot_label) -> CellState を正しく生成すること。"""
    cells = [
        ShiftPlanCells(
            plan_id=1,
            staff_user_id="staff1",
            target_date=date(2026, 11, 2),
            slot_label="09:00-17:00",
            cell_state="WORK",
            is_pinned=True,
        ),
        ShiftPlanCells(
            plan_id=1,
            staff_user_id="staff2",
            target_date=date(2026, 11, 2),
            slot_label="09:00-17:00",
            cell_state="specified",
            is_pinned=False,  # ピン留めされていないセルは除外されるべき
        ),
        ShiftPlanCells(
            plan_id=1,
            staff_user_id="staff3",
            target_date=date(2026, 11, 3),
            slot_label="EARLY",
            cell_state="pinned",  # 過去の cell_state='pinned' 互換
        ),
    ]

    fixed = build_fixed_assignments(cells)
    # staff1 はピン留めされているので含まれる
    assert ("staff1", date(2026, 11, 2), "09:00-17:00") in fixed
    assert fixed[("staff1", date(2026, 11, 2), "09:00-17:00")] == CellState.WORK

    # staff2 は未ピン留めなので含まれない
    assert ("staff2", date(2026, 11, 2), "09:00-17:00") not in fixed

    # staff3 は過去互換で含まれる
    assert any(k[0] == "staff3" and k[1] == date(2026, 11, 3) for k in fixed)


def test_recover_stale_jobs():
    """再起動時に中断された QUEUED / RUNNING ジョブが FAILED に更新されること。"""
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        plan = ShiftPlans(target_month="2026-11", status=PlanStatus.DRAFT)
        repo.create_plan(plan)

        stale_job = ShiftSolveJobs(
            plan_id=plan.id,
            status=SolveJobStatus.RUNNING,
        )
        repo.create_solve_job(stale_job)
        job_id = stale_job.id

    count = recover_stale_jobs()
    assert count >= 1

    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        updated_job = repo.get_job(job_id)
        assert updated_job.status == SolveJobStatus.FAILED
        assert "中断" in (updated_job.error_message or "")
