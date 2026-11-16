"""指導案（日案・月案）図表・画像添付機能 (P2-2) のテスト。"""
import io
import unittest
from PIL import Image

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import child_records.models  # noqa: F401
from plan_docs.auth_adapter import Role, StaffUser, resolve_plan_docs_staff_user
from plan_docs.contracts import DocumentStatus, DocumentType
from plan_docs.db_models import PlanDocumentAttachmentRow, PlanDocumentRow
import plan_docs.routers.documents as plan_docs_documents_router_module
from plan_docs.services.daily_export_layout import render_daily_plan_pdf
from plan_docs.store import SqlModelDocumentRepository, get_document_repository


def create_test_image_bytes() -> bytes:
    """テスト用のシンプルなPNG画像バイナリを生成する。"""
    buf = io.BytesIO()
    img = Image.new("RGB", (120, 80), color=(79, 70, 229))
    img.save(buf, format="PNG")
    return buf.getvalue()


class PlanDocAttachmentsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.current_user = StaffUser(
            role=Role.ADMIN,
            actor_ref="staff:admin",
            nursery_ref="default",
            classroom_refs=("hiyoko",),
            name="園長",
        )

        with Session(self.engine) as session:
            doc = PlanDocumentRow(
                document_type=DocumentType.DAILY_PLAN.value,
                status=DocumentStatus.DRAFT.value,
                title="ひよこ組 デイリー指導案",
                nursery_ref="default",
                classroom_ref="hiyoko",
                owner_name="山田花子",
                target_date="2026-11-17",
            )
            session.add(doc)
            session.commit()
            self.document_id = doc.id

    def tearDown(self):
        self.engine.dispose()

    def _create_test_client(self):
        app = FastAPI()
        app.include_router(plan_docs_documents_router_module.router, prefix="/plans")

        def override_repository():
            session = Session(self.engine)
            try:
                yield SqlModelDocumentRepository(session)
            finally:
                session.close()

        def override_current_user():
            return self.current_user

        app.dependency_overrides[get_document_repository] = override_repository
        app.dependency_overrides[resolve_plan_docs_staff_user] = override_current_user
        return TestClient(app)

    def test_upload_list_and_delete_attachment(self):
        """画像のアップロード、一覧取得、バイナリ配信、削除ができること (P2-2)。"""
        client = self._create_test_client()
        png_bytes = create_test_image_bytes()

        # 1. 一覧取得（初期状態は空）
        resp_list0 = client.get(f"/plans/documents/{self.document_id}/attachments")
        self.assertEqual(resp_list0.status_code, 200)
        self.assertEqual(resp_list0.json(), [])

        # 2. アップロード (JSON レスポンス)
        resp_upload = client.post(
            f"/plans/documents/{self.document_id}/attachments",
            files={"file": ("garden_map.png", png_bytes, "image/png")},
            data={"caption": "園庭散歩マップ", "layout_position": "appendix"},
            headers={"Accept": "application/json"},
        )
        self.assertEqual(resp_upload.status_code, 200)
        data = resp_upload.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["caption"], "園庭散歩マップ")
        att_id = data["attachment_id"]

        # DB 上に保存されていることの検証
        with Session(self.engine) as session:
            row = session.get(PlanDocumentAttachmentRow, att_id)
            self.assertIsNotNone(row)
            self.assertEqual(row.plan_document_id, self.document_id)
            self.assertEqual(row.caption, "園庭散歩マップ")
            self.assertEqual(row.content, png_bytes)

        # 3. 一覧取得（1件存在）
        resp_list1 = client.get(f"/plans/documents/{self.document_id}/attachments")
        self.assertEqual(resp_list1.status_code, 200)
        items = resp_list1.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], att_id)
        self.assertEqual(items[0]["caption"], "園庭散歩マップ")

        # 4. 画像バイナリ配信
        resp_img = client.get(f"/plans/documents/{self.document_id}/attachments/{att_id}")
        self.assertEqual(resp_img.status_code, 200)
        self.assertEqual(resp_img.headers["content-type"], "image/png")
        self.assertEqual(resp_img.content, png_bytes)

        # 5. 添付画像の削除
        resp_del = client.post(
            f"/plans/documents/{self.document_id}/attachments/{att_id}/delete",
            follow_redirects=False,
        )
        self.assertEqual(resp_del.status_code, 303)

        with Session(self.engine) as session:
            deleted_row = session.get(PlanDocumentAttachmentRow, att_id)
            self.assertIsNone(deleted_row)

    def test_render_daily_plan_pdf_with_attachments(self):
        """添付画像付き日案の A4 縦 PDF 帳票が正常に生成されること (P2-2)。"""
        png_bytes = create_test_image_bytes()
        plan_data = {
            "title": "デイリー指導計画（日案）",
            "facility_name": "あんな保育園",
            "target_date": "2026-11-17",
            "weather": "晴",
            "classroom_name": "ひよこ組",
            "age_class": "1歳児",
            "owner_name": "山田花子",
            "daily_aims": "落ち葉の感触を楽しむ",
            "daily_health_safety": "手洗い・うがい",
            "timeline_rows": [],
            "reflection": "元気に遊べました",
            "attachments": [
                {
                    "file_name": "garden_layout.png",
                    "caption": "園庭落ち葉プール配置図",
                    "content": png_bytes,
                    "layout_position": "appendix",
                }
            ],
        }

        pdf_bytes = render_daily_plan_pdf(plan_data)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 2000)


if __name__ == "__main__":
    unittest.main()
