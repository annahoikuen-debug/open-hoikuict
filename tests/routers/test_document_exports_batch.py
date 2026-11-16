"""複数クラス帳票一括出力 (ZIP) の結合テスト。"""

from __future__ import annotations

import io
import unittest
import zipfile
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from auth import Role
from database import engine
from main import app
from models import Classroom, DocumentExportLog, User
from testing_helpers import authenticate_mock_staff


class DocumentExportsBatchTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="https://testserver")
        unique_suffix = uuid4().hex[:8]
        self.admin_user_id = uuid4()
        with Session(engine) as session:
            admin = User(
                id=self.admin_user_id,
                username=f"admin_batch_{unique_suffix}",
                email=f"admin_batch_{unique_suffix}@example.com",
                display_name="帳票一括管理者",
                staff_role="admin",
                can_export_documents=True,
                is_active=True,
            )
            session.add(admin)

            # テスト用クラス作成（既存があれば取得、なければ作成）
            self.classroom_ids = []
            self.classroom_names = []
            for name in [f"ひよこ_{unique_suffix}組", f"すみれ_{unique_suffix}組"]:
                c = Classroom(name=name, display_order=1)
                session.add(c)
                session.commit()
                session.refresh(c)
                self.classroom_ids.append(c.id)
                self.classroom_names.append(c.name)

        authenticate_mock_staff(self.client, role=Role.ADMIN, user_id=self.admin_user_id)

    def test_batch_export_requires_permission(self):
        """帳票出力権限のない一般スタッフはアクセス拒否（403）されること。"""
        viewer_client = TestClient(app, base_url="https://testserver")
        authenticate_mock_staff(viewer_client, role=Role.VIEW_ONLY)
        resp = viewer_client.get(
            f"/document-exports/download/monthly-class-batch?classroom_ids={self.classroom_ids[0]}"
        )
        self.assertEqual(resp.status_code, 403)

    def test_batch_export_requires_classroom_ids(self):
        """クラス未指定時は 400 エラーとなること。"""
        resp = self.client.get("/document-exports/download/monthly-class-batch")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("クラスを1つ以上選択してください", resp.text)

    def test_batch_export_invalid_month(self):
        """対象月が不正な形式の場合は 400 エラーとなること。"""
        resp = self.client.get(
            f"/document-exports/download/monthly-class-batch?month=invalid-date&classroom_ids={self.classroom_ids[0]}"
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("対象月の形式が正しくありません", resp.text)

    def test_batch_export_success_zip(self):
        """複数クラスを選択して月案一括ZIPが正しくダウンロードでき、ログに記録されること。"""
        params = [("month", "2026-11")] + [("classroom_ids", cid) for cid in self.classroom_ids]

        resp = self.client.get("/document-exports/download/monthly-class-batch", params=params)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/zip")
        self.assertIn("attachment;", resp.headers.get("content-disposition", ""))

        # ZIPの解凍・内容検証
        zip_buf = io.BytesIO(resp.content)
        with zipfile.ZipFile(zip_buf, "r") as zf:
            namelist = zf.namelist()
            self.assertEqual(len(namelist), len(self.classroom_ids))
            for name in self.classroom_names:
                matched = [n for n in namelist if name in n and n.endswith(".pdf")]
                self.assertEqual(len(matched), 1)

        # ログ記録の検証
        with Session(engine) as session:
            log = session.exec(
                select(DocumentExportLog)
                .where(
                    DocumentExportLog.export_type == "monthly_class_batch",
                    DocumentExportLog.exported_by_user_id == self.admin_user_id,
                )
                .order_by(DocumentExportLog.created_at.desc())
            ).first()
            self.assertIsNotNone(log)
            self.assertEqual(log.export_format, "zip")
            self.assertEqual(log.record_count, len(self.classroom_ids))
            self.assertEqual(log.status, "success")
            self.assertEqual(log.target_month, "2026-11")

    def test_dashboard_renders_batch_export_form(self):
        """ダッシュボードに一括ZIP出力のフォームとクラス一覧が表示されること。"""
        resp = self.client.get("/document-exports")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("複数クラス帳票一括出力 (ZIP バッチ)", resp.text)
        self.assertIn("batch-export-form", resp.text)
        self.assertIn("まとめてZIPダウンロード", resp.text)
        for name in self.classroom_names:
            self.assertIn(name, resp.text)
