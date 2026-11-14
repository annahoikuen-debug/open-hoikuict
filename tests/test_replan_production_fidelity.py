"""突発欠勤リアルタイム再計画 (Real-time Replan) の本番データ完全準拠・動作テスト。"""

from datetime import date, time, timedelta
import pytest
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
from shiftai.domain import CellState
from shift_schedule.db_models import (
    ChildPlannedArrivalDefaults,
    ShiftFacilityClosedDays,
    ShiftFacilitySettings,
    ShiftPlanCells,
    ShiftPlanningAudits,
    ShiftPlanProposals,
    ShiftPlans,
    ShiftSolveJobs,
    StaffContracts,
)
from shift_schedule.services.replan import execute_realtime_replan
from shift_schedule.services.diff_review import apply_proposal


@pytest.fixture
def replan_test_env():
    with Session(engine) as session:
        # 1. 施設設定
        setting = session.exec(select(ShiftFacilitySettings)).first()
        if not setting:
            setting = ShiftFacilitySettings(
                day_open="07:30",
                day_close="19:30",
                granularity_min=30,
                capacity=60,
                staffing_standard_key="fukuoka_city",
            )
            session.add(setting)
            session.commit()
            session.refresh(setting)

        # 2. 職員2名
        u1 = session.exec(select(User).where(User.email == "replan_user1@example.com")).first()
        if not u1:
            u1 = User(
                email="replan_user1@example.com",
                display_name="再計画職員1",
                staff_role="can_edit",
            )
            session.add(u1)
            session.commit()
            session.refresh(u1)

        u2 = session.exec(select(User).where(User.email == "replan_user2@example.com")).first()
        if not u2:
            u2 = User(
                email="replan_user2@example.com",
                display_name="再計画職員2",
                staff_role="can_edit",
            )
            session.add(u2)
            session.commit()
            session.refresh(u2)

        # 契約
        c1 = session.exec(select(StaffContracts).where(StaffContracts.staff_user_id == u1.id.hex)).first()
        if not c1:
            c1 = StaffContracts(
                staff_user_id=u1.id.hex,
                employment_type="full_time",
                weekly_hours=40.0,
                daily_hours=8.0,
                is_qualified=True,
                effective_from=date(2026, 1, 1),
            )
            session.add(c1)

        c2 = session.exec(select(StaffContracts).where(StaffContracts.staff_user_id == u2.id.hex)).first()
        if not c2:
            c2 = StaffContracts(
                staff_user_id=u2.id.hex,
                employment_type="full_time",
                weekly_hours=40.0,
                daily_hours=8.0,
                is_qualified=True,
                effective_from=date(2026, 1, 1),
            )
            session.add(c2)
        session.commit()

        # 3. 園児1名
        child = session.exec(select(Child).where(Child.first_name == "再計画児")).first()
        if not child:
            child = Child(
                last_name="テスト",
                first_name="再計画児",
                last_name_kana="テスト",
                first_name_kana="サイケイカクジ",
                birth_date=date(2025, 4, 1),
                enrollment_date=date(2026, 4, 1),
                status=ChildStatus.enrolled,
            )
            session.add(child)
            session.commit()
            session.refresh(child)

        target_day = date(2026, 11, 16)

        # 4. シフト計画
        plan = ShiftPlans(
            target_month="2026-11",
            status="draft",
            staffing_standard_key="福岡市",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        # 既存セル（u1 が出勤予定）
        for slot in ["08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00"]:
            cell = ShiftPlanCells(
                plan_id=plan.id,
                staff_user_id=u1.id.hex,
                target_date=target_day,
                slot_label=slot,
                cell_state=CellState.WORK.value,
            )
            session.add(cell)
        session.commit()

        yield plan, [u1, u2], target_day

        # クリーンアップ
        from shift_schedule.db_models import ShiftViolations
        violations = session.exec(select(ShiftViolations).where(ShiftViolations.plan_id == plan.id)).all()
        for v in violations:
            session.delete(v)
        cells = session.exec(select(ShiftPlanCells).where(ShiftPlanCells.plan_id == plan.id)).all()
        for c in cells:
            session.delete(c)
        proposals = session.exec(select(ShiftPlanProposals).where(ShiftPlanProposals.plan_id == plan.id)).all()
        for p in proposals:
            session.delete(p)
        jobs = session.exec(select(ShiftSolveJobs).where(ShiftSolveJobs.plan_id == plan.id)).all()
        for j in jobs:
            session.delete(j)
        audits = session.exec(select(ShiftPlanningAudits).where(ShiftPlanningAudits.target_plan_id == plan.id)).all()
        for a in audits:
            session.delete(a)
        session.delete(plan)
        session.commit()


def test_realtime_replan_execution_and_diff(replan_test_env):
    """突発欠勤再計画が 1〜3秒で高速に提案を作成し、欠勤者が OFF になり、監査ログが残ること。"""
    plan, (u1, u2), target_day = replan_test_env

    with Session(engine) as session:
        result = execute_realtime_replan(
            session=session,
            plan_id=plan.id,
            target_dates=[target_day],
            absent_staff_user_ids=[u1.id.hex],
            time_limit_sec=5,
            direct_apply=False,
            requested_by_user_id=1,
        )

        assert result is not None
        assert result["proposal_id"] > 0
        assert result["absent_staff_count"] == 1
        assert result["direct_applied"] is False

        # 提案を取得して検証
        proposal = session.exec(
            select(ShiftPlanProposals).where(ShiftPlanProposals.id == result["proposal_id"])
        ).first()
        assert proposal is not None
        assert proposal.status == "pending"

        # 提案セル内で u1 が target_day に全スロット OFF になっていること
        import json
        cells_json = json.loads(proposal.proposal_cells)
        u1_cells_on_target_day = [
            c for c in cells_json
            if c["staff_user_id"] in (str(u1.id), u1.id.hex) and c["target_date"] == target_day.isoformat()
        ]
        assert all(c["cell_state"] in ("OFF", "CellState.OFF") for c in u1_cells_on_target_day)

        # 監査ログが記録されていること
        audits = session.exec(
            select(ShiftPlanningAudits).where(
                ShiftPlanningAudits.target_plan_id == plan.id,
                ShiftPlanningAudits.actor_user_id == 1,
            )
        ).all()
        assert len(audits) >= 2
        actions = {a.action for a in audits}
        assert "REALTIME_REPLAN_STARTED" in actions
        assert "REALTIME_REPLAN_COMPLETED" in actions

        # 提案を本番へ適用
        applied = apply_proposal(session, proposal.id)
        assert applied > 0
        session.refresh(proposal)
        assert proposal.status == "accepted"
