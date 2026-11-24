"""案1〜6の実装を検証する統合テストスイート。"""

import os
os.environ["HOIKUICT_ENV"] = "development"
os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = "1"
os.environ["HOIKUICT_STAFF_AUTH_MODE"] = "mock"
os.environ["HOIKUICT_PARENT_AUTH_MODE"] = "mock"
os.environ["HOIKUICT_DATABASE_URL"] = "sqlite:///./simulation.db"
os.environ["HOIKUICT_CSRF_ENFORCE"] = "0"

from datetime import date
import pytest
from starlette.testclient import TestClient
from auth import Role
from csrf import generate_csrf_token, CSRF_COOKIE_NAME
from main import app
from testing_helpers import authenticate_mock_staff


@pytest.fixture
def client():
    with TestClient(app) as c:
        token = generate_csrf_token()
        c.cookies.set(CSRF_COOKIE_NAME, token)
        c.headers["x-csrf-token"] = token
        yield c


def test_case_1_pickup_snack_fallback(client: TestClient):
    """案1: snack_required 未指定時でも 400 にならず 0 (不要) にフォールバックすること。"""
    client.get("/parent-portal/mock-login/1")
    r = client.post(
        "/parent-portal/children/37/pickup",
        data={
            "date": date.today().isoformat(),
            "revision": "1",
            "planned_pickup_time": "18:00",
            "pickup_person": "父",
            "snack_required": "",  # 未選択
        },
        follow_redirects=False,
    )
    assert r.status_code in (200, 302, 303), f"Expected success but got {r.status_code}: {r.text}"


def test_case_2_daily_contact_bulk_approve(client: TestClient):
    """案2: 主任による連絡帳返信の一括承認エンドポイントが動作すること。"""
    authenticate_mock_staff(client, role=Role.ADMIN, name="主任")
    r = client.post("/daily-contacts/replies/bulk-approve", data={"reply_ids": []})
    assert r.status_code == 200, f"Error: {r.status_code} {r.text}"
    res_json = r.json()
    assert res_json["status"] == "ok"
    assert "approved_count" in res_json


def test_case_3_import_repaired_shift(client: TestClient):
    """案3: NuShift突発欠勤リペア結果のインポート同期APIが動作すること。"""
    authenticate_mock_staff(client, role=Role.ADMIN, name="園長")
    payload = {
        "target_date": "2027-01-06",
        "absent_staff_id": "S01",
        "disrupted_cells": 12,
        "repair_ms": 25.5,
    }
    r = client.post("/shifts/import-repaired-shift", json=payload)
    assert r.status_code == 200, f"Error: {r.status_code} {r.text}"
    res = r.json()
    assert res["synced"] is True
    assert res["disrupted_cells"] == 12


def test_case_4_attendance_checks_classroom_filter(client: TestClient):
    """案4: クラスID指定での出欠点検画面が正常に表示されること。"""
    authenticate_mock_staff(client, role=Role.CAN_EDIT, name="ひよこ組担任")
    r = client.get("/attendance-checks/?classroom_id=1")
    assert r.status_code == 200, f"Error: {r.status_code} {r.text}"


def test_case_5_zengin_preflight_alert(client: TestClient):
    """案5: 全銀事前チェックAPIが動作し、未転送チェックが実行されること。"""
    import uuid
    from database import get_session
    from models.core import User

    session = next(get_session())
    uid = uuid.uuid4()
    admin_user = User(
        id=uid,
        display_name="テスト園長",
        email=f"test_director_{str(uid)[:8]}@example.com",
        staff_role="admin",
        is_active=True,
        can_export_zengin=True,
    )
    session.add(admin_user)
    session.commit()

    authenticate_mock_staff(client, role=Role.ADMIN, user_id=uid, name="テスト園長")
    r = client.get("/billing/zengin/1/preflight")
    # 正常に権限を通過して事前チェックが走ること (403以外)
    assert r.status_code in (200, 404), f"Unexpected status: {r.status_code} {r.text}"


def test_case_6_bulk_health_checks(client: TestClient):
    """案6: クラス一括の午睡・健康チェックAPIが動作すること。"""
    authenticate_mock_staff(client, role=Role.CAN_EDIT, name="ひよこ組担任")
    from database import get_session
    from models.core import Child, ChildStatus
    from sqlmodel import select

    session = next(get_session())
    real_child = session.exec(select(Child)).first()
    if not real_child:
        from models.core import ChildStatus
        real_child = Child(
            last_name="テスト",
            first_name="園児",
            last_name_kana="テスト",
            first_name_kana="エンジ",
            registration_verification_name="テスト エンジ",
            birth_date=date(2023, 4, 1),
            enrollment_date=date(2026, 4, 1),
            status=ChildStatus.enrolled,
        )
        session.add(real_child)
        session.commit()
        session.refresh(real_child)
    target_id = real_child.id

    r = client.post(
        "/health/bulk-checks",
        data={
            "child_ids": [target_id],
            "temperature": "36.5",
            "general_condition": "午睡中・呼吸良好",
        },
    )
    assert r.status_code == 200, f"Error: {r.status_code} {r.text}"
    res = r.json()
    assert res["status"] == "ok"
    assert res["created_count"] >= 1
