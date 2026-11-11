"""職員ポータル 希望休申請ルーター。

GET /staff/shift-requests - 自分の希望休一覧 & 申請フォーム
POST /staff/shift-requests - 希望休申請 (status='pending')
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from audit_logger import record_audit_event
from auth import StaffUser, get_current_staff_user, require_can_edit
from database import get_session
from shift_schedule.db_models import StaffShiftUnavailability
from template_utils import create_templates

router = APIRouter(prefix="/staff", tags=["staff_shift_requests"])
templates = create_templates()


@router.get("/shift-requests", response_class=HTMLResponse)
def staff_shift_requests_list(
    request: Request,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
) -> HTMLResponse:
    require_can_edit(current_user)

    uid_hex = current_user.user_id.hex if hasattr(current_user.user_id, "hex") else str(current_user.user_id)
    uid_str = str(current_user.user_id)
    uids = list({uid_hex, uid_str})

    requests = session.exec(
        select(StaffShiftUnavailability)
        .where(StaffShiftUnavailability.staff_user_id.in_(uids))
        .order_by(StaffShiftUnavailability.target_date.desc(), StaffShiftUnavailability.id.desc())
    ).all()

    return templates.TemplateResponse(
        request,
        "staff_portal/shift_requests.html",
        {
            "request": request,
            "requests": requests,
            "current_user": current_user,
            "today": date.today(),
        },
    )


@router.post("/shift-requests")
def staff_submit_shift_request(
    request: Request,
    target_date: str = Form(...),
    start_time: Optional[str] = Form(None),
    end_time: Optional[str] = Form(None),
    reason: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
) -> RedirectResponse:
    require_can_edit(current_user)

    parsed_date = date.fromisoformat(target_date)
    uid_hex = current_user.user_id.hex if hasattr(current_user.user_id, "hex") else str(current_user.user_id)

    # 重複チェック（同日に既に pending または approved の希望休があるか）
    existing = session.exec(
        select(StaffShiftUnavailability).where(
            StaffShiftUnavailability.staff_user_id.in_([uid_hex, str(current_user.user_id)]),
            StaffShiftUnavailability.target_date == parsed_date,
            StaffShiftUnavailability.status.in_(["pending", "approved"]),
        )
    ).first()
    if existing is not None:
        raise HTTPException(
            status_code=400,
            detail=f"{target_date} にはすでに希望休（状態: {existing.status}）が申請されています。",
        )

    unavail = StaffShiftUnavailability(
        staff_user_id=uid_hex,
        target_date=parsed_date,
        start_time=start_time or None,
        end_time=end_time or None,
        kind="希望休",
        status="pending",
        reason=reason or "",
    )
    session.add(unavail)
    session.commit()

    record_audit_event(
        actor_user_id=str(current_user.user_id),
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        target_resource="staff_shift_unavailability",
        resource_id=unavail.id,
        action="shift_request_submitted",
        ip_address=request.client.host if request.client else None,
        detail={"target_date": target_date, "status": "pending"},
    )

    return RedirectResponse(url="/staff/shift-requests?msg=申請を受け付けました。", status_code=303)

