from __future__ import annotations

import unittest
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser, get_current_staff_user
from csrf import CSRF_COOKIE_NAME, generate_csrf_token
from database import get_session
from main import app
import models  # noqa: F401
from models.core import MessageTemplate


class TestMessageTemplates(unittest.TestCase):
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

        self.client = TestClient(app, follow_redirects=False)
        self.csrf_token = generate_csrf_token()
        self.client.cookies.set(CSRF_COOKIE_NAME, self.csrf_token)
        self.headers = {"X-CSRF-Token": self.csrf_token}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()

    def test_list_and_seed_default_templates(self):
        """一覧アクセス時にデフォルトの文例が投入され、表示されること。"""
        res = self.client.get("/message-templates")
        self.assertEqual(res.status_code, 200)
        self.assertIn("定型文テンプレート管理", res.text)
        self.assertIn("園庭遊び", res.text)

        with Session(self.engine, expire_on_commit=False) as session:
            templates = session.exec(select(MessageTemplate)).all()
            self.assertGreaterEqual(len(templates), 4)

    def test_get_template_options_json(self):
        """連絡帳用・お知らせ用の定型文一覧JSONがカテゴリで取得できること。"""
        res_reply = self.client.get("/message-templates/options?category=daily_contact_reply")
        self.assertEqual(res_reply.status_code, 200)
        data = res_reply.json()
        self.assertGreaterEqual(len(data), 1)
        self.assertEqual(data[0]["category"], "daily_contact_reply")

        res_notice = self.client.get("/message-templates/options?category=notice")
        self.assertEqual(res_notice.status_code, 200)
        notice_data = res_notice.json()
        self.assertGreaterEqual(len(notice_data), 1)
        self.assertEqual(notice_data[0]["category"], "notice")

    def test_create_update_delete_template_workflow(self):
        """定型文の新規作成・更新・削除のライフサイクルが正常に動作すること。"""
        # 作成
        res_create = self.client.post(
            "/message-templates",
            data={
                "title": "カスタム文例",
                "content": "テスト用の本文です。",
                "category": "generic",
                "display_order": 99,
                "is_active": True,
            },
            headers=self.headers,
        )
        self.assertEqual(res_create.status_code, 303)

        with Session(self.engine, expire_on_commit=False) as session:
            created = session.exec(
                select(MessageTemplate).where(MessageTemplate.title == "カスタム文例")
            ).first()
            self.assertIsNotNone(created)
            self.assertEqual(created.content, "テスト用の本文です。")
            created_id = created.id

        # 更新
        res_update = self.client.post(
            f"/message-templates/{created_id}/update",
            data={
                "title": "更新後の文例",
                "content": "更新された本文です。",
                "category": "generic",
                "display_order": 1,
                "is_active": True,
            },
            headers=self.headers,
        )
        self.assertEqual(res_update.status_code, 303)

        with Session(self.engine, expire_on_commit=False) as session:
            updated = session.get(MessageTemplate, created_id)
            self.assertEqual(updated.title, "更新後の文例")
            self.assertEqual(updated.content, "更新された本文です。")

        # 削除
        res_delete = self.client.post(
            f"/message-templates/{created_id}/delete",
            headers=self.headers,
        )
        self.assertEqual(res_delete.status_code, 303)

        with Session(self.engine, expire_on_commit=False) as session:
            deleted = session.get(MessageTemplate, created_id)
            self.assertIsNone(deleted)
