import unittest
from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from database import get_session
import routers.nap_checks as nap_checks_module
import routers.facility_settings as facility_settings_module
from models import (
    AttendanceRecord,
    Child,
    ChildStatus,
    Classroom,
    FacilitySettings,
    NapCheckRecord,
    NapClassroomEnvironment,
)


class NapChecksTimelineTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(nap_checks_module.router)
        self.app.include_router(facility_settings_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.test_user = StaffUser(
            user_id="00000000-0000-0000-0000-000000000001",
            name="テスト保育士",
            role=Role.ADMIN,
        )

        def override_staff_user():
            return self.test_user

        self.app.dependency_overrides[get_session] = override_get_session
        self.app.dependency_overrides[nap_checks_module.get_current_staff_user] = override_staff_user
        self.app.dependency_overrides[facility_settings_module.get_current_staff_user] = override_staff_user

        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            classroom = Classroom(id=1, name="うさぎ組")
            session.add(classroom)

            child1 = Child(
                id=1,
                first_name="優衣",
                last_name="伊藤",
                first_name_kana="ゆい",
                last_name_kana="いとう",
                classroom_id=1,
                status=ChildStatus.enrolled,
                birth_date=date(2023, 4, 1),
                enrollment_date=date(2024, 4, 1),
            )
            child2 = Child(
                id=2,
                first_name="柚紀",
                last_name="鹿島",
                first_name_kana="ゆずき",
                last_name_kana="かしま",
                classroom_id=1,
                status=ChildStatus.enrolled,
                birth_date=date(2023, 5, 1),
                enrollment_date=date(2024, 4, 1),
            )
            session.add(child1)
            session.add(child2)

            today = date.today()
            # child1 は登園中（打刻済み）
            att1 = AttendanceRecord(
                child_id=1,
                attendance_date=today,
                check_in_at=datetime.now(),
            )
            # child2 は未登園・欠席（check_in_at なし）
            att2 = AttendanceRecord(
                child_id=2,
                attendance_date=today,
            )
            session.add(att1)
            session.add(att2)

            settings = FacilitySettings(
                id=1,
                nap_check_smart_enabled=True,
                nap_check_interval_minutes=5,
            )
            session.add(settings)
            session.commit()

    def tearDown(self):
        SQLModel.metadata.drop_all(self.engine)

    def test_nap_checks_list_view_and_kodmon_timeline(self):
        """コドモン互換5分刻みタイムラインが正常にレンダリングされることを検証。"""
        res = self.client.get("/nap-checks/?hour=13:00&only_present=1")
        self.assertEqual(res.status_code, 200)
        self.assertIn("健康チェック", res.text)
        self.assertIn("午睡", res.text)
        self.assertIn("スマートタイムライン", res.text)
        # child1（登園中）は表示され、child2（欠席）は登園中フィルタで除外
        self.assertIn("伊藤 優衣", res.text)
        self.assertNotIn("鹿島 柚紀", res.text)
        # 5分刻みスロットの分ヘッダーが含まれる
        self.assertIn("00", res.text)
        self.assertIn("05", res.text)
        self.assertIn("10", res.text)
        self.assertIn("55", res.text)

    def test_nap_checks_list_view_only_present_toggle(self):
        """登園中フィルタをOFFにした場合、全園児が表示されることを検証。"""
        res = self.client.get("/nap-checks/?hour=13:00&only_present=0")
        self.assertEqual(res.status_code, 200)
        self.assertIn("伊藤 優衣", res.text)
        self.assertIn("鹿島 柚紀", res.text)

    def test_nap_checks_smart_toggle_query(self):
        """?smart=0 で標準リスト表示モードに切り替えられることを検証。"""
        res = self.client.get("/nap-checks/?smart=0")
        self.assertEqual(res.status_code, 200)
        self.assertIn("標準リスト表示 [OFF]", res.text)

    def test_cycle_slot_posture(self):
        """スロットタップで体位が順次サイクル（未記録 -> back -> right -> left -> prone -> awake）することを検証。"""
        today_str = date.today().isoformat()
        # 1回目タップ: 未記録 -> back (仰向け)
        res1 = self.client.post(
            "/nap-checks/cycle-slot",
            data={
                "child_id": 1,
                "target_date": today_str,
                "time_key": "13:05",
                "current_posture": "",
            },
        )
        self.assertEqual(res1.status_code, 200)
        data1 = res1.json()
        self.assertEqual(data1["posture"], "back")
        self.assertEqual(data1["symbol"], "↑")

        # 2回目タップ: back -> right (右向き)
        res2 = self.client.post(
            "/nap-checks/cycle-slot",
            data={
                "child_id": 1,
                "target_date": today_str,
                "time_key": "13:05",
                "current_posture": "back",
            },
        )
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.json()["posture"], "right")

        # HTMX リクエストでのセル部分返却
        res_htmx = self.client.post(
            "/nap-checks/cycle-slot",
            headers={"HX-Request": "true"},
            data={
                "child_id": 1,
                "target_date": today_str,
                "time_key": "13:05",
                "current_posture": "right",
            },
        )
        self.assertEqual(res_htmx.status_code, 200)
        self.assertIn("hx-post=\"/nap-checks/cycle-slot\"", res_htmx.text)

    def test_bulk_present_slot(self):
        """現在スロットの全員「仰向け」一括確定フローを検証。"""
        today_str = date.today().isoformat()
        res = self.client.post(
            "/nap-checks/bulk-present",
            data={
                "target_date": today_str,
                "time_key": "13:10",
                "only_present": "1",
            },
            follow_redirects=True,
        )
        self.assertEqual(res.status_code, 200)

        with Session(self.engine) as session:
            rec = session.exec(
                select(NapCheckRecord).where(
                    NapCheckRecord.child_id == 1,
                    NapCheckRecord.target_date == date.today(),
                )
            ).first()
            self.assertIsNotNone(rec)
            self.assertIn("13:10", rec.slots)
            self.assertEqual(rec.slots["13:10"]["posture"], "back")

    def test_nap_memo_and_classroom_environment(self):
        """園児メモおよびクラス環境（天気・室温・湿度）の保存を検証。"""
        today_str = date.today().isoformat()
        # メモ保存
        res_memo = self.client.post(
            "/nap-checks/memo",
            data={
                "child_id": 1,
                "target_date": today_str,
                "memo": "13:15 入眠。呼吸・顔色良好。",
            },
        )
        self.assertEqual(res_memo.status_code, 200)

        # 環境記録保存
        res_env = self.client.post(
            "/nap-checks/environment",
            data={
                "classroom_id": 1,
                "target_date": today_str,
                "weather": "sunny",
                "room_temperature": "22.5",
                "humidity": "52",
                "notes": "換気良好",
            },
            follow_redirects=True,
        )
        self.assertEqual(res_env.status_code, 200)

        with Session(self.engine) as session:
            rec = session.exec(
                select(NapCheckRecord).where(NapCheckRecord.child_id == 1)
            ).first()
            self.assertEqual(rec.daily_memo, "13:15 入眠。呼吸・顔色良好。")

            env = session.exec(
                select(NapClassroomEnvironment).where(NapClassroomEnvironment.classroom_id == 1)
            ).first()
            self.assertEqual(env.weather, "sunny")
            self.assertEqual(env.room_temperature, 22.5)
            self.assertEqual(env.humidity, 52.0)

    def test_facility_settings_can_toggle_nap_check_and_interval(self):
        """施設設定画面からスマート午睡タイムラインのON/OFFおよび間隔変更を検証。"""
        with Session(self.engine) as session:
            settings = session.get(FacilitySettings, 1)
            settings.nap_check_smart_enabled = False
            settings.nap_check_interval_minutes = 10
            session.add(settings)
            session.commit()

        # 施設設定でスマートタイムラインをOFFにした場合、画面デフォルトが標準リスト表示になること
        res = self.client.get("/nap-checks/")
        self.assertEqual(res.status_code, 200)
        self.assertIn("標準リスト表示 [OFF]", res.text)

        # 10分間隔のスロットになっていること（00, 10, 20... があり、05がない）
        self.assertIn("10", res.text)
        self.assertNotIn("05", res.text)

        # 再びONに戻す
        with Session(self.engine) as session:
            settings = session.get(FacilitySettings, 1)
            settings.nap_check_smart_enabled = True
            settings.nap_check_interval_minutes = 5
            session.add(settings)
            session.commit()

        res2 = self.client.get("/nap-checks/")
        self.assertEqual(res2.status_code, 200)
        self.assertIn("スマートタイムライン [ON]", res2.text)
        self.assertIn("05", res2.text)


if __name__ == "__main__":
    unittest.main()


def test_nap_checks_invalid_input_returns_400_and_csrf_enforced():
    """不正な日付・数値入力は HTTP 400 となり、CSRF ミドルウェア適用時はトークンなし POST が 403 となること。"""
    import os
    from unittest.mock import patch
    from fastapi import Depends
    from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, generate_csrf_token, verify_csrf

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        cls = Classroom(name="ひよこ組", display_order=1)
        session.add(cls)
        session.commit()
        classroom_id = cls.id

    csrf_app = FastAPI(dependencies=[Depends(verify_csrf)])
    csrf_app.add_middleware(CsrfTokenMiddleware)
    csrf_app.include_router(nap_checks_module.router)

    def override_session():
        with Session(engine) as s:
            yield s

    csrf_app.dependency_overrides[get_session] = override_session
    csrf_app.dependency_overrides[nap_checks_module.get_current_staff_user] = lambda: StaffUser(
        role=Role.CAN_EDIT, name="保育士", can_manage_child_records=True
    )

    try:
        with patch.dict(os.environ, {"HOIKUICT_CSRF_ENFORCE": "1"}):
            c = TestClient(csrf_app)
            # CSRF なし POST は 403
            res_no_csrf = c.post(
                "/nap-checks/environment",
                data={"classroom_id": str(classroom_id), "target_date": "2026-11-25"},
            )
            assert res_no_csrf.status_code == 403

            token = generate_csrf_token()
            c.cookies.set(CSRF_COOKIE_NAME, token)

            # 不正日付は 400
            res_bad_date = c.post(
                "/nap-checks/cycle-slot",
                data={"child_id": "1", "target_date": "invalid-date", "time_key": "13:00", "current_posture": ""},
                headers={"X-CSRF-Token": token},
            )
            assert res_bad_date.status_code == 400

            res_bad_memo = c.post(
                "/nap-checks/memo",
                data={"child_id": "1", "target_date": "invalid-date", "memo": "test"},
                headers={"X-CSRF-Token": token},
            )
            assert res_bad_memo.status_code == 400

            # 不正室温は 400
            res_bad_temp = c.post(
                "/nap-checks/environment",
                data={
                    "classroom_id": str(classroom_id),
                    "target_date": "2026-11-25",
                    "room_temperature": "not-a-float",
                },
                headers={"X-CSRF-Token": token},
            )
            assert res_bad_temp.status_code == 400

            # 正常リクエスト + CSRF 通過 -> 303
            res_ok = c.post(
                "/nap-checks/environment",
                data={
                    "classroom_id": str(classroom_id),
                    "target_date": "2026-11-25",
                    "room_temperature": "22.5",
                    "csrf_token": token,
                },
                follow_redirects=False,
            )
            assert res_ok.status_code == 303
    finally:
        engine.dispose()
