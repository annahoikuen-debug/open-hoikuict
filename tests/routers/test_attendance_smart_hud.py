import unittest
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from database import get_session
import routers.attendance_checks as attendance_checks_module
import routers.facility_settings as facility_settings_module
from models import (
    AttendanceRecord,
    AttendanceVerification,
    AttendanceVerificationHistory,
    AttendanceVerificationStatus,
    Child,
    ChildStatus,
    Classroom,
    DailyContactEntry,
    FacilitySettings,
    ParentAccount,
    ParentContactType,
)


class AttendanceSmartHudTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(attendance_checks_module.router)
        self.app.include_router(facility_settings_module.router)

        def get_test_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[get_session] = get_test_session

        self.current_user = StaffUser(
            role=Role.ADMIN,
            name="テスト園長",
        )

        def get_test_user():
            return self.current_user

        self.app.dependency_overrides[attendance_checks_module.get_current_staff_user] = get_test_user
        self.app.dependency_overrides[facility_settings_module.get_current_staff_user] = get_test_user
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            classroom = Classroom(id=1, name="ぱんだ組", display_order=1)
            session.add(classroom)

            parent = ParentAccount(
                id=1,
                email="parent@example.com",
                display_name="保護者",
            )
            session.add(parent)

            # 園児1: 登園打刻あり（出席候補）
            child1 = Child(
                id=1,
                first_name="太郎",
                last_name="佐藤",
                first_name_kana="タロウ",
                last_name_kana="サトウ",
                birth_date=date(2023, 4, 1),
                enrollment_date=date(2024, 4, 1),
                classroom_id=1,
                status=ChildStatus.enrolled,
            )
            # 園児2: 発熱欠席連絡あり（要対応・赤）
            child2 = Child(
                id=2,
                first_name="花子",
                last_name="田中",
                first_name_kana="ハナコ",
                last_name_kana="タナカ",
                birth_date=date(2023, 5, 1),
                enrollment_date=date(2024, 4, 1),
                classroom_id=1,
                status=ChildStatus.enrolled,
            )
            # 園児3: 私用欠席連絡あり（連絡済・黄）
            child3 = Child(
                id=3,
                first_name="次郎",
                last_name="鈴木",
                first_name_kana="ジロウ",
                last_name_kana="スズキ",
                birth_date=date(2023, 6, 1),
                enrollment_date=date(2024, 4, 1),
                classroom_id=1,
                status=ChildStatus.enrolled,
            )
            session.add_all([child1, child2, child3])

            # 園児1の登園打刻
            record1 = AttendanceRecord(
                child_id=1,
                attendance_date=date(2027, 2, 10),
                check_in_at=datetime(2027, 2, 10, 8, 30, tzinfo=timezone.utc),
            )
            session.add(record1)

            # 園児2の発熱連絡（38.2℃）
            entry2 = DailyContactEntry(
                child_id=2,
                parent_account_id=1,
                target_date=date(2027, 2, 10),
                contact_type=ParentContactType.absent_sick,
                absence_reason="発熱",
                absence_temperature="38.2",
            )
            session.add(entry2)

            # 園児3の私用休み連絡
            entry3 = DailyContactEntry(
                child_id=3,
                parent_account_id=1,
                target_date=date(2027, 2, 10),
                contact_type=ParentContactType.absent_private,
                absence_reason="私用のため",
            )
            session.add(entry3)

            # 初期設定（HUD有効）
            settings = FacilitySettings(
                id=1,
                attendance_smart_hud_enabled=True,
            )
            session.add(settings)
            session.commit()

    def tearDown(self):
        SQLModel.metadata.drop_all(self.engine)

    def test_smart_hud_display_and_metrics(self):
        """スマートHUDが有効な場合、HUDコンポーネントが表示され3色シグナルが集計されること"""
        response = self.client.get("/attendance-checks/?date=2027-02-10")
        self.assertEqual(response.status_code, 200)
        content = response.text

        # HUDバナー・コンポーネントの表示確認
        self.assertIn("スマート・モーニング点呼 HUD", content)
        self.assertIn("登園済・出席", content)
        self.assertIn("連絡済（欠席/遅刻）", content)
        self.assertIn("要対応・未打刻", content)

        # 一括出席確定ボタン（園児1が未確認かつ打刻済なので表示される）
        self.assertIn("一括出席確定する", content)

    def test_smart_hud_toggle_via_query_param(self):
        """クエリパラメータ ?hud=0 で通常表示、?hud=1 でHUD表示に切り替えられること"""
        # ?hud=0 で通常表示
        res_off = self.client.get("/attendance-checks/?date=2027-02-10&hud=0")
        self.assertEqual(res_off.status_code, 200)
        self.assertNotIn("スマート・モーニング点呼 HUD", res_off.text)
        self.assertIn("スマートHUDへ", res_off.text)

        # ?hud=1 でHUD表示
        res_on = self.client.get("/attendance-checks/?date=2027-02-10&hud=1")
        self.assertEqual(res_on.status_code, 200)
        self.assertIn("スマート・モーニング点呼 HUD", res_on.text)
        self.assertIn("通常表示へ", res_on.text)

    def test_quick_bulk_present_flow(self):
        """登園打刻のある未確認園児が一括で出席確定され、履歴が残ること"""
        # 実行前の確認
        with Session(self.engine) as session:
            v_before = session.exec(
                select(AttendanceVerification).where(
                    AttendanceVerification.child_id == 1,
                    AttendanceVerification.target_date == date(2027, 2, 10),
                )
            ).first()
            self.assertIsNone(v_before)

        # 一括出席確定を実行
        post_res = self.client.post(
            "/attendance-checks/quick-bulk-present",
            data={
                "date": "2027-02-10",
                "classroom_id": "1",
                "hud": "1",
            },
            follow_redirects=True,
        )
        self.assertEqual(post_res.status_code, 200)

        # 実行後のDB確認
        with Session(self.engine) as session:
            v_after = session.exec(
                select(AttendanceVerification).where(
                    AttendanceVerification.child_id == 1,
                    AttendanceVerification.target_date == date(2027, 2, 10),
                )
            ).first()
            self.assertIsNotNone(v_after)
            self.assertEqual(v_after.status, AttendanceVerificationStatus.present)
            self.assertEqual(v_after.updated_by_name, "テスト園長")

            # 履歴の確認
            hist = session.exec(
                select(AttendanceVerificationHistory).where(
                    AttendanceVerificationHistory.child_id == 1,
                    AttendanceVerificationHistory.target_date == date(2027, 2, 10),
                )
            ).first()
            self.assertIsNotNone(hist)
            self.assertEqual(hist.reason, "スマートHUD一括出席確認")

    def test_facility_settings_can_toggle_hud_default(self):
        """施設設定でスマートHUDをOFFにすると既定が通常表示になること"""
        with Session(self.engine) as session:
            settings = session.get(FacilitySettings, 1)
            settings.attendance_smart_hud_enabled = False
            session.add(settings)
            session.commit()

        # デフォルトでアクセスするとHUDは非表示
        res = self.client.get("/attendance-checks/?date=2027-02-10")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("スマート・モーニング点呼 HUD", res.text)
        self.assertIn("スマートHUDへ", res.text)

        # 明示的に ?hud=1 をつければ表示可能
        res_hud = self.client.get("/attendance-checks/?date=2027-02-10&hud=1")
        self.assertEqual(res_hud.status_code, 200)
        self.assertIn("スマート・モーニング点呼 HUD", res_hud.text)


if __name__ == "__main__":
    unittest.main()
