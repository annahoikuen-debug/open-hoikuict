"""Boundary and segregation-of-duties tests for FacilitySettings vs ShiftFacilitySettings (Step 18)."""

import unittest
from datetime import datetime

from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.pool import StaticPool

from models import FacilitySettings
from shift_schedule.db_models import ShiftFacilitySettings


class FacilitySettingsBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def test_settings_tables_segregation_and_defaults(self):
        with Session(self.engine) as session:
            # 1. 本体 FacilitySettings (Phase 3.2: 延長保育・補食・キオスク運用)
            fac = FacilitySettings(
                id=1,
                final_pickup_time="19:00",
                supplementary_meal_time="18:00",
                supplementary_meal_fee=100,
            )
            session.add(fac)

            # 2. シフト用 ShiftFacilitySettings (Phase 3.1: 開園・閉園・定員・配置基準)
            shift_fac = ShiftFacilitySettings(
                id=1,
                day_open="07:30",
                day_close="19:30",
                capacity=60,
                staffing_standard_key="fukuoka_city",
            )
            session.add(shift_fac)
            session.commit()

            loaded_fac = session.exec(select(FacilitySettings).where(FacilitySettings.id == 1)).one()
            loaded_shift = session.exec(select(ShiftFacilitySettings).where(ShiftFacilitySettings.id == 1)).one()

            # 責務分離の検証:
            # 開園・閉園の正本は ShiftFacilitySettings
            self.assertEqual(loaded_shift.day_open, "07:30")
            self.assertEqual(loaded_shift.day_close, "19:30")

            # 補食・最終ピックアップ時刻の正本は FacilitySettings
            self.assertEqual(loaded_fac.final_pickup_time, "19:00")
            self.assertEqual(loaded_fac.supplementary_meal_time, "18:00")
            self.assertEqual(loaded_fac.supplementary_meal_fee, 100)

            # テーブル名と責務が完全に独立していること
            self.assertNotEqual(FacilitySettings.__tablename__, ShiftFacilitySettings.__tablename__)

    def test_non_admin_cannot_update_facility_settings(self):
        from uuid import uuid4
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from auth import Role, StaffUser
        from database import get_session
        from auth import get_current_staff_user
        from routers.facility_settings import router

        app = FastAPI()
        app.include_router(router)

        staff_user = StaffUser(role=Role.CAN_EDIT, name="一般職員", user_id=uuid4())

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_current_user():
            return staff_user

        app.dependency_overrides[get_session] = override_get_session
        app.dependency_overrides[get_current_staff_user] = override_current_user

        client = TestClient(app)
        # GET should be 403
        r_get = client.get("/settings/facility")
        self.assertEqual(r_get.status_code, 403)

        # POST should be 403
        r_post = client.post(
            "/settings/facility",
            data={
                "final_pickup_time": "19:00",
                "supplementary_meal_time": "18:00",
                "supplementary_meal_fee": 100,
            },
        )
        self.assertEqual(r_post.status_code, 403)

    def test_admin_updates_facility_settings_with_csrf(self):
        from uuid import uuid4
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from auth import Role, StaffUser
        from database import get_session
        from auth import get_current_staff_user
        from csrf import CsrfTokenMiddleware, generate_csrf_token, CSRF_COOKIE_NAME
        from routers.facility_settings import router

        app = FastAPI()
        app.add_middleware(CsrfTokenMiddleware)
        app.include_router(router)

        admin_user = StaffUser(role=Role.ADMIN, name="園長", user_id=uuid4())

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_current_user():
            return admin_user

        app.dependency_overrides[get_session] = override_get_session
        app.dependency_overrides[get_current_staff_user] = override_current_user

        client = TestClient(app)

        # 1. GET page
        r_get = client.get("/settings/facility")
        self.assertEqual(r_get.status_code, 200)
        self.assertIn("施設基本設定", r_get.text)

        # 2. POST without CSRF should fail if enforced or verified
        token = generate_csrf_token()
        client.cookies.set(CSRF_COOKIE_NAME, token)

        r_post = client.post(
            "/settings/facility",
            data={
                "csrf_token": token,
                "final_pickup_time": "19:30",
                "supplementary_meal_time": "18:15",
                "supplementary_meal_fee": 150,
            },
            follow_redirects=False,
        )
        self.assertEqual(r_post.status_code, 303)
        self.assertIn("/settings/facility?saved=1", r_post.headers["location"])

        # Check DB updated
        with Session(self.engine) as session:
            updated = session.exec(select(FacilitySettings).where(FacilitySettings.id == 1)).one()
            self.assertEqual(updated.final_pickup_time, "19:30")
            self.assertEqual(updated.supplementary_meal_time, "18:15")
            self.assertEqual(updated.supplementary_meal_fee, 150)
