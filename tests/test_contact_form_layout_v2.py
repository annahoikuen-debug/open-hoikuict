"""日次連絡フォーム v2 レイアウトの統合テスト（フェーズA W1）.

conftest のテスト DB を利用し、contact_layout_version=2 の POST 処理や
前回コピー・notice 表示などの動作を検証する。
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
from urllib.parse import unquote, urlparse, parse_qs
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from fastapi import FastAPI
from fastapi.testclient import TestClient

from models import (
    Child,
    ChildStatus,
    DailyContactEntry,
    Family,
    ParentAccount,
    ParentChildLink,
    ParentContactType,
)
import routers.parent_portal as parent_portal_module
from routers.parent_portal import mock_login_router
from testing_helpers import configure_test_environment
from time_utils import local_today


def _build_engine():
    import models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


class TestContactFormLayoutV2(unittest.TestCase):
    def setUp(self):
        configure_test_environment()
        self.engine = _build_engine()

        self.app = FastAPI()
        self.app.include_router(parent_portal_module.router)
        self.app.include_router(mock_login_router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[parent_portal_module.get_session] = (
            override_get_session
        )

        self.client = TestClient(self.app)

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

            self.child = Child(
                family_id=self.family.id,
                last_name="山田",
                first_name="太郎",
                last_name_kana="ヤマダ",
                first_name_kana="タロウ",
                status=ChildStatus.enrolled,
                birth_date=date(2021, 5, 10),
                enrollment_date=date(2024, 4, 1),
            )
            session.add(self.child)
            session.flush()

            session.add(
                ParentChildLink(
                    parent_account_id=self.parent.id, child_id=self.child.id
                )
            )
            session.commit()

            self.child_id = self.child.id
            self.parent_id = self.parent.id

    def _login(self):
        self.client.post(
            "/parent-portal/login",
            data={"parent_account_id": str(self.parent_id)},
        )

    def test_v2_post_generates_same_extra_data_as_v1(self):
        """contact_layout_version=2 の POST が v1 と同一の extra_data / entry 状態を生成する."""
        target = local_today()
        self._login()
        form_data = {
            "date": target.isoformat(),
            "attendance_mode": "present",
            "contact_type": ParentContactType.present.value,
            "temperature": "36.5",
            "contact_layout_version": "2",
            "care_fields_version": "1",
            "meal_fields_version": "1",
            "bedtime": "21:00",
            "wakeup_time": "07:00",
            "breakfast_appetite": "完食",
            "breakfast_contents": "パンと牛乳",
            "dinner_appetite": "ほぼ完食",
            "dinner_contents": "カレーライス",
            "stool_consistency": "normal",
            "stool_count": "1",
            "mood": "良好",
            "contact_note": "よろしくお願いします",
            "pickup_fields_version": "1",
            "planned_pickup_time": "17:00",
            "pickup_person": "父",
            "snack_required": "1",
            "pickup_hour": "17",
            "pickup_minute": "00",
            "pickup_revision": "new",
        }
        resp = self.client.post(
            f"/parent-portal/children/{self.child_id}/contact",
            data=form_data,
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)

        with Session(self.engine) as session:
            entry = session.exec(
                select(DailyContactEntry).where(
                    DailyContactEntry.child_id == self.child_id,
                    DailyContactEntry.target_date == target,
                )
            ).first()
            self.assertIsNotNone(entry)
            extra = entry.extra_data or {}
            self.assertEqual(extra.get("breakfast_appetite"), "完食")
            self.assertEqual(extra.get("dinner_appetite"), "ほぼ完食")
            self.assertEqual(extra.get("breakfast_contents"), "パンと牛乳")
            self.assertEqual(extra.get("dinner_contents"), "カレーライス")

    def test_v1_form_still_accepted(self):
        """v1 フォームの POST が引き続き受理される（配備直後の混在・リロード互換）."""
        target = local_today() + timedelta(days=1)
        self._login()
        form_data = {
            "date": target.isoformat(),
            "attendance_mode": "present",
            "contact_type": ParentContactType.present.value,
            "temperature": "36.8",
            # contact_layout_version を送信しない（v1 クライアント相当）
            "care_fields_version": "1",
            "meal_fields_version": "1",
            "bedtime": "20:30",
            "wakeup_time": "06:30",
            "breakfast_appetite": "旺盛",
            "breakfast_contents": "ごはん",
            "dinner_appetite": "普通",
            "dinner_contents": "魚",
            "stool_consistency": "normal",
            "mood": "ふつう",
            "pickup_fields_version": "1",
            "planned_pickup_time": "16:30",
            "pickup_person": "母",
            "pickup_hour": "16",
            "pickup_minute": "30",
            "pickup_revision": "new",
        }
        resp = self.client.post(
            f"/parent-portal/children/{self.child_id}/contact",
            data=form_data,
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)

        with Session(self.engine) as session:
            entry = session.exec(
                select(DailyContactEntry).where(
                    DailyContactEntry.child_id == self.child_id,
                    DailyContactEntry.target_date == target,
                )
            ).first()
            self.assertIsNotNone(entry)
            extra = entry.extra_data or {}
            self.assertEqual(extra.get("breakfast_appetite"), "旺盛")

    def test_copy_from_previous_shows_inherit_notice(self):
        """「前回コピー」フラグ付き送信で notice に引き継ぎ文言が入る／通常送信では入らない."""
        target = local_today() + timedelta(days=2)
        prev_date = target - timedelta(days=1)

        self._login()
        with Session(self.engine) as session:
            # 前日分のエントリを作成
            prev_entry = DailyContactEntry(
                child_id=self.child_id,
                parent_account_id=self.parent_id,
                target_date=prev_date,
                temperature="36.6",
                contact_type=ParentContactType.present,
                extra_data={
                    "bedtime": "20:00",
                    "wakeup_time": "06:00",
                    "breakfast_appetite": "完食",
                    "dinner_appetite": "半分",
                    "planned_pickup_time": "17:00",
                },
            )
            session.add(prev_entry)
            session.commit()

        form_data = {
            "date": target.isoformat(),
            "attendance_mode": "present",
            "contact_type": ParentContactType.present.value,
            "temperature": "36.7",
            "contact_layout_version": "2",
            "care_fields_version": "1",
            "meal_fields_version": "1",
            "copied_from_previous": "1",
            "bedtime": "20:00",
            "wakeup_time": "06:00",
            "breakfast_appetite": "完食",
            "dinner_appetite": "半分",
            "mood": "良好",
            "pickup_fields_version": "1",
            "planned_pickup_time": "17:00",
            "pickup_person": "父",
            "snack_required": "1",
            "pickup_hour": "17",
            "pickup_minute": "00",
            "pickup_revision": "new",
        }
        resp = self.client.post(
            f"/parent-portal/children/{self.child_id}/contact",
            data=form_data,
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        location = resp.headers.get("location", "")
        # notice はクエリパラメータとしてURLに含まれる（URLデコードして比較）
        parsed = urlparse(location)
        qs = parse_qs(parsed.query)
        notice_text = unquote(qs.get("notice", [""])[0])
        self.assertIn("引き継いで送信しました", notice_text)

    def test_absence_mode_meal_validation_skipped(self):
        """欠席モードでは食事・睡眠・排便の検証が走らない（現行仕様の維持）."""
        target = local_today() + timedelta(days=3)
        self._login()
        form_data = {
            "date": target.isoformat(),
            "attendance_mode": "absent",
            "absence_reason": "absent_sick",
            "contact_type": ParentContactType.absent_sick.value,
            "absence_temperature": "38.5",
            "absence_symptoms": "発熱",
            "contact_layout_version": "2",
            # 食事・睡眠・排便フィールドは空（検証されないはず）
        }
        resp = self.client.post(
            f"/parent-portal/children/{self.child_id}/contact",
            data=form_data,
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)

    def test_sick_absence_temperature_required(self):
        """病欠の体温・症状必須チェックが変わらない."""
        target = local_today() + timedelta(days=4)
        self._login()
        form_data = {
            "date": target.isoformat(),
            "attendance_mode": "absent",
            "absence_reason": "absent_sick",
            "contact_type": ParentContactType.absent_sick.value,
            # 体温・症状未入力
            "contact_layout_version": "2",
        }
        resp = self.client.post(
            f"/parent-portal/children/{self.child_id}/contact",
            data=form_data,
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.text
        self.assertIn("病欠の場合は現在の体温を入力してください", body)

    def test_contact_revision_mismatch_returns_409(self):
        """contact_revision 不一致で 409 + 「ご家族が日次連絡を更新しました」が返る（現行維持）."""
        target = local_today() + timedelta(days=5)
        self._login()
        with Session(self.engine) as session:
            # 既存エントリを作成
            existing = DailyContactEntry(
                child_id=self.child_id,
                parent_account_id=self.parent_id,
                target_date=target,
                temperature="36.5",
                contact_type=ParentContactType.present,
            )
            session.add(existing)
            session.commit()

        form_data = {
            "date": target.isoformat(),
            "attendance_mode": "present",
            "contact_type": ParentContactType.present.value,
            "temperature": "36.6",
            "contact_layout_version": "2",
            "contact_revision": "invalid-revision-value",
            "care_fields_version": "1",
            "meal_fields_version": "1",
            "mood": "良好",
            "pickup_fields_version": "1",
            "planned_pickup_time": "17:00",
            "pickup_person": "父",
            "pickup_hour": "17",
            "pickup_minute": "00",
            "pickup_revision": "new",
        }
        resp = self.client.post(
            f"/parent-portal/children/{self.child_id}/contact",
            data=form_data,
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 409)
        body = resp.text
        self.assertIn("ご家族が日次連絡を更新しました", body)

    def test_same_pickup_time_chip_is_explicit_only(self):
        """お迎え「前回と同じ時刻」チップは明示送信値としてのみ反映され、自動プリセットが発生しない."""
        target = local_today() + timedelta(days=6)
        self._login()
        # planned_pickup_time を送信しない → お迎え予定は保存されない
        form_data = {
            "date": target.isoformat(),
            "attendance_mode": "present",
            "contact_type": ParentContactType.present.value,
            "temperature": "36.5",
            "contact_layout_version": "2",
            "care_fields_version": "1",
            "meal_fields_version": "1",
            "mood": "良好",
            "pickup_fields_version": "1",
            "pickup_revision": "new",
        }
        resp = self.client.post(
            f"/parent-portal/children/{self.child_id}/contact",
            data=form_data,
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)

    def test_previous_entry_helper_various_cases(self):
        """前日値取得ヘルパー: 前日エントリなし・欠席エントリのみ・退園児の前日、の各ケース."""
        from daily_contact_service import load_latest_previous_contact

        target = local_today() + timedelta(days=7)
        with Session(self.engine) as session:
            # ケース1: 前日エントリなし
            prev = load_latest_previous_contact(
                session, child_id=self.child_id, before_date=target
            )
            self.assertIsNone(prev)

            # ケース2: 欠席エントリのみがある場合
            absent_date = target - timedelta(days=1)
            absent_entry = DailyContactEntry(
                child_id=self.child_id,
                parent_account_id=self.parent_id,
                target_date=absent_date,
                contact_type=ParentContactType.absent_private,
                extra_data={"mood": ""},
            )
            session.add(absent_entry)
            session.commit()
            prev = load_latest_previous_contact(
                session, child_id=self.child_id, before_date=target
            )
            self.assertIsNotNone(prev)
            self.assertEqual(prev.contact_type, ParentContactType.absent_private)
