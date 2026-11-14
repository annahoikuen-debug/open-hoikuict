"""ShiftSolveJobs の Timefold 互換スコアおよびスコア説明永続化テスト (改善案 1)."""

from __future__ import annotations

import json
from datetime import date

import pytest
from sqlmodel import Session, select

from database import engine
from shift_schedule.contracts import PlanStatus, SolveJobStatus
from shift_schedule.db_models import ShiftPlans, ShiftSolveJobs
from shift_schedule.services.solve_jobs import _run_solve_sync


def test_求解完了ジョブのstatsにShiftScoreとスコア説明がJSON永続化されること():
    """求解が完了したジョブの stats カラムに Hard/Soft スコアと ConstraintMatch が含まれることを検証する。"""
    with Session(engine) as session:
        # テスト用プランを作成
        plan = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.DRAFT,
            staffing_standard_key="福岡市",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        job = ShiftSolveJobs(
            plan_id=plan.id,
            status=SolveJobStatus.QUEUED,
            time_limit_sec=15,
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        # ワーカー同期実行
        _run_solve_sync(
            job_id=job.id,
            plan_id=plan.id,
            target_month="2026-11",
            staffing_standard_key="福岡市",
            time_limit_sec=15,
        )

        session.refresh(job)
        if job.status != SolveJobStatus.SUCCEEDED:
            print("JOB FAILED WITH ERROR:", job.error_message)
        assert job.status == SolveJobStatus.SUCCEEDED
        assert job.stats is not None

        stats_data = json.loads(job.stats)
        assert "score" in stats_data
        score = stats_data["score"]
        assert "hard_score" in score
        assert "soft_score" in score
        assert "is_feasible" in score
        assert "matches" in score

        # ハードスコアは数値（適法なら0、違反あれば負数）
        assert isinstance(score["hard_score"], int)
        assert isinstance(score["soft_score"], (int, float))
