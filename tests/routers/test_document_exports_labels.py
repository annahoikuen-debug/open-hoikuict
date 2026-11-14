from datetime import datetime, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlmodel import Session

from auth import Role
from database import create_db_and_tables, engine
from main import app
from models import DocumentExportLog, User
from routers.document_exports import EXPORT_FORMAT_LABELS, EXPORT_TYPE_LABELS
from testing_helpers import authenticate_mock_staff


def test_document_exports_label_definitions():
    """NuShiftデータ種別およびZIPフォーマットがラベル定義に含まれていること。"""
    assert "nushift" in EXPORT_TYPE_LABELS
    assert EXPORT_TYPE_LABELS["nushift"] == "NuShiftデータ"

    assert "zip" in EXPORT_FORMAT_LABELS
    assert EXPORT_FORMAT_LABELS["zip"] == "ZIP"


def test_document_exports_dashboard_renders_labels():
    """ダッシュボード画面と履歴画面のHTMLにNuShiftデータとZIPの表示が含まれること。"""
    create_db_and_tables()

    admin_user_id = uuid4()
    unique_suffix = admin_user_id.hex[:8]
    with Session(engine) as session:
        admin = User(
            id=admin_user_id,
            username=f"admin_{unique_suffix}",
            email=f"admin_{unique_suffix}@example.com",
            display_name="帳票管理者",
            staff_role="admin",
            can_export_documents=True,
            is_active=True,
        )
        session.add(admin)

        # ZIP形式のNuShiftログを1件追加してテーブル描画を検証
        log = DocumentExportLog(
            export_type="nushift",
            export_format="zip",
            status="success",
            target_month="2026-11",
            exported_by_name="帳票管理者",
            created_at=datetime.now(timezone.utc),
        )
        session.add(log)
        session.commit()

    c = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(c, role=Role.ADMIN, user_id=admin_user_id)

    # 履歴画面のフィルタセレクトボックスおよび一覧行に NuShiftデータ と ZIP が含まれているか検証
    resp = c.get("/document-exports/history")
    assert resp.status_code == 200
    html = resp.text
    assert 'value="nushift"' in html
    assert "NuShiftデータ" in html
    assert "ZIP" in html
