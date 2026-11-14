"""差分レビュー・提案適用ワークフロー (Diff Review) のテスト。"""

import datetime as dt
import pytest
from sqlmodel import Session, select

from database import engine
from shift_schedule.db_models import ShiftPlanCells, ShiftPlanProposals, ShiftPlans, ShiftSolveJobs
from shift_schedule.services.diff_review import (
    apply_proposal,
    compute_plan_diff,
    create_proposal,
    reject_proposal,
)


def test_compute_plan_diff_accuracy():
    """ADDED, REMOVED, MODIFIED, UNCHANGED の差分計算精度を検証。"""
    d1 = dt.date(2026, 11, 1)

    existing = [
        ShiftPlanCells(plan_id=1, staff_user_id="s1", target_date=d1, slot_label="09:00", cell_state="WORK"),
        ShiftPlanCells(plan_id=1, staff_user_id="s2", target_date=d1, slot_label="09:00", cell_state="WORK"),
        ShiftPlanCells(plan_id=1, staff_user_id="s3", target_date=d1, slot_label="09:00", cell_state="OFF"),
        ShiftPlanCells(plan_id=1, staff_user_id="s4", target_date=d1, slot_label="09:00", cell_state="WORK"),
    ]

    proposals = [
        # s1: WORK -> WORK (UNCHANGED)
        ShiftPlanCells(plan_id=1, staff_user_id="s1", target_date=d1, slot_label="09:00", cell_state="WORK"),
        # s2: WORK -> BREAK (MODIFIED)
        ShiftPlanCells(plan_id=1, staff_user_id="s2", target_date=d1, slot_label="09:00", cell_state="BREAK"),
        # s3: OFF -> WORK (ADDED)
        ShiftPlanCells(plan_id=1, staff_user_id="s3", target_date=d1, slot_label="09:00", cell_state="WORK"),
        # s4: WORK -> OFF (REMOVED)
        ShiftPlanCells(plan_id=1, staff_user_id="s4", target_date=d1, slot_label="09:00", cell_state="OFF"),
    ]

    diff = compute_plan_diff(existing, proposals)
    summary = diff["summary"]

    assert summary["unchanged_count"] == 1
    assert summary["modified_count"] == 1
    assert summary["added_count"] == 1
    assert summary["removed_count"] == 1
    assert summary["affected_staff_count"] == 3
    assert set(summary["affected_staff_ids"]) == {"s2", "s3", "s4"}


def test_proposal_lifecycle_and_pin_protection():
    """提案の作成 -> 承認コミット（固定セル保護確認） -> 破棄ライフサイクルの検証。"""
    from models import User
    with Session(engine) as session:
        users = session.exec(select(User)).all()
        assert len(users) >= 2
        u1_id = users[0].id.hex
        u2_id = users[1].id.hex

        plan = ShiftPlans(target_month="2026-11", status="draft", staffing_standard_key="福岡市")
        session.add(plan)
        session.commit()
        session.refresh(plan)

        job = ShiftSolveJobs(plan_id=plan.id, status="succeeded")
        session.add(job)
        session.commit()
        session.refresh(job)

        d1 = dt.date(2026, 11, 1)

        # 既存セル: 1つは手動固定 (is_pinned=True)
        pinned_cell = ShiftPlanCells(
            plan_id=plan.id,
            staff_user_id=u1_id,
            target_date=d1,
            slot_label="08:30",
            cell_state="WORK",
            is_pinned=True,
        )
        unpinned_cell = ShiftPlanCells(
            plan_id=plan.id,
            staff_user_id=u2_id,
            target_date=d1,
            slot_label="08:30",
            cell_state="OFF",
            is_pinned=False,
        )
        session.add(pinned_cell)
        session.add(unpinned_cell)
        session.commit()

        # ソルバー提案: u1 を OFF にしようとし、u2 を WORK にしようとする
        proposal_cells = [
            ShiftPlanCells(
                plan_id=plan.id,
                staff_user_id=u1_id,
                target_date=d1,
                slot_label="08:30",
                cell_state="OFF",
            ),
            ShiftPlanCells(
                plan_id=plan.id,
                staff_user_id=u2_id,
                target_date=d1,
                slot_label="08:30",
                cell_state="WORK",
            ),
        ]

        # 1. 提案作成
        proposal = create_proposal(
            session=session,
            plan_id=plan.id,
            job_id=job.id,
            proposal_cells=proposal_cells,
            score_dict={"hard_score": 0, "soft_score": -100.0},
        )
        assert proposal.status == "pending"
        assert proposal.hard_score == 0

        # 2. 提案承認・適用
        applied_count = apply_proposal(session, proposal.id)
        assert applied_count == 1  # u2 のみ適用（u1 は固定のためスキップ）

        # 本番セルの確認
        final_cells = session.exec(
            select(ShiftPlanCells).where(ShiftPlanCells.plan_id == plan.id)
        ).all()
        cells_map = {(c.staff_user_id, c.slot_label): c.cell_state for c in final_cells}

        # 固定セル u1 は WORK のまま維持されていること！
        assert cells_map[(u1_id, "08:30")] == "WORK"
        # 未固定セル u2 は提案通り WORK に更新されていること！
        assert cells_map[(u2_id, "08:30")] == "WORK"

        # 提案ステータスが accepted になっていること
        session.refresh(proposal)
        assert proposal.status == "accepted"

        # 3. 別の提案を作って破棄（Reject）を検証
        prop2 = create_proposal(
            session=session,
            plan_id=plan.id,
            job_id=job.id,
            proposal_cells=proposal_cells,
        )
        assert prop2.status == "pending"
        reject_proposal(session, prop2.id)
        session.refresh(prop2)
        assert prop2.status == "rejected"

        # クリーンアップ
        session.delete(proposal)
        session.delete(prop2)
        for c in final_cells:
            session.delete(c)
        session.commit()
        session.delete(job)
        session.commit()
        session.delete(plan)
        session.commit()
