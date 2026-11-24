"""夕食リマインド通知（フェーズA W2）の統合テスト。

notify_dinner_reminder() の挙動を検証する。
- 当日の夕食未入力園児の保護者に通知が送信される
- 夕食入力済み・欠席連絡済み園児は除外される
- 保護者の dinner_reminder_enabled=False でミュートされる
- リマインド時刻（19:00）前は送信されない
- 二重送信は冪等に排除される
"""

from __future__ import annotations

import unittest
from datetime import date, datetime, time, timedelta
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
    ParentNotificationKind,
    ParentPushPreference,
    ParentPushSubscription,
    ParentPushSubscriptionStatus,
    ParentPushTransport,
)
from notification_hub import notify_dinner_reminder
from routers.parent_portal import mock_login_router
import routers.parent_portal as parent_portal_module
from testing_helpers import configure_test_environment
from time_utils import ensure_utc_from_local, utc_now


def _build_engine():
    import models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _local_datetime(hour: int, minute: int = 0, day_offset: int = 0) -> datetime:
    base = datetime(2026, 11, 21, hour, minute, 0) + timedelta(days=day_offset)
    return ensure_utc_from_local(base)


class TestDinnerReminder(unittest.TestCase):
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
            self.target_date = date(2026, 11, 21)

    def _create_push_preference(self, session: Session, enabled: bool = True):
        pref = ParentPushPreference(
            parent_account_id=self.parent_id,
            push_enabled=True,
            dinner_reminder_enabled=enabled,
        )
        session.add(pref)
        session.flush()
        return pref

    def _create_push_subscription(self, session: Session):
        sub = ParentPushSubscription(
            parent_account_id=self.parent_id,
            endpoint="https://example.com/push/sub/1",
            endpoint_hash="hash1",
            p256dh_key="p256dh",
            auth_key="auth",
            status=ParentPushSubscriptionStatus.active,
            environment="development",
            transport=ParentPushTransport.capture,
        )
        session.add(sub)
        session.flush()
        return sub

    def test_dinner_reminder_sent_for_unentered_child(self):
        """当日の夕食未入力園児の保護者に通知が送信される."""
        with Session(self.engine) as session:
            self._create_push_preference(session, enabled=True)
            self._create_push_subscription(session)
            session.commit()

        result = notify_dinner_reminder(
            Session(self.engine),
            target_date=self.target_date,
            now=_local_datetime(19, 0),
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].kind, ParentNotificationKind.dinner_reminder)
        self.assertEqual(result[0].child_id, self.child_id)
        self.assertEqual(result[0].parent_account_id, self.parent_id)
        self.assertIn("夕食", result[0].body)
        self.assertIn("#meal-dinner", result[0].action_url)

    def test_dinner_reminder_not_sent_when_dinner_entered(self):
        """当日の夕食入力済み園児には通知が送信されない."""
        with Session(self.engine) as session:
            session.add(
                DailyContactEntry(
                    child_id=self.child_id,
                    parent_account_id=self.parent_id,
                    target_date=self.target_date,
                    temperature="36.6",
                    contact_type=ParentContactType.present,
                    extra_data={"dinner_appetite": "完食"},
                )
            )
            session.commit()
            self._create_push_preference(session, enabled=True)
            self._create_push_subscription(session)
            session.commit()

        result = notify_dinner_reminder(
            Session(self.engine),
            target_date=self.target_date,
            now=_local_datetime(19, 0),
        )
        self.assertEqual(len(result), 0)

    def test_dinner_reminder_not_sent_for_absent_child(self):
        """欠席連絡済み園児には通知が送信されない."""
        with Session(self.engine) as session:
            session.add(
                DailyContactEntry(
                    child_id=self.child_id,
                    parent_account_id=self.parent_id,
                    target_date=self.target_date,
                    temperature="37.5",
                    contact_type=ParentContactType.absent_sick,
                    extra_data={},
                )
            )
            session.commit()
            self._create_push_preference(session, enabled=True)
            self._create_push_subscription(session)
            session.commit()

        result = notify_dinner_reminder(
            Session(self.engine),
            target_date=self.target_date,
            now=_local_datetime(19, 0),
        )
        self.assertEqual(len(result), 0)

    def test_dinner_reminder_muted_by_preference(self):
        """保護者の dinner_reminder_enabled=False で通知が送信されない."""
        with Session(self.engine) as session:
            self._create_push_preference(session, enabled=False)
            self._create_push_subscription(session)
            session.commit()

        result = notify_dinner_reminder(
            Session(self.engine),
            target_date=self.target_date,
            now=_local_datetime(19, 0),
        )
        self.assertEqual(len(result), 0)

    def test_dinner_reminder_not_sent_before_reminder_time(self):
        """リマインド時刻（19:00）前は通知が送信されない."""
        with Session(self.engine) as session:
            self._create_push_preference(session, enabled=True)
            self._create_push_subscription(session)
            session.commit()

        result = notify_dinner_reminder(
            Session(self.engine),
            target_date=self.target_date,
            now=_local_datetime(18, 59),
        )
        self.assertEqual(len(result), 0)

    def test_dinner_reminder_idempotent_no_duplicate(self):
        """二重送信は冪等に排除される."""
        with Session(self.engine) as session:
            self._create_push_preference(session, enabled=True)
            self._create_push_subscription(session)
            session.commit()

        # 1回目
        result1 = notify_dinner_reminder(
            Session(self.engine),
            target_date=self.target_date,
            now=_local_datetime(19, 0),
        )
        self.assertEqual(len(result1), 1)

        # 2回目（同じ target_date, child_id）→ 送信されない
        result2 = notify_dinner_reminder(
            Session(self.engine),
            target_date=self.target_date,
            now=_local_datetime(19, 0),
        )
        self.assertEqual(len(result2), 0)

    def test_dinner_reminder_action_url_contains_child_id(self):
        """通知の action_url に子のIDと当日日付が含まれる."""
        with Session(self.engine) as session:
            self._create_push_preference(session, enabled=True)
            self._create_push_subscription(session)
            session.commit()

        result = notify_dinner_reminder(
            Session(self.engine),
            target_date=self.target_date,
            now=_local_datetime(19, 0),
        )
        self.assertEqual(len(result), 1)
        expected_url = (
            f"/parent-portal/children/{self.child_id}/contact?"
            f"date={self.target_date.isoformat()}#meal-dinner"
        )
        self.assertEqual(result[0].action_url, expected_url)


if __name__ == "__main__":
    unittest.main()
