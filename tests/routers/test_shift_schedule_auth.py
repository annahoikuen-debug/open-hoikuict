"""シフト管理APIの認証・認可制御回帰テスト。

未認証アクセス時の401拒否、閲覧権限ユーザーの編集・求解操作時の403拒否を検証する。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from auth import Role
from database import engine
from main import app
from shift_schedule.contracts import PlanStatus
from shift_schedule.db_models import ShiftPlans
from shift_schedule.store import SqlModelShiftRepository
from testing_helpers import authenticate_mock_staff


@pytest.fixture
def plan_id():
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        plan = ShiftPlans(target_month="2026-11", status=PlanStatus.DRAFT)
        repo.create_plan(plan)
        return plan.id


def test_unauthenticated_requests_are_rejected(plan_id):
    """未認証クライアントからのリクエストは認証・CSRF防御により 401 または 403 で拒否されること。"""
    from csrf import CSRF_COOKIE_NAME

    client = TestClient(app, base_url="https://testserver")

    # GET エンドポイント（CSRF不要）: 未認証のため 401
    assert client.get("/shifts/").status_code == 401
    assert client.get("/shifts/plans").status_code == 401
    assert client.get(f"/shifts/plans/{plan_id}").status_code == 401
    assert client.get(f"/shifts/plans/{plan_id}/export.csv").status_code == 401
    assert client.get("/shifts/facility").status_code == 401
    assert client.get("/shifts/contracts").status_code == 401

    # POST エンドポイント（CSRFトークン付与）: 未認証のため 401
    client.get("/healthz")
    token = client.cookies.get(CSRF_COOKIE_NAME) or ""

    assert client.post("/shifts/plans", data={"target_month": "2026-12", "csrf_token": token}).status_code == 401
    assert client.post(f"/shifts/plans/{plan_id}/solve", data={"csrf_token": token}).status_code == 401
    assert client.post(f"/shifts/plans/{plan_id}/cells", data={"csrf_token": token}).status_code == 401
    assert client.post(f"/shifts/plans/{plan_id}/approve", data={"csrf_token": token}).status_code == 401
    assert client.post("/shifts/facility", data={"csrf_token": token}).status_code == 401


def test_view_only_user_cannot_edit_or_solve(plan_id):
    """閲覧権限のみの職員は、編集・求解・承認・施設設定変更が 403 Forbidden となること。"""
    from csrf import CSRF_COOKIE_NAME

    client = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(client, role=Role.VIEW_ONLY)

    # 閲覧は可能
    assert client.get("/shifts/").status_code == 200
    assert client.get("/shifts/plans").status_code == 200
    assert client.get(f"/shifts/plans/{plan_id}").status_code == 200

    token = client.cookies.get(CSRF_COOKIE_NAME) or ""

    # 作成・求解・承認・セル編集は 403
    assert client.post("/shifts/plans", data={"target_month": "2026-12", "csrf_token": token}).status_code == 403
    assert client.post(f"/shifts/plans/{plan_id}/solve", data={"csrf_token": token}).status_code == 403
    assert client.post(f"/shifts/plans/{plan_id}/approve", data={"csrf_token": token}).status_code == 403
    assert client.post(f"/shifts/plans/{plan_id}/cells", data={"csrf_token": token}).status_code == 403

    # 管理者専用エンドポイント（施設設定・契約）は 403
    assert client.get("/shifts/facility").status_code == 403
    assert client.get("/shifts/contracts").status_code == 403
