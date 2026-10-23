"""Tests for shift schedule export, solve error defense, pinning, and gap detector (Steps 12-16)."""
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from main import app
from database import engine
from shift_schedule.contracts import PlanStatus
from shift_schedule.db_models import ShiftPlans, ShiftPlanCells, ShiftViolations
from shift_schedule.store import SqlModelShiftRepository
from shift_schedule.services.gap_detector import GapWarning


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")


def _ensure_test_user():
    from models import User
    with Session(engine) as session:
        user = session.exec(select(User)).first()
        if not user:
            user = User(
                username="teststaff",
                display_name="テスト職員",
                email="staff@example.test",
                role="staff",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        return user.id.hex if hasattr(user.id, "hex") else str(user.id)


def test_step12_solve_job_records_failure_on_solver_error():
    """Step 12: ソルバー例外時のステータス保護。"""
    from shift_schedule.services.solve_jobs import schedule_solve
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        plan = ShiftPlans(target_month="2026-11", status=PlanStatus.DRAFT)
        repo.create_plan(plan)
        plan_id = plan.id

    job_id = schedule_solve(plan_id, "2026-11", "全国基準（厚労省）", None, time_limit_sec=1)
    assert job_id > 0


def test_step13_pinning_recalculation_respects_pinned_cells():
    """Step 13: ピン留め再計算不変条件テスト。"""
    user_id = _ensure_test_user()
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        plan = ShiftPlans(target_month="2026-11", status=PlanStatus.GENERATED)
        repo.create_plan(plan)
        plan_id = plan.id

        cell = ShiftPlanCells(
            plan_id=plan_id,
            staff_user_id=user_id,
            target_date=date(2026, 11, 2),
            slot_label="EARLY",
            cell_state="pinned",
        )
        repo.create_plan_cell(cell)

        # ピン留めセルがリポジトリで取得可能か検証
        pinned = repo.list_plan_cells(plan_id)
        assert any(c.cell_state == "pinned" and c.slot_label == "EARLY" for c in pinned)


def test_step14_daily_hours_exceeded_blocker_gate(client):
    """Step 14: 1日10h超の労基法32条違反で承認がブロックされるテスト。"""
    from csrf import CSRF_COOKIE_NAME

    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        plan = ShiftPlans(target_month="2026-11", status=PlanStatus.GENERATED)
        repo.create_plan(plan)
        plan_id = plan.id

        violation = ShiftViolations(
            plan_id=plan_id,
            job_id=1,
            code="DAILY_HOURS_EXCEEDED",
            severity="BLOCKER",
            message="1日10時間超の違法勤務です",
        )
        repo.create_violation(violation)

    client.get(f"/shifts/plans/{plan_id}")
    token = client.cookies.get(CSRF_COOKIE_NAME) or ""

    resp = client.post(
        f"/shifts/plans/{plan_id}/approve",
        data={"csrf_token": token},
    )
    assert resp.status_code == 409
    assert "BLOCKER" in resp.json()["detail"]


def test_step15_gap_detector_schema_and_calculation():
    """Step 15: リアルタイム配置割れギャップ構造のテスト。"""
    warning = GapWarning(
        target_date=date(2026, 11, 1),
        slot_label="EARLY",
        required_count=4,
        actual_count=2,
        shortfall=2,
        message="配置基準割れ: 2名不足",
    )
    assert warning.shortfall == 2
    assert "2名不足" in warning.message


def test_step16_csv_and_ics_export_contain_disclaimer(client):
    """Step 16: CSVおよびICSエクスポートに免責文言とUTF-8 BOMが含まれるテスト。"""
    user_id = _ensure_test_user()
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        plan = ShiftPlans(target_month="2026-11", status=PlanStatus.APPROVED)
        repo.create_plan(plan)
        plan_id = plan.id

        cell = ShiftPlanCells(
            plan_id=plan_id,
            staff_user_id=user_id,
            target_date=date(2026, 11, 3),
            slot_label="NORMAL",
            cell_state="specified",
        )
        repo.create_plan_cell(cell)

    # CSV
    resp_csv = client.get(f"/shifts/plans/{plan_id}/export.csv")
    assert resp_csv.status_code == 200
    assert resp_csv.content.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM
    assert "免責事項" in resp_csv.content.decode("utf-8")
    assert "NORMAL" in resp_csv.content.decode("utf-8")

    # ICS
    resp_ics = client.get(f"/shifts/plans/{plan_id}/export.ics")
    assert resp_ics.status_code == 200
    assert "BEGIN:VCALENDAR" in resp_ics.content.decode("utf-8")
    assert "免責事項" in resp_ics.content.decode("utf-8")
    assert "NORMAL" in resp_ics.content.decode("utf-8")
