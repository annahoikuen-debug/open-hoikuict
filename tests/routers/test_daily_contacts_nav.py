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

    def test_copy_previous_day_reply_data_rendered(self):
        """前日の返信が存在する場合、「前日の返信をコピー」ボタンとデータが提供されること (P4-4)。"""
        prev_day = date(2026, 11, 15)
        with Session(engine) as session:
            prev_reply = DailyContactReply(
                child_id=self.child2_id,
                target_date=prev_day,
                message="昨日は砂場遊びを楽しんでいました。",
                field_values={"nap_time": "12:30-14:30", "appetite": "完食"},
                published_at=date(2026, 11, 15),
            )
            session.add(prev_reply)
            session.commit()

        resp = self.client.get(
            f"/daily-contacts/{self.child2_id}?date={self.day.isoformat()}&classroom_id={self.classroom_id}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("copy-previous-reply-btn", resp.text)
        self.assertIn("前日の返信をコピー", resp.text)
        self.assertIn("11/15分", resp.text)
        self.assertIn("previous-reply-json", resp.text)

        # template タグ内の JSON がパース可能で、前日のメッセージと値が含まれていること
        import json, re
        match = re.search(r'<template id="previous-reply-json">(.*?)</template>', resp.text)
        self.assertIsNotNone(match)
        data = json.loads(match.group(1))
        self.assertEqual(data["message"], "昨日は砂場遊びを楽しんでいました。")
        self.assertEqual(data["date_label"], "11/15")
        self.assertEqual(data["values"].get("appetite"), "完食")
        self.assertEqual(data["values"].get("nap_time"), "12:30-14:30")

    def test_optimistic_lock_conflict_returns_409(self):
        """古い revision による返信保存要求に対して HTTP 409 Conflict が返ること (P4-2)。"""
        resp = self.client.post(
            f"/daily-contacts/{self.child1_id}/reply",
            data={
                "date": self.day.isoformat(),
                "revision": "outdated_revision_20261116000000",
                "action": "draft",
                "reply_message": "上書きテスト",
            },
            headers={"X-Reply-Request": "1"},
        )
        self.assertEqual(resp.status_code, 409)
        json_data = resp.json()
        self.assertIn("別の職員が更新しています", json_data.get("detail", ""))
