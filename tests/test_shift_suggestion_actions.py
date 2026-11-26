"""B4: 過剰制約サジェスト 3ボタン（採用・保留・却下）のユニット・統合テスト."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from auth import Role
from csrf import CSRF_COOKIE_NAME
from database import engine
from main import app
from models import User
from shift_schedule.db_models import (
    ShiftPlans,
    ShiftSolveJobs,
    ShiftSuggestionActions,
    StaffShiftUnavailability,
)
from shift_schedule.services.diagnostics_service import (
    compute_suggestion_id,
    generate_diagnostics_report,
    get_plan_suggestions_with_state,
)
from testing_helpers import authenticate_mock_staff


def _create_plan_with_diagnostics(
    session: Session,
    *,
    target_month: str,
    suggestions: list[dict],
    status: str = "draft",
) -> tuple[ShiftPlans, ShiftSolveJobs]:
    plan = ShiftPlans(
        target_month=target_month,
        status=status,
        staffing_standard_key="fukuoka_city",
    )
    session.add(plan)
    session.commit()
    session.refresh(plan)

    diag = {
        "is_feasible": len(suggestions) == 0,
        "summary": "テスト診断",
        "total_shortfall_slots": len(suggestions),
        "shortfalls": [],
        "suggestions": suggestions,
        "top_indicted_staff": [],
    }
    job = ShiftSolveJobs(
        plan_id=plan.id,
        status="succeeded",
        stats=json.dumps({"diagnostics": diag}, ensure_ascii=False),
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return plan, job


def _csrf_headers(client: TestClient, plan_id: int) -> tuple[str, dict[str, str]]:
    client.get(f"/shifts/plans/{plan_id}")
    token = client.cookies.get(CSRF_COOKIE_NAME) or ""
    return token, {
        "Accept": "application/json",
        "X-Requested-With": "fetch",
        "X-CSRF-Token": token,
    }


def test_compute_suggestion_id_is_deterministic() -> None:
    """1. 同じサジェスト内容は同一 ID になる（type+対象日+対象のハッシュ）."""
    id1 = compute_suggestion_id("SHIFT_REQUEST_CONCESSION", "2026-12-08", ["staff_b", "staff_a"])
    id2 = compute_suggestion_id("SHIFT_REQUEST_CONCESSION", "2026-12-08", ["staff_a", "staff_b"])
    id3 = compute_suggestion_id("EXTERNAL_OR_OVERTIME", "2026-12-08", ["staff_a", "staff_b"])

    assert id1 == id2
    assert id1.startswith("sg_")
    assert id1 != id3


def test_adopt_sends_notification_once_and_rejects_duplicate() -> None:
    """2. 採用で打診通知が action_staff_ids の職員に1回だけ送信され、二重採用は409."""
    client = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(client, role=Role.ADMIN)

    staff_id = uuid4().hex
    sg_id = compute_suggestion_id("SHIFT_REQUEST_CONCESSION", "2026-12-08", [staff_id])
    sg = {
        "id": sg_id,
        "type": "SHIFT_REQUEST_CONCESSION",
        "target_date": "2026-12-08",
        "severity": "HIGH",
        "title": "2026-12-08 の希望休・有休の調整検討",
        "description": "不足あり",
        "action_staff_ids": [staff_id],
    }

    with Session(engine) as session:
        plan, _ = _create_plan_with_diagnostics(
            session, target_month="2026-12", suggestions=[sg]
        )
        plan_id = plan.id

    token, headers = _csrf_headers(client, plan_id)
    with patch(
        "shift_schedule.services.diagnostics_service.send_concession_notifications",
        return_value=[staff_id],
    ) as mock_notify:
        resp1 = client.post(
            f"/shifts/plans/{plan_id}/suggestions/{sg_id}/adopt",
            data={"csrf_token": token, "reason_note": "午前のみ可否確認"},
            headers=headers,
        )
        assert resp1.status_code == 200
        body1 = resp1.json()
        assert body1["ok"] is True
        assert body1["action"] == "adopted"
        assert body1["notified_staff_ids"] == [staff_id]
        assert mock_notify.call_count == 1

        # 二重採用は 409 Conflict で拒否され通知も再送されない
        resp2 = client.post(
            f"/shifts/plans/{plan_id}/suggestions/{sg_id}/adopt",
            data={"csrf_token": token},
            headers=headers,
        )
        assert resp2.status_code == 409
        assert mock_notify.call_count == 1


def test_hold_persists_until_resolved_and_shows_stale_days() -> None:
    """3. 保留は翌求解時に不足が残っていれば再表示・解消されていれば自動消滅."""
    sg_id = compute_suggestion_id("EXTERNAL_OR_OVERTIME", "2026-12-12", [])
    sg = {
        "id": sg_id,
        "type": "EXTERNAL_OR_OVERTIME",
        "target_date": "2026-12-12",
        "severity": "MEDIUM",
        "title": "2026-12-12 のパート延長または応援要請",
        "description": "不足あり",
        "action_staff_ids": [],
    }

    with Session(engine) as session:
        plan, _ = _create_plan_with_diagnostics(
            session, target_month="2026-12", suggestions=[sg]
        )
        # 35日前に保留されたレコードを登録
        stale_dt = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=35)
        hold_row = ShiftSuggestionActions(
            facility_id=plan.facility_id,
            plan_id=plan.id,
            suggestion_id=sg_id,
            suggestion_type="EXTERNAL_OR_OVERTIME",
            target_date="2026-12-12",
            action="hold",
            actor_name="テスト園長",
            created_at=stale_dt,
        )
        session.add(hold_row)
        session.commit()

        # 不足が残っている場合は保留として再表示 & 30日超日数が出る
        state1 = get_plan_suggestions_with_state(session, plan)
        assert len(state1["suggestions"]) == 1
        assert state1["suggestions"][0]["status"] == "hold"
        assert state1["suggestions"][0]["hold_days"] >= 35

        # 翌求解で不足解消（suggestions=[]）になった場合、自動消滅 (resolved) になる
        resolved_job = ShiftSolveJobs(
            plan_id=plan.id,
            status="succeeded",
            stats=json.dumps(
                {
                    "diagnostics": {
                        "is_feasible": True,
                        "summary": "充足",
                        "total_shortfall_slots": 0,
                        "shortfalls": [],
                        "suggestions": [],
                        "top_indicted_staff": [],
                    }
                },
                ensure_ascii=False,
            ),
        )
        session.add(resolved_job)
        session.commit()

        state2 = get_plan_suggestions_with_state(session, plan)
        assert state2["suggestions"] == []
        assert any(h.action == "resolved" and h.suggestion_id == sg_id for h in state2["history"])


def test_reject_records_reason_and_attaches_prev_rejected_to_same_type() -> None:
    """4. 却下は理由（定型+補足）を記録し、以後の同typeサジェストに「前回却下」が付く."""
    client = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(client, role=Role.ADMIN)

    sg1_id = compute_suggestion_id("SHIFT_REQUEST_CONCESSION", "2026-12-08", [])
    sg2_id = compute_suggestion_id("SHIFT_REQUEST_CONCESSION", "2026-12-15", [])
    sg1 = {
        "id": sg1_id,
        "type": "SHIFT_REQUEST_CONCESSION",
        "target_date": "2026-12-08",
        "severity": "HIGH",
        "title": "12/08 調整",
        "description": "不足",
        "action_staff_ids": [],
    }
    sg2 = {
        "id": sg2_id,
        "type": "SHIFT_REQUEST_CONCESSION",
        "target_date": "2026-12-15",
        "severity": "HIGH",
        "title": "12/15 調整",
        "description": "不足",
        "action_staff_ids": [],
    }

    with Session(engine) as session:
        plan, _ = _create_plan_with_diagnostics(
            session, target_month="2026-12", suggestions=[sg1, sg2]
        )
        plan_id = plan.id

    token, headers = _csrf_headers(client, plan_id)

    # 「その他」で補足空は 400
    bad_resp = client.post(
        f"/shifts/plans/{plan_id}/suggestions/{sg1_id}/reject",
        data={"csrf_token": token, "reason_code": "その他", "reason_note": "   "},
        headers=headers,
    )
    assert bad_resp.status_code == 400

    # 定型理由 + 補足で却下成功
    ok_resp = client.post(
        f"/shifts/plans/{plan_id}/suggestions/{sg1_id}/reject",
        data={
            "csrf_token": token,
            "reason_code": "職員の事情（冠婚葬祭・体調等）により打診不可",
            "reason_note": "家庭事情",
        },
        headers=headers,
    )
    assert ok_resp.status_code == 200

    with Session(engine) as session:
        plan_obj = session.get(ShiftPlans, plan_id)
        state = get_plan_suggestions_with_state(session, plan_obj)
        sg2_state = next(s for s in state["suggestions"] if s["id"] == sg2_id)
        assert sg2_state["prev_rejected_reason"] == "職員の事情（冠婚葬祭・体調等）により打診不可（家庭事情）"


def test_history_visible_on_plan_detail_and_unauthorized_user_forbidden() -> None:
    """5. 判断履歴がplan詳細に表示され、編集権限のない職員には編集権限がない(403)."""
    client = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(client, role=Role.ADMIN)

    sg_id = compute_suggestion_id("EXTERNAL_OR_OVERTIME", "2026-12-20", [])
    sg = {
        "id": sg_id,
        "type": "EXTERNAL_OR_OVERTIME",
        "target_date": "2026-12-20",
        "severity": "MEDIUM",
        "title": "12/20 応援要請",
        "description": "不足あり",
        "action_staff_ids": [],
    }

    with Session(engine) as session:
        plan, _ = _create_plan_with_diagnostics(
            session, target_month="2026-12", suggestions=[sg]
        )
        plan_id = plan.id

    token, headers = _csrf_headers(client, plan_id)
    hold_resp = client.post(
        f"/shifts/plans/{plan_id}/suggestions/{sg_id}/hold",
        data={"csrf_token": token},
        headers=headers,
    )
    assert hold_resp.status_code == 200

    detail_resp = client.get(f"/shifts/plans/{plan_id}")
    assert detail_resp.status_code == 200
    assert "サジェスト判断履歴" in detail_resp.text
    assert sg_id in detail_resp.text

    # 閲覧専用ユーザー (Role.VIEW_ONLY) では 403
    viewer_client = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(viewer_client, role=Role.VIEW_ONLY)
    v_token, v_headers = _csrf_headers(viewer_client, plan_id)
    forbid_resp = viewer_client.post(
        f"/shifts/plans/{plan_id}/suggestions/{sg_id}/hold",
        data={"csrf_token": v_token},
        headers=v_headers,
    )
    assert forbid_resp.status_code == 403


def test_diagnostics_pipeline_output_structure_preserved() -> None:
    """6. 求解パイプライン自体（診断レポートの内容・構造）が変わらない."""
    with Session(engine) as session:
        user = session.exec(select(User)).first()
        if user is None:
            user = User(
                email=f"diag_{uuid4().hex[:8]}@example.com",
                display_name="診断テスト職員",
                role="can_edit",
                password_hash="dummy",
            )
            session.add(user)
            session.commit()
            session.refresh(user)
        unavail = StaffShiftUnavailability(
            staff_user_id=user.id.hex,
            target_date=date(2026, 12, 25),
            kind="希望休",
            status="approved",
        )
        session.add(unavail)
        session.commit()

        fake_result = SimpleNamespace(
            overconstrained_shortfalls=[
                {"day": "2026-12-25", "slot": "08:30", "needed": 3, "assigned": 2, "deficit": 1}
            ],
            score=SimpleNamespace(is_feasible=False, indictments={}),
        )
        report = generate_diagnostics_report(fake_result, None, session)
        assert report["is_feasible"] is False
        assert report["total_shortfall_slots"] == 1
        assert len(report["suggestions"]) == 1
        sg = report["suggestions"][0]
        assert sg["type"] == "SHIFT_REQUEST_CONCESSION"
        assert sg["target_date"] == "2026-12-25"
        assert sg["id"].startswith("sg_")
        assert user.id.hex in sg["action_staff_ids"]
