"""nusoft export と NuShift (shiftai) の往復データ連携結合テスト。

nusoft からエクスポートされた ZIP 内の CSV 群（園児・職員・希望休）が
NuShift のデータローダー仕様に完全準拠し、エラーなく読み込めることを検証する。
"""
from __future__ import annotations

import io
import sys
import zipfile
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from auth import Role
from database import create_db_and_tables, engine
from main import app
from models import User
from testing_helpers import authenticate_mock_staff

# E:\nushift\nushift が存在すればインポート
NUSHIFT_DIR = r"E:\nushift\nushift\src"
if NUSHIFT_DIR not in sys.path:
    sys.path.insert(0, NUSHIFT_DIR)


@pytest.fixture
def admin_client():
    create_db_and_tables()
    admin_user_id = uuid4()
    unique_suffix = admin_user_id.hex[:8]
    with Session(engine) as session:
        admin = User(
            id=admin_user_id,
            username=f"admin_rt_{unique_suffix}",
            email=f"admin_rt_{unique_suffix}@example.com",
            display_name="連携管理者",
            staff_role="admin",
            can_export_documents=True,
            is_active=True,
        )
        session.add(admin)
        session.commit()

    c = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(c, role=Role.ADMIN, user_id=admin_user_id)
    return c


def test_nushift_export_zip_structure_and_headers(admin_client):
    """エクスポートされた ZIP 内に 3つの必須 CSV が存在し、ヘッダーが NuShift 準拠であること。"""
    resp = admin_client.get("/shifts/nushift-export?month=2026-12&kind=zip")
    assert resp.status_code == 200
    assert "application/zip" in resp.headers.get("content-type", "")

    with zipfile.ZipFile(io.BytesIO(resp.content), "r") as zf:
        namelist = zf.namelist()
        assert "children_2026-12.csv" in namelist
        assert "staff_2026-12.csv" in namelist
        assert "preferences_2026-12.csv" in namelist

        # children ヘッダー検証
        children_csv = zf.read("children_2026-12.csv").decode("utf-8-sig")
        c_first_line = children_csv.splitlines()[0]
        assert "園児ID" in c_first_line and "登園時刻" in c_first_line

        # staff ヘッダー検証
        staff_csv = zf.read("staff_2026-12.csv").decode("utf-8-sig")
        s_first_line = staff_csv.splitlines()[0]
        assert "職員ID" in s_first_line and "氏名" in s_first_line

        # preferences ヘッダー検証
        pref_csv = zf.read("preferences_2026-12.csv").decode("utf-8-sig")
        p_first_line = pref_csv.splitlines()[0]
        assert "職員ID" in p_first_line and "種別" in p_first_line and "日付" in p_first_line


def test_nushift_data_loader_compatibility(admin_client):
    """NuShift (shiftai.data_loader) でパースした際にエラー issue が 0件であること。"""
    try:
        from shiftai.data_loader import load_children, load_staff, load_preferences, read_table
    except ImportError:
        pytest.skip("NuShift (shiftai) が環境に存在しないためスキップ")

    resp = admin_client.get("/shifts/nushift-export?month=2026-12&kind=zip")
    assert resp.status_code == 200

    with zipfile.ZipFile(io.BytesIO(resp.content), "r") as zf:
        c_bytes = zf.read("children_2026-12.csv")
        s_bytes = zf.read("staff_2026-12.csv")
        p_bytes = zf.read("preferences_2026-12.csv")

    c_df = read_table(c_bytes, kind="children")
    s_df = read_table(s_bytes, kind="staff")
    p_df = read_table(p_bytes, kind="preferences")

    _children, c_issues = load_children(c_df)
    _staff, s_issues = load_staff(s_df)
    _prefs, p_issues = load_preferences(p_df)

    c_errors = [i for i in c_issues if i.level == "error"]
    s_errors = [i for i in s_issues if i.level == "error"]
    p_errors = [i for i in p_issues if i.level == "error"]

    assert len(c_errors) == 0, f"Children load errors: {c_errors}"
    assert len(s_errors) == 0, f"Staff load errors: {s_errors}"
    assert len(p_errors) == 0, f"Preferences load errors: {p_errors}"
