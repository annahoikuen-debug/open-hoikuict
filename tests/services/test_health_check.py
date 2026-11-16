"""設定ヘルスチェックサービス (P1-1) のテスト。"""
import unittest
from datetime import date

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import child_records.models  # noqa: F401
from health_check_service import run_facility_health_check
from models import (
    BillingSetting,
    Child,
    ChildStatus,
    Classroom,
    FacilitySettings,
    FeeItem,
)


class HealthCheckServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_health_check_detects_default_and_unassigned_issues(self):
        """初期値や未割当がある場合に正しく重大・警告を検出すること。"""
        with Session(self.engine) as session:
            # 1. ダミーコードの全銀設定
            zengin = BillingSetting(
                facility_name="テスト園",
                collector_code="1234567890",  # ダミー
                collector_name_kana="ﾃｽﾄ",
                withdrawal_bank_code="0001",
                withdrawal_branch_code="001",
                collector_account_type="1",
                collector_account_number="1234567",
            )
            session.add(zengin)

            # 2. クラス未割当の在園児
            child = Child(
                first_name="葵",
                last_name="小林",
                first_name_kana="アオイ",
                last_name_kana="コバヤシ",
                birth_date=date(2023, 4, 1),
                enrollment_date=date(2025, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=None,  # 未割当
            )
            session.add(child)
            session.commit()

            result = run_facility_health_check(session)

        self.assertLess(result["score"], 100)
        self.assertIn(result["rating"], ["要対応", "注意", "概ね良好"])
        self.assertGreaterEqual(result["counts"]["critical"], 1)
        self.assertGreaterEqual(result["counts"]["warning"], 1)

        critical_ids = [d["id"] for d in result["diagnostics"] if d["level"] == "critical"]
        self.assertIn("zengin_collector_code", critical_ids)

        warning_ids = [d["id"] for d in result["diagnostics"] if d["level"] == "warning"]
        self.assertIn("unassigned_children", warning_ids)
        self.assertIn("fee_items_defined", warning_ids)

    def test_health_check_passes_when_all_configured(self):
        """適切に設定された環境で高スコア（良好）となること。"""
        with Session(self.engine) as session:
            # 正規全銀設定
            zengin = BillingSetting(
                facility_name="ひまわり保育園",
                collector_code="9876543210",  # 正規コード
                collector_name_kana="ﾋﾏﾜﾘ",
                withdrawal_bank_code="0005",
                withdrawal_branch_code="123",
                collector_account_type="1",
                collector_account_number="7654321",
            )
            session.add(zengin)

            # クラスと所属園児
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(classroom)
            session.flush()

            child = Child(
                first_name="太郎",
                last_name="山田",
                first_name_kana="タロウ",
                last_name_kana="ヤマダ",
                birth_date=date(2023, 4, 1),
                enrollment_date=date(2025, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
            )
            session.add(child)

            # 料金項目
            fee = FeeItem(code="meal_monthly", name="月極給食費", category="meal", charge_unit="monthly", is_active=True)
            session.add(fee)

            # 施設設定
            fac = FacilitySettings(
                closing_time="18:00",
                snack_cutoff_time="16:00",
                fever_caution_c="37.5",
            )
            session.add(fac)
            session.commit()

            result = run_facility_health_check(session)

        # 0 critical, 0 or 1 warning -> score >= 90
        self.assertEqual(result["counts"]["critical"], 0)
        self.assertGreaterEqual(result["score"], 80)
        ok_ids = [d["id"] for d in result["diagnostics"] if d["level"] == "ok"]
        self.assertIn("zengin_collector_code", ok_ids)
        self.assertIn("unassigned_children", ok_ids)
        self.assertIn("fee_items_defined", ok_ids)
        self.assertIn("facility_settings", ok_ids)

    def test_health_check_http_endpoints(self):
        """HTTP GET /settings/health-check および /settings/health-check/api の検証。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from auth import Role, StaffUser
        import routers.settings as settings_router_module

        app = FastAPI()
        app.include_router(settings_router_module.router)

        admin_user = StaffUser(role=Role.ADMIN, name="園長", user_id="admin-01")

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_get_current_staff_user():
            return admin_user

        app.dependency_overrides[settings_router_module.get_session] = override_get_session
        app.dependency_overrides[settings_router_module.get_current_staff_user] = override_get_current_staff_user

        client = TestClient(app)

        # 1. HTML画面
        resp_html = client.get("/settings/health-check")
        self.assertEqual(resp_html.status_code, 200)
        self.assertIn("施設・園の設定ヘルスチェック診断", resp_html.text)

        # 2. JSON API
        resp_api = client.get("/settings/health-check/api")
        self.assertEqual(resp_api.status_code, 200)
        data = resp_api.json()
        self.assertIn("score", data)
        self.assertIn("rating", data)
        self.assertIn("counts", data)
        self.assertIn("diagnostics", data)


if __name__ == "__main__":
    unittest.main()
