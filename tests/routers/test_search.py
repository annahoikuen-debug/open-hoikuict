from __future__ import annotations

from datetime import date, datetime
import unittest
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from auth import Role, StaffUser, get_current_staff_user
from database import get_session
from main import app
import models  # noqa: F401
from models.core import Child, ChildStatus, Classroom, DailyContactEntry, Family, ParentAccount
from models.notice import Notice, NoticePriority, NoticeStatus


class TestStaffSearch(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        def _override_session():
            with Session(self.engine, expire_on_commit=False) as session:
                yield session

        self.mock_user = StaffUser(
            role=Role.ADMIN,
            name="テスト管理者",
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            can_manage_child_records=True,
        )

        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[get_current_staff_user] = lambda: self.mock_user
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_search_requires_staff_authentication(self):
        """未ログイン時は401が返ること。"""
        app.dependency_overrides.pop(get_current_staff_user, None)
        res = self.client.get("/staff/search?q=テスト")
        self.assertEqual(res.status_code, 401)

    def test_search_children_and_notices_and_parents(self):
        """園児名、お知らせ、保護者名がそれぞれヒットして返ること。"""
        with Session(self.engine, expire_on_commit=False) as session:
            room = Classroom(name="ばら組")
            session.add(room)
            session.flush()

            child = Child(
                first_name="太郎",
                last_name="山田",
                first_name_kana="たろう",
                last_name_kana="やまだ",
                birth_date=date(2021, 5, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=room.id,
            )
            session.add(child)

            parent = ParentAccount(
                display_name="山田 恵子",
                email="yamada@example.test",
            )
            session.add(parent)

            notice = Notice(
                title="秋の遠足のご案内",
                body="水曜日に秋の遠足を実施します。",
                priority=NoticePriority.normal,
                status=NoticeStatus.published,
                created_at=datetime(2026, 11, 1, 10, 0),
            )
            session.add(notice)
            session.commit()

        # 園児検索
        res = self.client.get("/staff/search?q=山田", headers={"Accept": "application/json"})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertGreaterEqual(data["counts"]["child"], 1)
        self.assertGreaterEqual(data["counts"]["parent"], 1)
        self.assertIn("山田 太郎", data["results"]["child"][0]["title"])
        self.assertIn("ばら組", data["results"]["child"][0]["subtitle"])

        # お知らせ検索
        res_notice = self.client.get("/staff/search?q=遠足", headers={"Accept": "application/json"})
        self.assertEqual(res_notice.status_code, 200)
        notice_data = res_notice.json()
        self.assertGreaterEqual(notice_data["counts"]["notice"], 1)
        self.assertEqual(notice_data["results"]["notice"][0]["title"], "秋の遠足のご案内")

    def test_search_html_view(self):
        """HTML画面が正常にレンダリングされること。"""
        with Session(self.engine, expire_on_commit=False) as session:
            child = Child(
                first_name="花子",
                last_name="佐藤",
                first_name_kana="はなこ",
                last_name_kana="さとう",
                birth_date=date(2022, 1, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
            )
            session.add(child)
            session.commit()

        res = self.client.get("/staff/search?q=佐藤")
        self.assertEqual(res.status_code, 200)
        self.assertIn("佐藤 花子", res.text)
        self.assertIn("横断検索", res.text)

    def test_search_empty_and_zero_results(self):
        """空クエリおよび0件時の表示が安全であること。"""
        res_empty = self.client.get("/staff/search?q=")
        self.assertEqual(res_empty.status_code, 200)
        self.assertIn("検索キーワードを入力してください", res_empty.text)

        res_zero = self.client.get("/staff/search?q=全く一致しない文字列99999")
        self.assertEqual(res_zero.status_code, 200)
        self.assertIn("一致するデータは見つかりませんでした", res_zero.text)
