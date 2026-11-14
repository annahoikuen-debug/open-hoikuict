from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from auth import Role
from database import create_db_and_tables, engine
from main import app
from models import DocumentExportLog, User
from testing_helpers import authenticate_mock_staff


@pytest.fixture
def test_setup():
    create_db_and_tables()

    admin_user_id = uuid4()
    unique_suffix = admin_user_id.hex[:8]
    with Session(engine) as session:
        # Clear old export logs
        for log in session.exec(select(DocumentExportLog).where(DocumentExportLog.export_type == "nushift")).all():
            session.delete(log)

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
        session.commit()

    c = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(c, role=Role.ADMIN, user_id=admin_user_id)
    return c, admin_user_id


def test_nushift_export_creates_audit_log_for_children_csv(test_setup):
    client, admin_user_id = test_setup

    resp = client.get("/shifts/nushift-export?month=2026-11&kind=children")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")

    with Session(engine) as session:
        logs = session.exec(
            select(DocumentExportLog).where(
                DocumentExportLog.export_type == "nushift",
                DocumentExportLog.export_format == "csv",
            )
        ).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.target_month == "2026-11"
        assert log.status == "success"
        assert log.exported_by_user_id == admin_user_id
        assert log.file_size_bytes is not None and log.file_size_bytes > 0


def test_nushift_export_creates_audit_log_for_staff_csv(test_setup):
    client, admin_user_id = test_setup

    resp = client.get("/shifts/nushift-export?month=2026-11&kind=staff")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")

    with Session(engine) as session:
        logs = session.exec(
            select(DocumentExportLog).where(
                DocumentExportLog.export_type == "nushift",
                DocumentExportLog.export_format == "csv",
            )
        ).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.status == "success"
        assert log.target_month == "2026-11"


def test_nushift_export_creates_audit_log_for_preferences_csv(test_setup):
    client, admin_user_id = test_setup

    resp = client.get("/shifts/nushift-export?month=2026-11&kind=preferences")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")

    with Session(engine) as session:
        logs = session.exec(
            select(DocumentExportLog).where(
                DocumentExportLog.export_type == "nushift",
                DocumentExportLog.export_format == "csv",
            )
        ).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.status == "success"
        assert log.target_month == "2026-11"


def test_nushift_export_creates_audit_log_for_zip(test_setup):
    client, admin_user_id = test_setup

    resp = client.get("/shifts/nushift-export?month=2026-11&kind=zip")
    assert resp.status_code == 200
    assert "application/zip" in resp.headers.get("content-type", "")

    with Session(engine) as session:
        logs = session.exec(
            select(DocumentExportLog).where(
                DocumentExportLog.export_type == "nushift",
                DocumentExportLog.export_format == "zip",
            )
        ).all()
        assert len(logs) == 1
        log = logs[0]
        assert log.target_month == "2026-11"
        assert log.status == "success"
        assert log.file_size_bytes is not None and log.file_size_bytes > 0


def test_nushift_export_dashboard_and_history_integration(test_setup):
    client, admin_user_id = test_setup

    # 1件ZIPを出力してログを作成
    resp_export = client.get("/shifts/nushift-export?month=2026-11&kind=zip")
    assert resp_export.status_code == 200

    # ダッシュボード画面で総出力数・成功数がカウントされていること
    resp_dash = client.get("/document-exports")
    assert resp_dash.status_code == 200
    assert "NuShiftデータ" in resp_dash.text
    assert "ZIP" in resp_dash.text

    # 履歴画面で nushift タイプで絞り込みできること
    resp_hist = client.get("/document-exports/history?export_type=nushift")
    assert resp_hist.status_code == 200
    assert "NuShiftデータ" in resp_hist.text
    assert "2026-11" in resp_hist.text
