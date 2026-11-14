"""兄弟姉妹の一括連絡 ＆ 前回入力コピー機能のテスト。"""
from __future__ import annotations

import unittest
from datetime import date
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models import (
    Child,
    ChildStatus,
    DailyContactEntry,
    Family,
    ParentAccount,
    ParentChildLink,
    AttendanceRecord,
)
from time_utils import local_today
from daily_contact_service import (
    extract_copyable_fields,
    load_latest_previous_contact,
)


def _build_engine():
    import models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


class TestDailyContactPreviousCopy(unittest.TestCase):
    def setUp(self):
        self.engine = _build_engine()
        with Session(self.engine) as session:
            self.family = Family(family_name="山田")
            session.add(self.family)
            session.flush()

            self.parent = ParentAccount(
                family_id=self.family.id,
                email="parent@example.com",
                display_name="山田保護者",
            )
            session.add(self.parent)
            session.flush()

            self.child1 = Child(
                family_id=self.family.id,
                last_name="山田",
                first_name="太郎",
                last_name_kana="ヤマダ",
                first_name_kana="タロウ",
                status=ChildStatus.enrolled,
                birth_date=date(2021, 5, 10),
                enrollment_date=date(2024, 4, 1),
            )
            self.child2 = Child(
                family_id=self.family.id,
                last_name="山田",
                first_name="花子",
                last_name_kana="ヤマダ",
                first_name_kana="ハナコ",
                status=ChildStatus.enrolled,
                birth_date=date(2023, 8, 20),
                enrollment_date=date(2024, 4, 1),
            )
            session.add_all([self.child1, self.child2])
            session.flush()

            session.add_all([
                ParentChildLink(parent_account_id=self.parent.id, child_id=self.child1.id),
                ParentChildLink(parent_account_id=self.parent.id, child_id=self.child2.id),
            ])
            session.commit()

            self.child1_id = self.child1.id
            self.child2_id = self.child2.id
            self.parent_id = self.parent.id

    def test_load_latest_previous_contact_found(self):
        with Session(self.engine) as session:
            # 2日前の連絡帳
            e1 = DailyContactEntry(
                child_id=self.child1_id,
                parent_account_id=self.parent_id,
                target_date=date(2026, 11, 8),
                temperature="36.5",
                mood="普通",
            )
            # 1日前の連絡帳（こちらが最新になるべき）
            e2 = DailyContactEntry(
                child_id=self.child1_id,
                parent_account_id=self.parent_id,
                target_date=date(2026, 11, 9),
                temperature="36.6",
                mood="良好",
                sleep_notes="ぐっすり",
                breakfast_status="完食",
                extra_data={
                    "bedtime": "21:00",
                    "wakeup_time": "06:30",
                    "breakfast_contents": "パン、牛乳、バナナ",
                    "stool_consistency": "normal",
                    "stool_count": "1",
                },
            )
            session.add_all([e1, e2])
            session.commit()

            # 2026-11-10 の時点で検索すると 2026-11-09 のレコードが返る
            prev = load_latest_previous_contact(session, child_id=self.child1_id, before_date=date(2026, 11, 10))
            self.assertIsNotNone(prev)
            self.assertEqual(prev.target_date, date(2026, 11, 9))
            self.assertEqual(prev.mood, "良好")

    def test_load_latest_previous_contact_not_found(self):
        with Session(self.engine) as session:
            prev = load_latest_previous_contact(session, child_id=self.child1_id, before_date=date(2026, 11, 10))
            self.assertIsNone(prev)

    def test_extract_copyable_fields_safety(self):
        # entry にすべての値が入っている場合
        entry = DailyContactEntry(
            child_id=self.child1_id,
            parent_account_id=self.parent_id,
            target_date=date(2026, 11, 9),
            temperature="36.6",
            mood="良好",
            sleep_notes="熟睡",
            breakfast_status="完食",
            cough="少し",
            runny_nose="なし",
            medication="朝に服用",
            condition_note="元気です",
            contact_note="本日はよろしくお願いします",
            absence_temperature="38.5",
            absence_symptoms="発熱",
            absence_diagnosis="かぜ",
            absence_note="受診します",
            extra_data={
                "bedtime": "21:15",
                "wakeup_time": "06:45",
                "breakfast_contents": "ごはん、みそ汁",
                "stool_consistency": "soft",
                "stool_count": "2",
            },
        )
        fields = extract_copyable_fields(entry)

        # コピーされるべき定常項目
        self.assertEqual(fields["bedtime"], "21:15")
        self.assertEqual(fields["wakeup_time"], "06:45")
        self.assertEqual(fields["breakfast_status"], "完食")
        self.assertEqual(fields["breakfast_contents"], "ごはん、みそ汁")
        self.assertEqual(fields["mood"], "良好")
        self.assertEqual(fields["stool_consistency"], "soft")
        self.assertEqual(fields["stool_count"], "2")
        self.assertEqual(fields["sleep_notes"], "熟睡")

        # 安全のためにコピー除外（空欄）とすべき項目
        self.assertEqual(fields["temperature"], "")
        self.assertEqual(fields["cough"], "")
        self.assertEqual(fields["runny_nose"], "")
        self.assertEqual(fields["medication"], "")
        self.assertEqual(fields["condition_note"], "")
        self.assertEqual(fields["contact_note"], "")
        self.assertEqual(fields["absence_temperature"], "")
        self.assertEqual(fields["absence_symptoms"], "")
        self.assertEqual(fields["absence_diagnosis"], "")
        self.assertEqual(fields["absence_note"], "")

    def test_contact_form_copy_previous_integration(self):
        import os
        from fastapi.testclient import TestClient
        from main import app
        from database import get_session
        from auth import MOCK_PARENT_ACCOUNT_COOKIE

        old_mock_env = os.environ.get("HOIKUICT_ENABLE_MOCK_AUTH")
        os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = "1"

        with Session(self.engine) as session:
            # 過去の連絡帳とお迎え記録を作成
            past_date = date(2026, 11, 8)
            e_past = DailyContactEntry(
                child_id=self.child1_id,
                parent_account_id=self.parent_id,
                target_date=past_date,
                temperature="36.5",
                mood="良好",
                sleep_notes="ぐっすり睡眠",
                breakfast_status="完食",
                extra_data={
                    "bedtime": "21:00",
                    "wakeup_time": "06:30",
                    "breakfast_contents": "納豆ごはん、みそ汁",
                    "stool_consistency": "normal",
                    "stool_count": "1",
                },
            )
            rec_past = AttendanceRecord(
                child_id=self.child1_id,
                attendance_date=past_date,
                planned_pickup_time="17:30",
                pickup_person="母",
                snack_required=False,
                pickup_snack_confirmed=True,
            )
            session.add_all([e_past, rec_past])
            session.commit()

        def _override_get_session():
            with Session(self.engine) as s:
                yield s

        app.dependency_overrides[get_session] = _override_get_session
        try:
            client = TestClient(app, cookies={MOCK_PARENT_ACCOUNT_COOKIE: str(self.parent_id)})

            # 1. 通常アクセス（copy_previous なし）
            res = client.get(f"/parent-portal/children/{self.child1_id}/contact?date=2026-11-10")
            self.assertEqual(res.status_code, 200)
            self.assertIn("前回の入力を反映", res.text)
            self.assertIn("11/08", res.text)

            # 2. copy_previous=1 でアクセス（自動反映）
            res_copied = client.get(f"/parent-portal/children/{self.child1_id}/contact?date=2026-11-10&copy_previous=1")
            self.assertEqual(res_copied.status_code, 200)
            self.assertIn("納豆ごはん、みそ汁", res_copied.text)
            self.assertIn("17:30", res_copied.text)
            self.assertIn("前回の入力（11/08）を反映しました", res_copied.text)
        finally:
            app.dependency_overrides.pop(get_session, None)
            if old_mock_env is None:
                os.environ.pop("HOIKUICT_ENABLE_MOCK_AUTH", None)
            else:
                os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = old_mock_env

    def test_bulk_contact_endpoints_integration(self):
        import os
        from fastapi.testclient import TestClient
        from main import app
        from database import get_session
        from auth import MOCK_PARENT_ACCOUNT_COOKIE
        from csrf import generate_csrf_token, CSRF_COOKIE_NAME

        old_mock_env = os.environ.get("HOIKUICT_ENABLE_MOCK_AUTH")
        os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = "1"

        def _override_get_session():
            with Session(self.engine) as s:
                yield s

        app.dependency_overrides[get_session] = _override_get_session
        try:
            csrf_token = generate_csrf_token()
            client = TestClient(
                app,
                cookies={
                    MOCK_PARENT_ACCOUNT_COOKIE: str(self.parent_id),
                    CSRF_COOKIE_NAME: csrf_token,
                },
            )

            # 1. ホーム画面で一括入力ボタンが表示されること
            res_home = client.get("/parent-portal/?date=2026-11-11")
            self.assertEqual(res_home.status_code, 200)
            self.assertIn("きょうだい一括入力", res_home.text)

            # 2. 一括入力画面 (GET /parent-portal/bulk-contact)
            res_bulk = client.get("/parent-portal/bulk-contact?date=2026-11-11")
            self.assertEqual(res_bulk.status_code, 200)
            self.assertIn("山田 太郎", res_bulk.text)
            self.assertIn("山田 花子", res_bulk.text)
            self.assertIn("きょうだい共通の予定・生活記録", res_bulk.text)

            # 3. 一括入力送信 (POST /parent-portal/bulk-contact) 正常系
            post_data = {
                "csrf_token": csrf_token,
                "date": "2026-11-11",
                "common_planned_pickup_time": "18:00",
                "common_pickup_person": "父",
                "common_snack_required": "1",
                "common_breakfast_contents": "ホットケーキ、牛乳",
                "common_contact_note": "本日は二人ともよろしくお願いします。",
                "child_ids": [str(self.child1_id), str(self.child2_id)],
                f"attendance_mode_{self.child1_id}": "present",
                f"temperature_{self.child1_id}": "36.4",
                f"mood_{self.child1_id}": "良好",
                f"attendance_mode_{self.child2_id}": "present",
                f"temperature_{self.child2_id}": "36.7",
                f"mood_{self.child2_id}": "ふつう",
            }
            res_post = client.post("/parent-portal/bulk-contact", data=post_data, headers={"X-CSRF-Token": csrf_token}, follow_redirects=False)
            self.assertEqual(res_post.status_code, 303)
            self.assertIn("notice=bulk_saved", res_post.headers["location"])

            # リダイレクト先（ホーム）で完了メッセージが表示されること
            res_after = client.get(res_post.headers["location"])
            self.assertEqual(res_after.status_code, 200)
            self.assertIn("きょうだい全員分の連絡を保存しました。", res_after.text)

            # 4. バリデーションエラー時 (体温が37.5℃以上)
            post_err_data = dict(post_data)
            post_err_data[f"temperature_{self.child2_id}"] = "38.2"
            res_post_err = client.post("/parent-portal/bulk-contact", data=post_err_data, headers={"X-CSRF-Token": csrf_token}, follow_redirects=False)
            self.assertEqual(res_post_err.status_code, 400)
            self.assertIn("37.5", res_post_err.text)
        finally:
            app.dependency_overrides.pop(get_session, None)
            if old_mock_env is None:
                os.environ.pop("HOIKUICT_ENABLE_MOCK_AUTH", None)
            else:
                os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = old_mock_env

    def test_save_bulk_parent_contacts_success(self):
        from daily_contact_service import save_bulk_parent_contacts

        target_date = local_today()
        common_data = {
            "planned_pickup_time": "17:15",
            "pickup_person": "母",
            "snack_required": "0",
            "breakfast_contents": "ロールパン、コーンスープ、りんご",
            "contact_note": "本日は17:15にお迎えに行きます。",
        }
        children_data = [
            {
                "child_id": self.child1_id,
                "attendance_mode": "present",
                "temperature": "36.5",
                "mood": "良好",
                "bedtime": "21:00",
                "wakeup_time": "06:30",
                "breakfast_status": "完食",
                "stool_consistency": "normal",
                "stool_count": "1",
                "sleep_notes": "ぐっすり",
            },
            {
                "child_id": self.child2_id,
                "attendance_mode": "present",
                "temperature": "36.8",
                "mood": "ふつう",
                "bedtime": "20:30",
                "wakeup_time": "06:45",
                "breakfast_status": "少なめ",
                "stool_consistency": "",
                "stool_count": "",
                "sleep_notes": "",
            },
        ]

        with Session(self.engine) as session:
            parent = session.get(ParentAccount, self.parent_id)
            saved_entries = save_bulk_parent_contacts(
                session,
                current_parent_user=parent,
                target_date=target_date,
                common_data=common_data,
                children_data=children_data,
            )
            session.commit()
            self.assertEqual(len(saved_entries), 2)

        # 保存後のレコードを検証
        with Session(self.engine) as session:
            e1 = session.exec(select(DailyContactEntry).where(
                DailyContactEntry.child_id == self.child1_id,
                DailyContactEntry.target_date == target_date,
            )).first()
            e2 = session.exec(select(DailyContactEntry).where(
                DailyContactEntry.child_id == self.child2_id,
                DailyContactEntry.target_date == target_date,
            )).first()

            self.assertIsNotNone(e1)
            self.assertIsNotNone(e2)
            self.assertEqual(e1.temperature, "36.5")
            self.assertEqual(e2.temperature, "36.8")
            self.assertEqual(e1.extra_data["breakfast_contents"], "ロールパン、コーンスープ、りんご")
            self.assertEqual(e2.extra_data["breakfast_contents"], "ロールパン、コーンスープ、りんご")
            self.assertEqual(e1.contact_note, "本日は17:15にお迎えに行きます。")
            self.assertTrue(e1.extra_data["bulk_submission"])
            self.assertEqual(e1.extra_data["bulk_with_children"], [self.child1_id, self.child2_id])

            # お迎え記録の検証
            r1 = session.exec(select(AttendanceRecord).where(
                AttendanceRecord.child_id == self.child1_id,
                AttendanceRecord.attendance_date == target_date,
            )).first()
            r2 = session.exec(select(AttendanceRecord).where(
                AttendanceRecord.child_id == self.child2_id,
                AttendanceRecord.attendance_date == target_date,
            )).first()
            self.assertIsNotNone(r1)
            self.assertIsNotNone(r2)
            self.assertEqual(r1.planned_pickup_time, "17:15")
            self.assertEqual(r2.planned_pickup_time, "17:15")
            self.assertEqual(r1.pickup_person, "母")
            self.assertEqual(r2.pickup_person, "母")

    def test_save_bulk_parent_contacts_validation_error_rolls_back(self):
        from daily_contact_service import save_bulk_parent_contacts

        target_date = local_today()
        common_data = {
            "planned_pickup_time": "17:00",
            "pickup_person": "父",
            "breakfast_contents": "ごはん",
        }
        # child1 は正常、child2 は 38.0℃で出席（バリデーションエラー）
        children_data = [
            {
                "child_id": self.child1_id,
                "attendance_mode": "present",
                "temperature": "36.5",
            },
            {
                "child_id": self.child2_id,
                "attendance_mode": "present",
                "temperature": "38.0",
            },
        ]

        with Session(self.engine) as session:
            parent = session.get(ParentAccount, self.parent_id)
            with self.assertRaises(ValueError) as ctx:
                save_bulk_parent_contacts(
                    session,
                    current_parent_user=parent,
                    target_date=target_date,
                    common_data=common_data,
                    children_data=children_data,
                )
            self.assertIn("37.5", str(ctx.exception))

            # ロールバックされているため child1 も保存されていないことを確認
            e1 = session.exec(select(DailyContactEntry).where(
                DailyContactEntry.child_id == self.child1_id,
                DailyContactEntry.target_date == target_date,
            )).first()
            self.assertIsNone(e1)


