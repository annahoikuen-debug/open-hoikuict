"""SolverManager の優先度・キャンセル・進捗管理テスト。"""

import pytest
from sqlmodel import Session, select

from database import engine
from shift_schedule.contracts import SolveJobStatus
from shift_schedule.db_models import ShiftPlans, ShiftSolveJobs
from shift_schedule.services.solver_manager import JobPriority, solver_manager


@pytest.fixture
def test_plan_and_jobs():
    with Session(engine) as session:
        plan = ShiftPlans(
            target_month="2026-11",
            status="draft",
            staffing_standard_key="福岡市",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        # 3つの優先度でジョブを作成
        job_batch = ShiftSolveJobs(
            plan_id=plan.id,
            priority=JobPriority.BATCH_BACKGROUND,
            status=SolveJobStatus.QUEUED,
        )
        job_urgent = ShiftSolveJobs(
            plan_id=plan.id,
            priority=JobPriority.URGENT_REPLAN,
            status=SolveJobStatus.QUEUED,
        )
        job_interactive = ShiftSolveJobs(
            plan_id=plan.id,
            priority=JobPriority.INTERACTIVE,
            status=SolveJobStatus.QUEUED,
        )
        session.add(job_batch)
        session.add(job_urgent)
        session.add(job_interactive)
        session.commit()
        session.refresh(job_batch)
        session.refresh(job_urgent)
        session.refresh(job_interactive)

        yield plan, [job_urgent, job_interactive, job_batch]

        # クリーンアップ（ジョブを先に削除してコミットしてからプランを削除）
        for j in [job_urgent, job_interactive, job_batch]:
            db_j = session.get(ShiftSolveJobs, j.id)
            if db_j:
                session.delete(db_j)
        session.commit()
        db_p = session.get(ShiftPlans, plan.id)
        if db_p:
            session.delete(db_p)
        session.commit()


def test_priority_queue_order(test_plan_and_jobs):
    """優先度付きキューで URGENT (1) が BATCH (3) より先に取得されることを検証。"""
    _, jobs = test_plan_and_jobs
    with Session(engine) as session:
        fetched_jobs = session.exec(
            select(ShiftSolveJobs)
            .where(ShiftSolveJobs.id.in_([j.id for j in jobs]))
            .order_by(ShiftSolveJobs.priority.asc(), ShiftSolveJobs.requested_at.asc())
        ).all()

        priorities = [j.priority for j in fetched_jobs]
        assert priorities == [
            JobPriority.URGENT_REPLAN,
            JobPriority.INTERACTIVE,
            JobPriority.BATCH_BACKGROUND,
        ]


def test_cooperative_cancellation():
    """ジョブに対してキャンセル要求が正常に機能し、フラグが伝播することを検証。"""
    job_id = 99991
    token = solver_manager.register_job(job_id)
    assert not token.is_cancelled()
    assert not solver_manager.is_cancelled(job_id)

    # キャンセル実行
    solver_manager.cancel_job(job_id)
    assert token.is_cancelled()
    assert solver_manager.is_cancelled(job_id)

    # 進捗ステータスが CANCELLED になっていること
    prog = solver_manager.get_progress(job_id)
    assert prog.get("stage") == "CANCELLED"
    assert prog.get("is_cancelled") is True


def test_progress_tracking_and_reporting():
    """進捗更新がリアルタイムに反映され取得できることを検証。"""
    job_id = 99992
    solver_manager.register_job(job_id)

    solver_manager.update_progress(
        job_id,
        {
            "stage": "STAGE_2_SLOTS",
            "progress_percent": 65,
            "current_day": "2026-11-15",
            "total_days": 30,
        },
    )

    prog = solver_manager.get_progress(job_id)
    assert prog["stage"] == "STAGE_2_SLOTS"
    assert prog["progress_percent"] == 65
    assert prog["current_day"] == "2026-11-15"
