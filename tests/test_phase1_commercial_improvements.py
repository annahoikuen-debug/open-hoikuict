from __future__ import annotations

import io
import json
import uuid
import zipfile
from datetime import date
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from auth import Role
from database import engine
from main import app
from models import User
from shift_schedule.db_models import ShiftPlanCells, ShiftPlans
from testing_helpers import authenticate_mock_staff


def test_shift_export_menu_and_xlsx_print_routes() -> None:
    """#3: 未実装だった出力メニュー、Excel(.xlsx)、印刷ビューが正常応答し開発用語が露出しないこと。"""
    with Session(engine) as session:
        staff_user = User(
            username=f"shift_exp_{uuid.uuid4().hex[:8]}",
            display_name="出力テスト職員",
            email=f"shift_exp_{uuid.uuid4().hex[:8]}@example.test",
            role="staff",
        )
        session.add(staff_user)
        session.commit()
        session.refresh(staff_user)

        plan = ShiftPlans(
            target_month="2027-02",
            staffing_standard_key="national",
            status="draft",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        staff_id_str = staff_user.id.hex
        staff_user_id = staff_user.id
        cell = ShiftPlanCells(
            plan_id=plan.id,
            staff_user_id=staff_id_str,
            target_date=date(2027, 2, 1),
            slot_label="08:00-17:00",
            cell_state="work",
        )
        session.add(cell)
        session.commit()
        plan_id = plan.id

    client = TestClient(app)
    authenticate_mock_staff(client, role=Role.ADMIN, user_id=staff_user_id, name="管理者")
    res_menu = client.get(f"/shifts/plans/{plan_id}/export")
    assert res_menu.status_code == 200
    assert "未実装" not in res_menu.text
    assert "export.xlsx" in res_menu.text
    assert f"/shifts/plans/{plan_id}/print" in res_menu.text

    res_xlsx = client.get(f"/shifts/plans/{plan_id}/export.xlsx")
    assert res_xlsx.status_code == 200
    assert "spreadsheetml" in res_xlsx.headers["content-type"]
    assert len(res_xlsx.content) > 100

    res_print = client.get(f"/shifts/plans/{plan_id}/print")
    assert res_print.status_code == 200
    assert "2027-02 勤務シフト表" in res_print.text
    assert f"職員 {staff_id_str}" in res_print.text


def test_plan_detail_has_no_internal_jargon() -> None:
    """#3: plan_detail.html に Timefold / MILP などの内部開発用語が残っていないこと。"""
    template_path = Path(__file__).resolve().parent.parent / "templates" / "shift_schedule" / "plan_detail.html"
    content = template_path.read_text(encoding="utf-8")
    assert "Timefold" not in content
    assert "MILP" not in content


def test_role_based_navigation_hides_admin_links_for_teacher() -> None:
    """#1: 一般保育士セッションでは請求・システム設定・シフト管理設定がナビゲーションに出ないこと。"""
    with Session(engine) as session:
        staff_user = User(
            username=f"teacher_nav_{uuid.uuid4().hex[:8]}",
            display_name="一般担任",
            email=f"teacher_nav_{uuid.uuid4().hex[:8]}@example.test",
            role="staff",
            is_active=True,
        )
        session.add(staff_user)
        session.commit()
        session.refresh(staff_user)

    client = TestClient(app)
    authenticate_mock_staff(client, role=Role.CAN_EDIT, user_id=staff_user.id, name="一般担任")
    res = client.get("/health")
    assert res.status_code == 200
    assert 'href="/billing/"' not in res.text
    assert 'href="/settings"' not in res.text
    assert 'href="/shifts/staff"' not in res.text
    assert 'href="/attendance"' in res.text


def test_diagnostics_pack_excludes_pii_and_returns_zip() -> None:
    """#9: 管理者向け匿名診断パックが PII を含まず正常な ZIP を返すこと。"""
    secret_email = f"director-secret-{uuid.uuid4().hex[:8]}@example.com"
    with Session(engine) as session:
        admin_user = User(
            username=f"admin_diag_{uuid.uuid4().hex[:8]}",
            display_name="園長テスト",
            email=secret_email,
            role="admin",
            staff_role="admin",
            is_active=True,
        )
        session.add(admin_user)
        session.commit()
        session.refresh(admin_user)

    client = TestClient(app)
    authenticate_mock_staff(client, role=Role.ADMIN, user_id=admin_user.id, name="園長テスト")
    res = client.get("/settings/diagnostics-pack")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"

    with zipfile.ZipFile(io.BytesIO(res.content), "r") as zf:
        names = zf.namelist()
        assert "diagnostics_summary.json" in names
        summary_raw = zf.read("diagnostics_summary.json").decode("utf-8")
        assert secret_email not in summary_raw
        data = json.loads(summary_raw)
        assert "app_version" in data
        assert "database" in data
