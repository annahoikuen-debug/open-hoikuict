import json
import unittest
from datetime import datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from auth import Role, StaffUser
from database import get_session
import routers.facility_settings as facility_settings_module
import routers.staff_portal as staff_portal_module
from facility_settings_service import get_simple_mode_tiles
from models import FacilitySettings, User


class StaffSimpleModeTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(staff_portal_module.router)
        self.app.include_router(facility_settings_module.router)

        def get_test_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[get_session] = get_test_session

        self.staff_id = uuid4()
        self.current_user = StaffUser(
            role=Role.ADMIN,
            name="テスト園長",
            user_id=self.staff_id,
        )

        def get_test_user():
            return self.current_user

        self.app.dependency_overrides[staff_portal_module.get_optional_current_staff_user] = get_test_user
        self.app.dependency_overrides[facility_settings_module.get_current_staff_user] = get_test_user
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            user = User(
                id=self.staff_id,
                email="admin@example.com",
                display_name="テスト園長",
                staff_role="admin",
                is_active=True,
            )
            session.add(user)

            settings = FacilitySettings(
                id=1,
                staff_simple_mode_enabled=True,
                simple_mode_custom_tiles=json.dumps(["attendance_checks", "health"]),
            )
            session.add(settings)
            session.commit()

    def tearDown(self):
        SQLModel.metadata.drop_all(self.engine)

    def test_next_action_recommendation_time_phases(self):
        """時間帯ごとに適切なネクストアクションが生成されること"""
        # 朝 08:30
        morning_dt = datetime(2027, 2, 10, 8, 30)
        morning_res = staff_portal_module.build_next_action_recommendation(morning_dt)
        self.assertEqual(morning_res["phase"], "morning")
        self.assertIn("出欠確認", morning_res["primary_action"]["title"])

        # 午前 11:30
        day_dt = datetime(2027, 2, 10, 11, 30)
        day_res = staff_portal_module.build_next_action_recommendation(day_dt)
        self.assertEqual(day_res["phase"], "daytime")
        self.assertIn("日次連絡", day_res["primary_action"]["title"])

        # 午睡 13:30
        nap_dt = datetime(2027, 2, 10, 13, 30)
        nap_res = staff_portal_module.build_next_action_recommendation(nap_dt)
        self.assertEqual(nap_res["phase"], "nap")
        self.assertIn("健康・午睡", nap_res["primary_action"]["title"])

        # 夕方 17:30
        evening_dt = datetime(2027, 2, 10, 17, 30)
        evening_res = staff_portal_module.build_next_action_recommendation(evening_dt)
        self.assertEqual(evening_res["phase"], "evening")
        self.assertIn("登降園管理", evening_res["primary_action"]["title"])

    def test_staff_home_displays_command_bar_and_custom_tiles(self):
        """職員ホームにかんたんメニューとカスタマイズされたタイル（出欠、健康）が表示されること"""
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        content = response.text

        # コマンドバーと推奨ルーチン
        self.assertIn("推奨ルーチン", content)

        # かんたん業務メニュー
        self.assertIn("かんたん業務メニュー", content)
        self.assertIn("出欠確認", content)
        self.assertIn("健康・午睡", content)

        # カスタマイズで除外された「カレンダー」タイルはかんたんメニュー一覧にないこと
        # （ヘッダーなどのナビゲーションリンク以外でタイルのdescが含まれないことを検証）
        self.assertIn("検温・SIDS午睡チェック", content)
        self.assertNotIn("行事予定・シフト確認", content)

    def test_staff_home_simple_mode_query_toggle(self):
        """クエリパラメータ ?simple=0 で通常表示、?simple=1 でかんたんモードに切り替えられること"""
        # ?simple=0 で通常モード（かんたん業務メニューは非表示）
        res_normal = self.client.get("/?simple=0")
        self.assertEqual(res_normal.status_code, 200)
        self.assertNotIn("かんたん業務メニュー", res_normal.text)
        self.assertIn("かんたんモードへ", res_normal.text)

        # ?simple=1 でかんたんモード
        res_simple = self.client.get("/?simple=1")
        self.assertEqual(res_simple.status_code, 200)
        self.assertIn("かんたん業務メニュー", res_simple.text)
        self.assertIn("通常ホームへ", res_simple.text)

    def test_facility_settings_can_customize_tiles_and_toggle(self):
        """施設設定でタイルをカスタマイズ選択し、かんたんモードをOFFにできること"""
        with Session(self.engine) as session:
            settings = session.get(FacilitySettings, 1)
            # 3つのタイルを選択
            settings.simple_mode_custom_tiles = json.dumps(["notices", "plans", "calendar"])
            session.add(settings)
            session.commit()

            tiles = get_simple_mode_tiles(session)
            tile_keys = [t["key"] for t in tiles]
            self.assertEqual(tile_keys, ["notices", "plans", "calendar"])

            # 機能をOFFにする
            settings.staff_simple_mode_enabled = False
            session.add(settings)
            session.commit()

        # 施設設定OFFのとき、ホームにコマンドバーやかんたんメニューは表示されない
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertNotIn("かんたん業務メニュー", res.text)
        self.assertNotIn("推奨ルーチン", res.text)


if __name__ == "__main__":
    unittest.main()
