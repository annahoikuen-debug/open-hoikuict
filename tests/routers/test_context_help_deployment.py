"""G-1 文脈ヘルプ配備拡大のテスト。

出欠一覧・請求設定・施設設定の各画面に文脈ヘルプが配備され、レンダリング時に
マーカーが出力されることを検証する。指導計画はプラン固有の依存関係を持つため、
テンプレートファイルのマーカー含有を直接アサートする。
"""
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from auth import Role, StaffUser
from models import User


class ContextHelpDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            self.admin_id = self._create_user(session, "admin", Role.ADMIN)
            self.staff_id = self._create_user(session, "staff", Role.CAN_EDIT)
            session.commit()
        self.admin_user = StaffUser(role=Role.ADMIN, name="園長", user_id=self.admin_id)
        self.staff_user = StaffUser(role=Role.CAN_EDIT, name="職員", user_id=self.staff_id)

    def tearDown(self):
        self.engine.dispose()

    def _create_user(self, session, name, role):
        user = User(email=f"{name}@example.com", display_name=name, staff_role=role)
        session.add(user)
        session.flush()
        return user.id

    def _client(self, router_module, user):
        app = FastAPI()
        app.include_router(router_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_get_current_staff_user():
            return user

        app.dependency_overrides[router_module.get_session] = override_get_session
        app.dependency_overrides[router_module.get_current_staff_user] = (
            override_get_current_staff_user
        )
        return TestClient(app)

    def _assert_help(self, router_module, path, user, marker):
        client = self._client(router_module, user)
        resp = client.get(path)
        self.assertEqual(resp.status_code, 200, f"{path} rendered:\n{resp.text[:500]}")
        self.assertIn(marker, resp.text)

    def test_attendance_list_has_context_help(self):
        import routers.attendance as attendance_router_module

        self._assert_help(
            attendance_router_module,
            "/attendance",
            self.staff_user,
            'id="help-attendance-list"',
        )

    def test_billing_settings_has_context_help(self):
        import routers.billing as billing_router_module

        self._assert_help(
            billing_router_module,
            "/billing/settings",
            self.admin_user,
            'id="help-billing-settings"',
        )

    def test_facility_settings_has_context_help(self):
        import routers.facility_settings as facility_router_module

        self._assert_help(
            facility_router_module,
            "/settings/facility",
            self.admin_user,
            'id="help-facility-settings"',
        )

    def test_settings_index_has_tour_progress_widget(self):
        import routers.settings as settings_router_module

        self._assert_help(
            settings_router_module,
            "/settings",
            self.staff_user,
            'id="tour-progress-label"',
        )
        self._assert_help(
            settings_router_module,
            "/settings",
            self.staff_user,
            'id="tour-resume-btn"',
        )

    def test_templates_contain_context_help_markers(self):
        """テンプレートファイルに文脈ヘルプのマーカーが含まれていること（全4画面）。"""
        templates = Path("templates")
        expected = {
            "attendance_list.html": 'id="help-attendance-list"',
            "billing/settings.html": 'id="help-billing-settings"',
            "plan_docs/home.html": 'id="help-plan-docs-home"',
            "facility_settings/index.html": 'id="help-facility-settings"',
        }
        for rel, marker in expected.items():
            content = (templates / rel).read_text(encoding="utf-8")
            self.assertIn(marker, content, f"{rel} に {marker} が含まれていません")


if __name__ == "__main__":
    unittest.main()
