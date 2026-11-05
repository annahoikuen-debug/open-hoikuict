"""通知イベントハブ（改善案6）のテスト。

- お知らせ公開: 対象保護者へ in_app + push 通知が作られること
- 対象絞り込み（クラス・園児・全体）が機能すること
- 同一 source への二重通知が冪等に排除されること
- アンケート公開: 期限表記つきの通知が作られること
- 職員向けアンケートは通知しないこと
"""
from __future__ import annotations

import unittest
from datetime import date, datetime

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models import (
    Classroom,
    Family,
    NotificationDeliveryChannel,
    ParentAccount,
    ParentChildLink,
    ParentNotification,
    ParentNotificationKind,
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


class NotificationHubTests(unittest.TestCase):
    def setUp(self):
        self.engine = _build_engine()
        with Session(self.engine) as session:
            family = Family(family_name="てすと")
            session.add(family)
            session.flush()
            classroom = Classroom(name="うさぎ組")
            session.add(classroom)
            session.flush()
            self.classroom_id = classroom.id
            from models import Child

            child = Child(family_id=family.id, classroom_id=classroom.id,
                          last_name="てすと", first_name="ゆうと",
                          last_name_kana="テスト", first_name_kana="ユウト",
                          birth_date=date(2022, 4, 1), enrollment_date=date(2024, 4, 1))
            session.add(child)
            session.flush()
            self.child_id = child.id
            for email in ("mother@example.com", "father@example.com"):
                parent = ParentAccount(email=email, family_id=family.id, status="active",
                                       display_name=email.split("@")[0])
                session.add(parent)
                session.flush()
                session.add(ParentChildLink(parent_account_id=parent.id, child_id=child.id))
            session.commit()

    def test_notice_published_notifies_linked_parents(self):
        from notification_hub import notify_notice_published

        with Session(self.engine) as session:
            notify_notice_published(
                session, notice_id=1, title="運動会のお知らせ",
                target_classroom_ids=[], target_child_ids=[],
                created_by_name="園長",
            )
            session.commit()

        with Session(self.engine) as session:
            notifications = session.exec(select(ParentNotification)).all()
            self.assertEqual(len(notifications), 2)
            for notification in notifications:
                self.assertEqual(notification.kind, ParentNotificationKind.notice_published)
                self.assertEqual(notification.source_type, "notice")
                self.assertEqual(notification.source_id, "1")
                self.assertIn("運動会のお知らせ", notification.body)
                self.assertFalse(notification.is_read)
            # 2件目の呼び出しでは冪等に排除される
            again = notify_notice_published(
                session, notice_id=1, title="運動会のお知らせ",
                target_classroom_ids=[], target_child_ids=[],
            )
            self.assertEqual(again, [])

    def test_notice_published_scopes_to_classroom(self):
        from notification_hub import notify_notice_published
        from models import Child as ChildModel, ParentAccount

        with Session(self.engine) as session:
            # 別クラスの園児・保護者を追加
            other_class = Classroom(name="ぞう組")
            session.add(other_class)
            session.flush()
            other_family = Family(family_name="べつ")
            session.add(other_family)
            session.flush()
            other_child = ChildModel(family_id=other_family.id, classroom_id=other_class.id,
                                     last_name="べつ", first_name="さくら",
                                     last_name_kana="ベツ", first_name_kana="サクラ",
                                     birth_date=date(2022, 6, 1), enrollment_date=date(2024, 4, 1))
            session.add(other_child)
            session.flush()
            other_parent = ParentAccount(email="other@example.com", family_id=other_family.id,
                                         status="active", display_name="other")
            session.add(other_parent)
            session.flush()
            session.add(ParentChildLink(parent_account_id=other_parent.id, child_id=other_child.id))
            session.commit()

        with Session(self.engine) as session:
            notify_notice_published(
                session, notice_id=2, title="うさぎ組遠足",
                target_classroom_ids=[self.classroom_id], target_child_ids=[],
            )
            session.commit()

        with Session(self.engine) as session:
            notified = session.exec(select(ParentNotification)).all()
            emails = {
                session.get(ParentAccount, n.parent_account_id).email for n in notified
            }
            self.assertEqual(emails, {"mother@example.com", "father@example.com"})

    def test_notice_creates_push_delivery(self):
        from notification_hub import notify_notice_published
        from models import ParentNotificationDelivery

        with Session(self.engine) as session:
            notify_notice_published(
                session, notice_id=3, title="投稿テスト",
                target_classroom_ids=[], target_child_ids=[],
            )
            session.commit()

        with Session(self.engine) as session:
            deliveries = session.exec(select(ParentNotificationDelivery)).all()
            channels = {d.channel for d in deliveries}
            self.assertIn(NotificationDeliveryChannel.in_app, channels)
            self.assertIn(NotificationDeliveryChannel.push, channels)

    def test_survey_published_with_deadline(self):
        from notification_hub import notify_survey_published

        closes_at = datetime(2026, 11, 30, 17, 0)
        with Session(self.engine) as session:
            created = notify_survey_published(
                session, survey_id=5, title="バス遅延アンケート",
                closes_at=closes_at,
                audience_child_ids=[self.child_id],
                created_by_name="主任",
            )
            session.commit()
            self.assertEqual(len(created), 2)

        with Session(self.engine) as session:
            notifications = session.exec(select(ParentNotification)).all()
            self.assertTrue(all(n.kind == ParentNotificationKind.survey_published for n in notifications))
            self.assertTrue(all("11/30" in n.body for n in notifications))
            self.assertTrue(all(n.action_url.endswith("survey_id=5") for n in notifications))
            # 冪等性
            again = notify_survey_published(
                session, survey_id=5, title="バス遅延アンケート", closes_at=closes_at,
            )
            self.assertEqual(again, [])

    def test_notice_target_date_field_defaults_to_none(self):
        from notification_hub import notify_notice_published

        with Session(self.engine) as session:
            created = notify_notice_published(
                session, notice_id=9, title="対象日なし",
                target_classroom_ids=[], target_child_ids=[],
            )
            self.assertTrue(all(n.target_date is None for n in created))
            self.assertTrue(all(isinstance(n.created_at, datetime) for n in created))


class NotifyFamiliesTests(unittest.TestCase):
    """notify_families（休園・緊急連絡・打刻訂正）とミュートのテスト（改善案6 後続）。"""

    def setUp(self):
        self.engine = _build_engine()
        with Session(self.engine) as session:
            family = Family(family_name="てすと")
            session.add(family)
            session.flush()
            parent = ParentAccount(email="mother@example.com", family_id=family.id,
                                   status="active", display_name="mother")
            session.add(parent)
            session.flush()
            session.add(ParentChildLink(parent_account_id=parent.id, child_id=1))
            session.commit()
            self.parent_id = parent.id

    def test_closure_notice_notifies(self):
        from models import ParentNotificationKind
        from notification_hub import notify_families

        with Session(self.engine) as session:
            created = notify_families(
                session, kind=ParentNotificationKind.closure_notice,
                source_type="closure", source_id="2026-11-10",
                title="休園のお知らせ", body="11月10日は休園です。",
                created_by_name="園長",
            )
            session.commit()
            self.assertEqual(len(created), 1)

        with Session(self.engine) as session:
            notifications = session.exec(select(ParentNotification)).all()
            self.assertEqual(notifications[0].kind, ParentNotificationKind.closure_notice)
            # 二重配信は冪等に排除
            again = notify_families(
                session, kind=ParentNotificationKind.closure_notice,
                source_type="closure", source_id="2026-11-10",
                title="休園のお知らせ", body="11月10日は休園です。",
            )
            self.assertEqual(again, [])

    def test_muted_parent_receives_in_app_only(self):
        from models import ParentNotificationDelivery, ParentNotificationKind, ParentPushPreference
        from notification_hub import notify_families

        with Session(self.engine) as session:
            session.add(ParentPushPreference(
                parent_account_id=self.parent_id,
                punch_correction_notice_enabled=False,
            ))
            session.commit()

        with Session(self.engine) as session:
            notify_families(
                session, kind=ParentNotificationKind.punch_correction_notice,
                source_type="punch", source_id="rec-1",
                title="打刻訂正のお知らせ", body="降園打刻を訂正しました。",
            )
            session.commit()

        with Session(self.engine) as session:
            deliveries = session.exec(select(ParentNotificationDelivery)).all()
            self.assertEqual(len(deliveries), 1)
            self.assertEqual(deliveries[0].channel, NotificationDeliveryChannel.in_app)

    def test_emergency_forces_push_despite_mute(self):
        from models import ParentNotificationDelivery, ParentNotificationKind, ParentPushPreference
        from notification_hub import notify_families

        with Session(self.engine) as session:
            session.add(ParentPushPreference(
                parent_account_id=self.parent_id,
                emergency_notice_enabled=False,
            ))
            session.commit()

        with Session(self.engine) as session:
            notify_families(
                session, kind=ParentNotificationKind.emergency_notice,
                source_type="emergency", source_id="e-1",
                title="緊急連絡", body="園庭に忘れ物があります。",
                force_push=True,
            )
            session.commit()

        with Session(self.engine) as session:
            deliveries = session.exec(select(ParentNotificationDelivery)).all()
            channels = {d.channel for d in deliveries}
            self.assertIn(NotificationDeliveryChannel.in_app, channels)
            self.assertIn(NotificationDeliveryChannel.push, channels)

    def test_unsupported_kind_rejected(self):
        from models import ParentNotificationKind
        from notification_hub import NotificationHubError, notify_families

        with Session(self.engine) as session:
            with self.assertRaises(NotificationHubError):
                notify_families(
                    session, kind=ParentNotificationKind.notice_published,
                    source_type="notice", source_id="1",
                    title="無効", body="無効",
                )


if __name__ == "__main__":
    unittest.main()
