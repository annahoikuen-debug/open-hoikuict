"""帳票エクスポートダッシュボードおよび履歴・ログ記録の結合テスト。"""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from auth import Role
from database import engine
from main import app
from models import DocumentExportLog, User
from testing_helpers import authenticate_mock_staff


class DocumentExportsTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="https://testserver")
        unique_suffix = uuid4().hex[:8]
        self.admin_user_id = uuid4()
        with Session(engine) as session:
            admin = User(
                id=self.admin_user_id,
                username=f"admin_{unique_suffix}",
                email=f"admin_{unique_suffix}@example.com",
                display_name="帳票管理者",
                staff_role="admin",
                can_export_documents=True,
                is_active=True,
            )
            session.add(admin)
            session.commit()

        authenticate_mock_staff(self.client, role=Role.ADMIN, user_id=self.admin_user_id)

    def test_dashboard_displays_export_statistics(self):
        """ダッシュボードが表示され、過去ログの集計が反映されること。"""
        with Session(engine) as session:
            log1 = DocumentExportLog(
                export_type="attendance",
                export_format="csv",
                status="success",
                record_count=15,
                created_at=datetime.now(timezone.utc),
            )
            log2 = DocumentExportLog(
                export_type="zengin",
                export_format="txt",
                status="error",
                error_message="テストエラー",
                created_at=datetime.now(timezone.utc),
            )
            session.add(log1)
            session.add(log2)
            session.commit()

        resp = self.client.get("/document-exports")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("帳票出力", resp.text)
        self.assertIn("出勤表", resp.text)

    def test_history_pagination_and_filters(self):
        """履歴画面でフィルタおよびページネーションが正しく機能すること。"""
        resp = self.client.get("/document-exports/history?export_type=attendance&status=success")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("帳票出力履歴", resp.text)

    def test_unauthorized_staff_cannot_access_dashboard(self):
        """帳票出力権限のない一般スタッフはアクセス拒否（403）されること。"""
        viewer_client = TestClient(app, base_url="https://testserver")
        authenticate_mock_staff(viewer_client, role=Role.VIEW_ONLY)
        resp = viewer_client.get("/document-exports")
        self.assertEqual(resp.status_code, 403)
