"""Tests for staff paid leave application, approval, and solver integration (Step 21 & Step 22)."""

import unittest
from datetime import date
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser, get_current_staff_user
from database import get_session
from models import StaffPaidLeave, StaffPaidLeaveRequest
from routers.paid_leave import router as paid_leave_router
from shift_schedule.bridge import build_staff_member, build_staff_preferences


class StaffPaidLeaveTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(paid_leave_router)

        self.staff_user_id = uuid4()
        self.staff_user = StaffUser(role=Role.CAN_EDIT, name="保育士A", user_id=self.staff_user_id)
        self.admin_user = StaffUser(role=Role.ADMIN, name="園長", user_id=uuid4())

        self.current_user = self.staff_user

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_current_user():
            return self.current_user

        self.app.dependency_overrides[get_session] = override_get_session
        self.app.dependency_overrides[get_current_staff_user] = override_current_user
        self.client = TestClient(self.app)

    def test_apply_and_approve_paid_leave_workflow(self):
        # 1. 有給台帳に10日付与をセット
        with Session(self.engine) as session:
            leave = StaffPaidLeave(
                staff_user_id=self.staff_user_id,
                granted_date=date(2026, 4, 1),
                granted_days=10.0,
                used_days=0.0,
                expires_on=date(2028, 3, 31),
            )
            session.add(leave)
            session.commit()

        # 2. 一般職員で有給申請 (2026-11-10)
        self.current_user = self.staff_user
        r_apply = self.client.post(
            "/paid-leave/requests",
            data={
                "target_date": "2026-11-10",
                "days": "1.0",
                "reason": "私用のため",
            },
            follow_redirects=False,
        )
        self.assertEqual(r_apply.status_code, 303)

        with Session(self.engine) as session:
            req = session.exec(select(StaffPaidLeaveRequest)).one()
            self.assertEqual(req.status, "PENDING")
            self.assertEqual(req.target_date, date(2026, 11, 10))
            self.assertEqual(req.days, 1.0)
            req_id = req.id

        # 3. 園長（ADMIN）で承認実行
        self.current_user = self.admin_user
        r_approve = self.client.post(
            f"/paid-leave/requests/{req_id}/approve",
            follow_redirects=False,
        )
        self.assertEqual(r_approve.status_code, 303)

        # 4. 承認結果と残日数の減算を検証
        with Session(self.engine) as session:
            req = session.get(StaffPaidLeaveRequest, req_id)
            self.assertEqual(req.status, "APPROVED")
            self.assertIsNotNone(req.decided_at)

            leave = session.exec(select(StaffPaidLeave)).one()
            self.assertEqual(leave.used_days, 1.0)

    def test_approved_paid_leave_is_included_in_solver_unavailability(self):
        # 有給承認データが存在する場合、bridge.build_staff_member の unavailabilities に含まれるか検証
        with Session(self.engine) as session:
            # 承認済み有給申請を作成
            approved_req = StaffPaidLeaveRequest(
                staff_user_id=self.staff_user_id,
                target_date=date(2026, 11, 15),
                days=1.0,
                reason="年休",
                status="APPROVED",
            )
            session.add(approved_req)

            from models import User
            from shift_schedule.db_models import StaffContracts, StaffQualifications

            user = User(
                id=self.staff_user_id,
                email="teacher_a@example.com",
                display_name="保育士A",
                role="staff",
                is_active=True,
            )
            session.add(user)

            qual = StaffQualifications(
                staff_user_id=self.staff_user_id.hex,
                role="保育士",
                effective_from=date(2026, 4, 1),
            )
            session.add(qual)

            contract = StaffContracts(
                staff_user_id=self.staff_user_id.hex,
                employment_type="正職員",
                weekly_hours=40.0,
                daily_hours=8.0,
                effective_from=date(2026, 4, 1),
            )
            session.add(contract)
            session.commit()

            # build_staff_member & build_staff_preferences 呼び出し
            domain_staff = build_staff_member(session=session, user=user)
            self.assertIsNotNone(domain_staff)

            prefs = build_staff_preferences(session=session, user=user)
            # unavailable に 2026-11-15 の有給休が含まれていること
            unavail_days = [u.day for u in prefs.unavailable]
            self.assertIn(date(2026, 11, 15), unavail_days)
