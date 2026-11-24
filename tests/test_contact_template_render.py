"""日次連絡フォームテンプレートのレンダリングスモークテスト（フェーズA W1）.

contact_form.html の W1 関連要素（コピーボタン、同じ時刻チップ、
hidden フィールドなど）が正しくレンダリングされることを検証する。
"""

from __future__ import annotations

import unittest
from datetime import date, timedelta
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
from routers.parent_portal import mock_login_router
import routers.parent_portal as parent_portal_module
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


class TestContactTemplateRender(unittest.TestCase):
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

    def test_contact_form_renders_with_previous_entry(self):
        """前回エントリあり：コピーボタン・同じ時刻チップが表示される."""
        target = local_today() + timedelta(days=1)
        prev_date = target - timedelta(days=1)

        self._login()
        with Session(self.engine) as session:
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

        resp = self.client.get(
            f"/parent-portal/children/{self.child_id}/contact?date={target.isoformat()}",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.text

        # 前回コピーボタンが表示される
        self.assertIn("前回の入力を反映", body)
        self.assertIn(prev_date.strftime("%m/%d"), body)

        # 同じ時刻チップが表示される
        self.assertIn("前回と同じ時刻", body)
        self.assertIn("17:00", body)

    def test_contact_form_renders_without_previous_entry(self):
        """前回エントリなし：コピーボタン・同じ時刻チップは表示されない."""
        target = local_today() + timedelta(days=1)

        self._login()
        resp = self.client.get(
            f"/parent-portal/children/{self.child_id}/contact?date={target.isoformat()}",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.text

        # コピーボタンは表示されない（ボタン要素自体がレンダリングされない）
        self.assertNotIn('id="btn-copy-previous"', body)
        # 同じ時刻チップは表示されない
        self.assertNotIn('id="btn-same-pickup-time"', body)

    def test_contact_form_includes_hidden_layout_fields(self):
        """contact_layout_version と copied_from_previous の hidden フィールドが含まれる."""
        target = local_today() + timedelta(days=1)

        self._login()
        resp = self.client.get(
            f"/parent-portal/children/{self.child_id}/contact?date={target.isoformat()}",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.text

        # W1 の hidden フィールド
        self.assertIn('name="contact_layout_version"', body)
        self.assertIn('value="2"', body)
        self.assertIn('name="copied_from_previous"', body)
        self.assertIn('value="0"', body)

    def test_contact_form_renders_for_absence_mode(self):
        """欠席モードでもテンプレートがレンダリングされる."""
        target = local_today() + timedelta(days=1)

        self._login()
        resp = self.client.get(
            f"/parent-portal/children/{self.child_id}/contact?date={target.isoformat()}&notice=saved",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.text

        # notice が表示される
        self.assertIn("日次連絡を保存しました", body)

    def test_contact_form_with_copy_previous_query(self):
        """copy_previous=1 クエリで前回値がフォームに反映される."""
        target = local_today() + timedelta(days=1)
        prev_date = target - timedelta(days=1)

        self._login()
        with Session(self.engine) as session:
            prev_entry = DailyContactEntry(
                child_id=self.child_id,
                parent_account_id=self.parent_id,
                target_date=prev_date,
                temperature="36.6",
                contact_type=ParentContactType.present,
                extra_data={
                    "breakfast_appetite": "完食",
                    "dinner_appetite": "半分",
                },
            )
            session.add(prev_entry)
            session.commit()

        resp = self.client.get(
            f"/parent-portal/children/{self.child_id}/contact?"
            f"date={target.isoformat()}&copy_previous=1",
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.text

        # 前回の値が反映されたnoticeが表示される
        self.assertIn("前回の入力", body)
        self.assertIn("を反映しました", body)


if __name__ == "__main__":
    unittest.main()
