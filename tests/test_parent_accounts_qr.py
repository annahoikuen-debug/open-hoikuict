"""保護者登録QRコード管理画面のアクセス認可テスト。"""
from __future__ import annotations

from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from auth import Role
from database import create_db_and_tables, engine
from main import app
from models import User
from testing_helpers import authenticate_mock_staff


@pytest.fixture
def admin_client():
    create_db_and_tables()
    admin_user_id = uuid4()
    unique_suffix = admin_user_id.hex[:8]
    with Session(engine) as session:
        admin = User(
            id=admin_user_id,
            username=f"admin_qr_{unique_suffix}",
            email=f"admin_qr_{unique_suffix}@example.com",
            display_name="QR管理者",
            staff_role="admin",
            can_export_documents=True,
            is_active=True,
        )
        session.add(admin)
        session.commit()

    c = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(c, role=Role.ADMIN, user_id=admin_user_id)
    return c


def test_registration_qr_page_accessible_in_mock_env(admin_client):
    resp = admin_client.get("/parent-accounts/registration-qr")
    assert resp.status_code == 200
    assert "QR" in resp.text or "登録" in resp.text


def test_registration_qr_svg_accessible_in_mock_env(admin_client):
    resp = admin_client.get("/parent-accounts/registration-qr.svg")
    assert resp.status_code == 200
    assert "image/svg+xml" in resp.headers.get("content-type", "")
