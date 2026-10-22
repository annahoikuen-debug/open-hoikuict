"""Tests for shift plan cell editing, approval gate, and gap detection."""
from __future__ import annotations

from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from main import app
from database import engine
from shift_schedule.contracts import PlanStatus
from shift_schedule.db_models import ShiftPlans, ShiftViolations
from shift_schedule.store import SqlModelShiftRepository


@pytest.fixture
def client():
    return TestClient(app)


def test_plans_cell_edit_and_pinned():
    from csrf import CSRF_COOKIE_NAME
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
        user_id = user.id.hex if hasattr(user.id, "hex") else str(user.id)

        repo = SqlModelShiftRepository(session)
        # Create test plan
        plan = ShiftPlans(target_month="2026-11", status=PlanStatus.DRAFT)
        repo.create_plan(plan)
        plan_id = plan.id

    client = TestClient(app, base_url="https://testserver")
    client.get(f"/shifts/plans/{plan_id}")
    token = client.cookies.get(CSRF_COOKIE_NAME) or ""

    # Edit cell
    resp = client.post(
        f"/shifts/plans/{plan_id}/cells",
        data={
            "csrf_token": token,
            "staff_user_id": user_id,
            "target_date": "2026-11-01",
            "slot_label": "EARLY",
            "cell_state": "pinned",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    # Check cell saved as pinned
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        cell = repo.get_plan_cell(plan_id, user_id, date(2026, 11, 1))
        assert cell is not None
        assert cell.slot_label == "EARLY"
        assert cell.cell_state == "pinned"


def test_plans_approve_blocked_when_blocker_violations():
    from csrf import CSRF_COOKIE_NAME

    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        plan = ShiftPlans(target_month="2026-12", status=PlanStatus.GENERATED)
        repo.create_plan(plan)
        plan_id = plan.id

        # Add BLOCKER violation
        violation = ShiftViolations(
            plan_id=plan_id,
            job_id=1,
            code="DAILY_HOURS_EXCEEDED",
            severity="BLOCKER",
            message="1日10時間超の違法勤務です",
        )
        repo.create_violation(violation)

    client = TestClient(app, base_url="https://testserver")
    client.get(f"/shifts/plans/{plan_id}")
    token = client.cookies.get(CSRF_COOKIE_NAME) or ""

    # Attempt approval
    resp = client.post(
        f"/shifts/plans/{plan_id}/approve",
        data={"csrf_token": token},
    )
    assert resp.status_code == 409
    assert "BLOCKER" in resp.json()["detail"]


def test_plans_approve_succeeds_when_no_blockers():
    from csrf import CSRF_COOKIE_NAME

    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        plan = ShiftPlans(target_month="2027-01", status=PlanStatus.GENERATED)
        repo.create_plan(plan)
        plan_id = plan.id

        # Add WARNING violation only
        violation = ShiftViolations(
            plan_id=plan_id,
            job_id=1,
            code="HOURS_IMBALANCE",
            severity="WARNING",
            message="勤務時間の偏りがあります",
        )
        repo.create_violation(violation)

    client = TestClient(app, base_url="https://testserver")
    client.get(f"/shifts/plans/{plan_id}")
    token = client.cookies.get(CSRF_COOKIE_NAME) or ""

    # Attempt approval
    resp = client.post(
        f"/shifts/plans/{plan_id}/approve",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        approved_plan = repo.get_plan(plan_id)
        assert approved_plan.status == PlanStatus.APPROVED

    # Edited cell on approved plan should now be blocked
    resp2 = client.post(
        f"/shifts/plans/{plan_id}/cells",
        data={
            "csrf_token": token,
            "staff_user_id": 1,
            "target_date": "2027-01-01",
            "slot_label": "OFF",
            "cell_state": "specified",
        },
    )
    assert resp2.status_code == 409
