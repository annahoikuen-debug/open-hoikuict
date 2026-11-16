"""連絡帳詳細画面の園児間クイック移動ナビゲーション (P4-1) のテスト。"""

from __future__ import annotations

import unittest
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from auth import Role
from database import engine
from main import app
from models import Child, ChildStatus, Classroom, DailyContactReply, User
from testing_helpers import authenticate_mock_staff


class DailyContactsNavigationTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="https://testserver")
        unique_suffix = uuid4().hex[:8]
        self.staff_user_id = uuid4()
        self.day = date(2026, 11, 16)

        with Session(engine) as session:
            staff = User(
                id=self.staff_user_id,
                username=f"staff_nav_{unique_suffix}",
                email=f"staff_nav_{unique_suffix}@example.com",
                display_name="連絡帳担当",
                staff_role="staff",
                is_active=True,
            )
            session.add(staff)

            # テスト用クラスと園児2名を作成
            classroom = Classroom(name=f"ひまわり_{unique_suffix}組", display_order=1)
            session.add(classroom)
            session.commit()
            session.refresh(classroom)
            self.classroom_id = classroom.id
            self.classroom_name = classroom.name

            child1 = Child(
                first_name="太郎",
                last_name="青木",
                first_name_kana="タロウ",
                last_name_kana="アオキ",
                classroom_id=classroom.id,
                status=ChildStatus.enrolled,
                birth_date=date(2023, 5, 1),
                enrollment_date=date(2024, 4, 1),
            )
            child2 = Child(
                first_name="花子",
                last_name="佐藤",
                first_name_kana="ハナコ",
                last_name_kana="サトウ",
                classroom_id=classroom.id,
                status=ChildStatus.enrolled,
                birth_date=date(2023, 6, 1),
                enrollment_date=date(2024, 4, 1),
            )
            session.add(child1)
            session.add(child2)
            session.commit()
            session.refresh(child1)
            session.refresh(child2)
            self.child1_id = child1.id
            self.child1_name = child1.full_name
            self.child2_id = child2.id
            self.child2_name = child2.full_name

            # child1 だけ返信済みを作成
            reply1 = DailyContactReply(
                child_id=child1.id,
                target_date=self.day,
                message="本日は元気に過ごしていました。",
                published_at=date(2026, 11, 16),
            )
            session.add(reply1)
            session.commit()

        authenticate_mock_staff(self.client, role=Role.CAN_EDIT, user_id=self.staff_user_id)

    def test_navigation_bar_links_between_children(self):
        """詳細画面に前後の園児リンクおよび未返信園児へのジャンプが表示されること。"""
        # 1人目 (child1) の詳細画面
        resp = self.client.get(
            f"/daily-contacts/{self.child1_id}?date={self.day.isoformat()}&classroom_id={self.classroom_id}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("child-nav-bar", resp.text)
        # child1 は先頭なので前の園児リンクは非アクティブ
        self.assertIn("前の園児", resp.text)
        # 次の園児 (child2) へのリンクが存在すること
        self.assertIn(f"/daily-contacts/{self.child2_id}", resp.text)
        self.assertIn(self.child2_name, resp.text)
        # child2 が未返信なので、未返信園児へのジャンプリンクが存在すること
        self.assertIn("次の未返信園児へ", resp.text)

        # 2人目 (child2) の詳細画面
        resp2 = self.client.get(
            f"/daily-contacts/{self.child2_id}?date={self.day.isoformat()}&classroom_id={self.classroom_id}"
        )
        self.assertEqual(resp2.status_code, 200)
        # 前の園児 (child1) へのリンクが存在すること
        self.assertIn(f"/daily-contacts/{self.child1_id}", resp2.text)
        self.assertIn(self.child1_name, resp2.text)
        # child2 は末尾なので次の園児リンクは非アクティブ
        self.assertIn("次の園児", resp2.text)
