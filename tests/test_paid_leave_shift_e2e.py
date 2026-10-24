"""Step 23: E2E test - paid leave application to shift solver OFF assignment.

職員が有給申請 → 園長承認 → 対象週のシフト自動計算実行 →
該当職員の対象日が「公休（OFF）」として割り当てられる一連の流れを検証する。
"""
from datetime import date, time
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from csrf import CSRF_COOKIE_NAME
from database import engine
from main import app
from models import StaffPaidLeave, StaffPaidLeaveRequest, User
from shift_schedule.contracts import PlanStatus
from shift_schedule.db_models import (
    ShiftFacilitySettings,
    ShiftPlanCells,
    ShiftPlans,
    StaffContracts,
    StaffQualifications,
)
from shift_schedule.services.solve_jobs import _run_solve_sync
from shift_schedule.store import SqlModelShiftRepository


@pytest.fixture
def client():
    return TestClient(app, base_url="https://testserver")


def test_paid_leave_results_in_off_slot_in_generated_shift(client):
    from database import create_db_and_tables
    create_db_and_tables()

    # 1. ユーザー作成
    user_id = uuid4()
    with Session(engine) as session:
        user = User(
            id=user_id,
            email=f"e2e_staff_{user_id.hex[:6]}@example.com",
            display_name="有給テスト職員",
            role="staff",
            is_active=True,
        )
        session.add(user)

        # 資格と雇用契約
        qual = StaffQualifications(
            staff_user_id=user_id.hex,
            role="保育士",
            effective_from=date(2026, 4, 1),
        )
        session.add(qual)

        contract = StaffContracts(
            staff_user_id=user_id.hex,
            employment_type="正職員",
            weekly_hours=40.0,
            daily_hours=8.0,
            effective_from=date(2026, 4, 1),
        )
        session.add(contract)

        # ユーザーを先にコミットして外部キー制約を満たす
        session.commit()

        # 有給台帳
        leave = StaffPaidLeave(
            staff_user_id=user_id,
            granted_date=date(2026, 4, 1),
            granted_days=10.0,
            used_days=0.0,
            expires_on=date(2028, 3, 31),
        )
        session.add(leave)
        session.commit()

        # 施設設定（シフト求解用）
        repo = SqlModelShiftRepository(session)
        fs = repo.facility_settings()
        if fs is None:
            fs = ShiftFacilitySettings(
                day_open=time(7, 0),
                day_close=time(19, 0),
                granularity_min=30,
                capacity=30,
                staffing_standard_key="全国基準（厚労省）",
                min_two_staff_rule=True,
            )
            session.add(fs)
            session.commit()

    from auth import Role, StaffUser, get_current_staff_user

    # 2. 有給申請（2026-11-04）: 一般職員として申請
    target_leave_date = date(2026, 11, 4)
    staff_principal = StaffUser(role=Role.CAN_EDIT, name="有給テスト職員", user_id=user_id)
    app.dependency_overrides[get_current_staff_user] = lambda: staff_principal

    try:
        client.get("/paid-leave")
        csrf_token = client.cookies.get(CSRF_COOKIE_NAME) or ""

        resp = client.post(
            "/paid-leave/requests",
            data={
                "csrf_token": csrf_token,
                "staff_user_id": str(user_id),
                "target_date": target_leave_date.isoformat(),
                "days": "1.0",
                "reason": "私用のため有給取得",
            },
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # 3. 園長承認: 管理者として承認
        admin_principal = StaffUser(role=Role.ADMIN, name="園長", user_id=uuid4())
        app.dependency_overrides[get_current_staff_user] = lambda: admin_principal

        with Session(engine) as session:
            req = session.exec(
                select(StaffPaidLeaveRequest).where(
                    StaffPaidLeaveRequest.staff_user_id == user_id,
                    StaffPaidLeaveRequest.target_date == target_leave_date,
                )
            ).first()
            assert req is not None
            req_id = req.id

        client.get("/paid-leave")
        csrf_token = client.cookies.get(CSRF_COOKIE_NAME) or ""
        resp_approve = client.post(
            f"/paid-leave/requests/{req_id}/approve",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert resp_approve.status_code == 303
    finally:
        app.dependency_overrides.pop(get_current_staff_user, None)

    # 4. 対象月（2026-11）のシフトプランを作成
    from shift_schedule.db_models import ShiftSolveJobs
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        plan = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.DRAFT,
            staffing_standard_key="全国基準（厚労省）",
        )
        repo.create_plan(plan)
        plan_id = plan.id

        job = ShiftSolveJobs(plan_id=plan_id, status="queued")
        repo.create_solve_job(job)
        job_id = job.id

    # 5. シフト同期求解ワーカーを実行
    _run_solve_sync(
        job_id=job_id,
        plan_id=plan_id,
        target_month="2026-11",
        staffing_standard_key="全国基準（厚労省）",
        time_limit_sec=5,
    )

    # 6. 生成されたセルの検証
    # 有給申請日（2026-11-04）の職員セルの cell_state がすべて OFF であること
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        cells = repo.list_plan_cells(plan_id)
        target_uids = {user_id.hex, str(user_id)}
        staff_cells_on_leave_day = [
            c for c in cells
            if c.staff_user_id in target_uids and c.target_date == target_leave_date
        ]

        assert len(staff_cells_on_leave_day) > 0, "求解結果に該当日のセルが生成されていること"
        for c in staff_cells_on_leave_day:
            # shiftai の CellState.OFF は 'OFF'
            assert c.cell_state == "OFF", f"有給申請日 {c.target_date} {c.slot_label} は OFF でなければならないが {c.cell_state}"
