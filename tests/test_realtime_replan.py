"""突発欠勤に対するリアルタイム部分再計画 (Real-time Replan) のテスト。"""

import datetime as dt
import pytest
from sqlmodel import Session, select

from database import engine
from models import User
from shift_schedule.contracts import SolveJobStatus
from shift_schedule.db_models import ShiftPlanCells, ShiftPlanProposals, ShiftPlans, ShiftSolveJobs
from shift_schedule.services.replan import execute_realtime_replan


def test_realtime_replan_handles_sudden_absence():
    """突発欠勤が発生した際、他日を固定したまま対象日のみ高速に再計画できることを検証。"""
    with Session(engine) as session:
        users = session.exec(select(User)).all()
        assert len(users) >= 3
        u1_id = users[0].id.hex
        u2_id = users[1].id.hex
        u3_id = users[2].id.hex

        plan = ShiftPlans(target_month="2026-11", status="draft", staffing_standard_key="福岡市")
        session.add(plan)
        session.commit()
        session.refresh(plan)

        day_past = dt.date(2026, 11, 1)    # 過去日（再計画対象外）
        day_target = dt.date(2026, 11, 2)  # 当日（突発欠勤発生日）

        # 既存セル: day_past は u1 が出勤
        c_past = ShiftPlanCells(
            plan_id=plan.id,
            staff_user_id=u1_id,
            target_date=day_past,
            slot_label="08:30",
            cell_state="WORK",
        )
        # day_target は u1（今日急病）が出勤予定だった
        c_target_u1 = ShiftPlanCells(
            plan_id=plan.id,
            staff_user_id=u1_id,
            target_date=day_target,
            slot_label="08:30",
            cell_state="WORK",
        )
        c_target_u2 = ShiftPlanCells(
            plan_id=plan.id,
            staff_user_id=u2_id,
            target_date=day_target,
            slot_label="08:30",
            cell_state="OFF",
        )
        session.add(c_past)
        session.add(c_target_u1)
        session.add(c_target_u2)
        session.commit()

        # 突発欠勤: u1 が欠勤
        result = execute_realtime_replan(
            session=session,
            plan_id=plan.id,
            target_dates=[day_target],
            absent_staff_user_ids=[u1_id],
            time_limit_sec=5,
            direct_apply=False,
        )

        assert result["status"] == "pending"
        assert result["absent_staff_count"] == 1
        assert "diff_summary" in result

        # 提案の確認
        prop = session.get(ShiftPlanProposals, result["proposal_id"])
        assert prop is not None
        assert prop.status == "pending"

        # クリーンアップ
        session.delete(prop)
        session.commit()
        cells = session.exec(select(ShiftPlanCells).where(ShiftPlanCells.plan_id == plan.id)).all()
        for c in cells:
            session.delete(c)
        session.commit()
        job = session.get(ShiftSolveJobs, result["job_id"])
        if job:
            session.delete(job)
        session.commit()
        session.delete(plan)
        session.commit()
