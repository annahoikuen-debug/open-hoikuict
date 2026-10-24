from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import StaffUser, get_current_staff_user, require_admin, require_can_edit
from database import get_session
from models import StaffPaidLeave, StaffPaidLeaveRequest
from template_utils import create_templates
from time_utils import utc_now

router = APIRouter(prefix="/paid-leave", tags=["paid-leave"])
templates = create_templates()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def list_paid_leave(
    request: Request,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_can_edit(current_user)

    # 1. 職員の有給台帳取得
    leave_records = session.exec(
        select(StaffPaidLeave).where(StaffPaidLeave.staff_user_id == current_user.user_id)
    ).all()
    total_granted = sum(r.granted_days for r in leave_records)
    total_used = sum(r.used_days for r in leave_records)
    remaining_days = max(0.0, total_granted - total_used)

    # 2. 申請履歴取得
    if current_user.is_admin:
        # 管理者は全職員の申請を確認可能
        requests = session.exec(
            select(StaffPaidLeaveRequest).order_by(StaffPaidLeaveRequest.applied_at.desc())
        ).all()
    else:
        requests = session.exec(
            select(StaffPaidLeaveRequest)
            .where(StaffPaidLeaveRequest.staff_user_id == current_user.user_id)
            .order_by(StaffPaidLeaveRequest.applied_at.desc())
        ).all()

    return templates.TemplateResponse(
        request,
        "paid_leave/index.html",
        {
            "request": request,
            "current_user": current_user,
            "leave_records": leave_records,
            "total_granted": total_granted,
            "total_used": total_used,
            "remaining_days": remaining_days,
            "requests": requests,
            "applied": request.query_params.get("applied") == "1",
            "approved": request.query_params.get("approved") == "1",
            "rejected": request.query_params.get("rejected") == "1",
        },
    )


@router.post("/requests")
def apply_paid_leave(
    target_date: str = Form(...),
    days: float = Form(default=1.0),
    reason: str = Form(default="有給休暇"),
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_can_edit(current_user)

    try:
        parsed_date = date.fromisoformat(target_date.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="日付形式が不正です (YYYY-MM-DD)") from exc

    if days <= 0 or days > 30:
        raise HTTPException(status_code=422, detail="日数は0より大きく30日以内で指定してください")

    req = StaffPaidLeaveRequest(
        staff_user_id=current_user.user_id,
        target_date=parsed_date,
        days=days,
        reason=reason.strip() or "有給休暇",
        status="PENDING",
        applied_at=utc_now(),
    )
    session.add(req)
    session.commit()
    session.refresh(req)

    return RedirectResponse(url="/paid-leave?applied=1", status_code=303)


@router.post("/requests/{req_id}/approve")
def approve_paid_leave(
    req_id: UUID,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_admin(current_user)

    req = session.get(StaffPaidLeaveRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="申請が見つかりません")

    if req.status != "PENDING":
        raise HTTPException(status_code=400, detail="未処理の申請のみ承認できます")

    # 有給残日数の減算（最も失効日が近い、または直近の付与台帳から充当）
    leaves = session.exec(
        select(StaffPaidLeave)
        .where(StaffPaidLeave.staff_user_id == req.staff_user_id)
        .order_by(StaffPaidLeave.expires_on.asc())
    ).all()

    remaining_to_deduct = req.days
    for leave in leaves:
        available = leave.granted_days - leave.used_days
        if available > 0:
            deduct = min(available, remaining_to_deduct)
            leave.used_days += deduct
            remaining_to_deduct -= deduct
            session.add(leave)
            if remaining_to_deduct <= 0:
                break

    req.status = "APPROVED"
    req.decided_at = utc_now()
    req.decided_by = str(current_user.user_id)
    session.add(req)
    session.commit()

    return RedirectResponse(url="/paid-leave?approved=1", status_code=303)


@router.post("/requests/{req_id}/reject")
def reject_paid_leave(
    req_id: UUID,
    comment: str = Form(default=""),
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_admin(current_user)

    req = session.get(StaffPaidLeaveRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="申請が見つかりません")

    if req.status != "PENDING":
        raise HTTPException(status_code=400, detail="未処理の申請のみ差戻しできます")

    req.status = "REJECTED"
    req.comment = comment.strip() or None
    req.decided_at = utc_now()
    req.decided_by = str(current_user.user_id)
    session.add(req)
    session.commit()

    return RedirectResponse(url="/paid-leave?rejected=1", status_code=303)
