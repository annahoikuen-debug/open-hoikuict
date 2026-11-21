"""Test for Shift Schedule Diagnostics and Constraint Indictment Service.

検証内容:
1. 過剰制約計画（Overconstrained Planning）による不足コマ（Shortfalls）の診断
2. 制約起訴（Constraint Indictment）によるペナルティ分析とAIサジェスト生成
3. DBおよびAPI経由での診断レポート取得（GET /shifts/plans/{plan_id}/diagnostics）
"""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from database import engine, create_db_and_tables
from main import app
from models import User
from shift_schedule.contracts import PlanStatus
from shift_schedule.db_models import (
    ShiftPlans,
    ShiftSolveJobs,
    ShiftViolations,
    StaffShiftUnavailability,
)
from shift_schedule.services.diagnostics_service import (
    enrich_solve_job_with_diagnostics,
    generate_diagnostics_report,
    get_plan_diagnostics,
)
from vendor.nushift.shiftai.domain import Indictment, ShiftScore


@pytest.fixture
def test_client():
    from testing_helpers import authenticate_mock_staff
    from auth import Role

    c = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(c, role=Role.ADMIN)
    return c


def test_diagnostics_report_generation():
    """不足コマおよび制約起訴から自然言語サジェストが正しく生成されること。"""
    create_db_and_tables()

    uid1 = uuid4()
    with Session(engine) as session:
        user = User(
            id=uid1,
            email=f"diag_test_{uid1.hex[:6]}@example.com",
            display_name="佐藤保育士",
            role="staff",
            is_active=True,
        )
        session.add(user)
        session.commit()

        # 不在希望を登録
        unavail = StaffShiftUnavailability(
            staff_user_id=uid1.hex,
            target_date=date(2026, 11, 15),
            kind="希望休",
            status="approved",
            reason="私用のため",
        )
        session.add(unavail)
        session.commit()

        # モックの SolveResult を準備
        mock_shortfalls = [
            {
                "day": date(2026, 11, 15),
                "slot": "09:00-09:30",
                "needed": 2,
                "assigned": 1,
                "deficit": 1,
                "class_name": "1歳児",
            }
        ]
        mock_indictment = Indictment(
            staff_id=uid1.hex,
            day=date(2026, 11, 15),
            hard_penalty_count=1,
            soft_penalty_total=25.0,
            violations=["希望休と必要人員の衝突"],
        )
        mock_score = ShiftScore(
            hard_score=-1,
            medium_score=-100.0,
            soft_score=-25.0,
            indictments={(uid1.hex, date(2026, 11, 15)): mock_indictment},
        )
        mock_result = SimpleNamespace(
            overconstrained_shortfalls=mock_shortfalls,
            score=mock_score,
        )

        report = generate_diagnostics_report(
            result=mock_result,
            context=None,
            session=session,
        )

        assert report["is_feasible"] is False
        assert report["total_shortfall_slots"] == 1
        assert len(report["suggestions"]) >= 1

        first_sugg = report["suggestions"][0]
        assert "佐藤保育士" in first_sugg["description"]
        assert "2026-11-15" in first_sugg["description"]
        assert uid1.hex in first_sugg["action_staff_ids"]

        assert len(report["top_indicted_staff"]) >= 1
        assert report["top_indicted_staff"][0]["staff_user_id"] == uid1.hex


def test_diagnostics_enrich_and_save():
    """enrich_solve_job_with_diagnostics が ShiftViolations (BLOCKER) を正しく記録すること。"""
    create_db_and_tables()

    with Session(engine) as session:
        plan = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.DRAFT.value,
            staffing_standard_key="fukuoka_city",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        job = ShiftSolveJobs(
            plan_id=plan.id,
            status="running",
        )
        session.add(job)
        session.commit()
        session.refresh(job)

        mock_shortfalls = [
            {
                "day": date(2026, 11, 10),
                "slot": "14:00-14:30",
                "needed": 3,
                "assigned": 2,
                "deficit": 1,
            }
        ]
        mock_result = SimpleNamespace(
            overconstrained_shortfalls=mock_shortfalls,
            score=None,
        )

        diag = enrich_solve_job_with_diagnostics(
            session=session,
            job=job,
            result=mock_result,
            context=None,
            plan_id=plan.id,
        )

        import json

        job.stats = json.dumps({"diagnostics": diag}, ensure_ascii=False)
        session.add(job)
        session.commit()

        # ShiftViolations の検証
        violations = session.exec(
            select(ShiftViolations).where(
                ShiftViolations.plan_id == plan.id,
                ShiftViolations.code == "OVERCONSTRAINED_SHORTFALL",
            )
        ).all()

        assert len(violations) == 1
        assert violations[0].severity == "BLOCKER"
        assert "14:00-14:30" in violations[0].message

        # get_plan_diagnostics の検証
        fetched_diag = get_plan_diagnostics(session, plan.id)
        assert fetched_diag["total_shortfall_slots"] == 1


def test_diagnostics_api_endpoint(test_client):
    """GET /shifts/plans/{plan_id}/diagnostics エンドポイントが正常に動作すること。"""
    create_db_and_tables()

    with Session(engine) as session:
        plan = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.GENERATED.value,
            staffing_standard_key="fukuoka_city",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        import json

        job = ShiftSolveJobs(
            plan_id=plan.id,
            status="succeeded",
            stats=json.dumps(
                {
                    "diagnostics": {
                        "is_feasible": True,
                        "summary": "全配置基準を満たしています。",
                        "total_shortfall_slots": 0,
                        "shortfalls": [],
                        "suggestions": [],
                        "top_indicted_staff": [],
                    }
                }
            ),
        )
        session.add(job)
        session.commit()
        plan_id = plan.id

    resp = test_client.get(f"/shifts/plans/{plan_id}/diagnostics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_feasible"] is True
    assert "全配置基準を満たしています。" in data["summary"]
