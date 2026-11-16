"""連絡帳ダブルチェック承認フロー (P4-3) およびツアー永続化 (P1-2) のテスト。"""
from datetime import date
import unittest
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

import child_records.models  # noqa: F401
import plan_docs.db_models  # noqa: F401
from auth import Role, StaffUser
from models import (
    Child,
    ChildStatus,
    Classroom,
    DailyContactEntry,
    DailyContactReply,
    DailyContactReplyStatus,
    FacilitySettings,
    ParentAccount,
    User,
)
import routers.daily_contacts as daily_contacts_router_module
import routers.settings as settings_router_module


class DailyContactReviewFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.admin_id = uuid4()
        self.staff_id = uuid4()
        self.today = date(2026, 11, 16)

        with Session(self.engine) as session:
            admin_user = User(
                id=self.admin_id,
                email="admin@example.com",
                display_name="園長",
                staff_role=Role.ADMIN.value,
            )
            staff_user = User(
                id=self.staff_id,
                email="teacher@example.com",
                display_name="保育士A",
                staff_role=Role.CAN_EDIT.value,
            )
            parent = ParentAccount(
                display_name="山田 保護者",
                email="yamada@example.com",
            )
            classroom = Classroom(id=1, name="ひよこ組", display_order=1)
            child = Child(
                id=1,
                first_name="太郎",
                last_name="山田",
                first_name_kana="タロウ",
                last_name_kana="ヤマダ",
                birth_date=date(2023, 4, 1),
                enrollment_date=date(2025, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=1,
            )
            session.add_all([admin_user, staff_user, parent, classroom, child])
            session.flush()

            entry = DailyContactEntry(
                id=1,
                child_id=1,
                parent_account_id=parent.id,
                target_date=self.today,
                message="朝からご機嫌です。",
            )
            facility = FacilitySettings(
                contact_reply_review_required=True,  # ダブルチェック有効
            )
            session.add_all([entry, facility])
            session.commit()

        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="保育士A",
            user_id=self.staff_id,
        )

    def tearDown(self):
        self.engine.dispose()

    def _create_test_client(self):
        app = FastAPI()
        app.include_router(daily_contacts_router_module.router)
        app.include_router(settings_router_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_get_current_staff_user():
            return self.current_user

        app.dependency_overrides[daily_contacts_router_module.get_session] = override_get_session
        app.dependency_overrides[daily_contacts_router_module.get_current_staff_user] = override_get_current_staff_user
        app.dependency_overrides[settings_router_module.get_session] = override_get_session
        app.dependency_overrides[settings_router_module.get_current_staff_user] = override_get_current_staff_user
        return TestClient(app)

    def test_request_review_by_staff_creates_pending_review(self):
        """一般保育士が「確認を依頼」すると status が pending_review になること (P4-3)。"""
        client = self._create_test_client()
        resp = client.post(
            "/daily-contacts/1/reply",
            data={
                "date": self.today.isoformat(),
                "action": "request_review",
                "reply_message": "園庭で楽しく遊びました。",
            },
            headers={"X-Reply-Request": "1"},
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "確認待ち")

        with Session(self.engine) as session:
            reply = session.exec(
                select(DailyContactReply).where(
                    DailyContactReply.child_id == 1,
                    DailyContactReply.target_date == self.today,
                )
            ).first()
            self.assertIsNotNone(reply)
            self.assertEqual(reply.status, DailyContactReplyStatus.pending_review)
            self.assertEqual(reply.message, "園庭で楽しく遊びました。")
            self.assertEqual(reply.staff_name, "保育士A")
            self.assertIsNone(reply.published_at)

    def test_publish_by_staff_under_review_required_promoted_to_pending_review(self):
        """ダブルチェック必須の園では、一般保育士が「公開」を押しても自動的に確認待ちになること (P4-3)。"""
        client = self._create_test_client()
        resp = client.post(
            "/daily-contacts/1/reply",
            data={
                "date": self.today.isoformat(),
                "action": "publish",
                "reply_message": "給食を完食しました。",
            },
            headers={"X-Reply-Request": "1"},
        )
        self.assertEqual(resp.status_code, 200)

        with Session(self.engine) as session:
            reply = session.exec(
                select(DailyContactReply).where(
                    DailyContactReply.child_id == 1,
                    DailyContactReply.target_date == self.today,
                )
            ).first()
            self.assertEqual(reply.status, DailyContactReplyStatus.pending_review)
            self.assertIsNone(reply.published_at)

    def test_admin_approve_reply(self):
        """主任・園長が確認待ちの返信を承認して公開できること (P4-3)。"""
        # まず確認待ちを作成
        with Session(self.engine) as session:
            reply = DailyContactReply(
                child_id=1,
                target_date=self.today,
                status=DailyContactReplyStatus.pending_review,
                message="園庭で元気に走りました。",
                staff_name="保育士A",
            )
            session.add(reply)
            session.commit()
            reply_id = reply.id

        # 管理者としてログイン
        self.current_user = StaffUser(
            role=Role.ADMIN,
            name="園長",
            user_id=self.admin_id,
        )
        client = self._create_test_client()

        # 承認実行
        resp = client.post(
            f"/daily-contacts/replies/{reply_id}/approve",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

        with Session(self.engine) as session:
            approved_reply = session.get(DailyContactReply, reply_id)
            self.assertEqual(approved_reply.status, DailyContactReplyStatus.published)
            self.assertIsNotNone(approved_reply.published_at)
            self.assertEqual(approved_reply.reviewed_by_name, "園長")
            self.assertIsNotNone(approved_reply.reviewed_at)
            self.assertIsNone(approved_reply.rejection_reason)

    def test_admin_reject_reply_with_reason(self):
        """主任・園長が理由付きで返信を差し戻しできること (P4-3)。"""
        with Session(self.engine) as session:
            reply = DailyContactReply(
                child_id=1,
                target_date=self.today,
                status=DailyContactReplyStatus.pending_review,
                message="転びました。",
                staff_name="保育士A",
            )
            session.add(reply)
            session.commit()
            reply_id = reply.id

        # 管理者としてログイン
        self.current_user = StaffUser(
            role=Role.ADMIN,
            name="園長",
            user_id=self.admin_id,
        )
        client = self._create_test_client()

        # 差し戻し実行
        resp = client.post(
            f"/daily-contacts/replies/{reply_id}/reject",
            data={"reason": "手当ての状況を追記してください。"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)

        with Session(self.engine) as session:
            rejected_reply = session.get(DailyContactReply, reply_id)
            self.assertEqual(rejected_reply.status, DailyContactReplyStatus.rejected)
            self.assertEqual(rejected_reply.rejection_reason, "手当ての状況を追記してください。")
            self.assertEqual(rejected_reply.reviewed_by_name, "園長")
            self.assertIsNone(rejected_reply.published_at)

    def test_staff_cannot_approve_reply(self):
        """一般保育士は承認できず 403 Forbidden になること (P4-3)。"""
        with Session(self.engine) as session:
            reply = DailyContactReply(
                child_id=1,
                target_date=self.today,
                status=DailyContactReplyStatus.pending_review,
                message="テスト",
            )
            session.add(reply)
            session.commit()
            reply_id = reply.id

        # 一般保育士
        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="保育士A",
            user_id=self.staff_id,
        )
        client = self._create_test_client()

        resp = client.post(f"/daily-contacts/replies/{reply_id}/approve")
        self.assertEqual(resp.status_code, 403)

    def test_list_pending_reviews(self):
        """確認待ち一覧（GET /daily-contacts/pending-reviews）が取得できること (P4-3)。"""
        with Session(self.engine) as session:
            reply = DailyContactReply(
                child_id=1,
                target_date=self.today,
                status=DailyContactReplyStatus.pending_review,
                message="確認をお願いします。",
                staff_name="保育士A",
            )
            session.add(reply)
            session.commit()

        client = self._create_test_client()
        resp = client.get(
            "/daily-contacts/pending-reviews",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["child_name"], "山田 太郎")
        self.assertEqual(items[0]["message"], "確認をお願いします。")

    def test_onboarding_tour_persistence(self):
        """オンボーディングツアーの完了・ステータス取得・リセットが動作すること (P1-2)。"""
        client = self._create_test_client()

        # 1. 初期ステータスは未完了
        s0 = client.get("/settings/tour/status").json()
        self.assertFalse(s0["is_completed"])

        # 2. 完了登録
        c1 = client.post("/settings/tour/complete").json()
        self.assertTrue(c1["is_completed"])

        # 3. 取得して完了になっていること
        s1 = client.get("/settings/tour/status").json()
        self.assertTrue(s1["is_completed"])

        # 4. リセット実行
        r = client.post("/settings/tour/reset").json()
        self.assertFalse(r["is_completed"])

        # 5. 再取得して未完了に戻っていること
        s2 = client.get("/settings/tour/status").json()
        self.assertFalse(s2["is_completed"])


if __name__ == "__main__":
    unittest.main()
