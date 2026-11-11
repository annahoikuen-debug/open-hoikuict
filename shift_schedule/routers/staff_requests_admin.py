"""園長・管理者側 希望休承認ルーター。

GET /shifts/requests - 承認待ち希望休一覧
POST /shifts/requests/{id}/approve - 承認
POST /shifts/requests/{id}/reject - 却下
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select

from audit_logger import record_audit_event
from auth import StaffUser, get_current_staff_user, require_admin
from models import User
from ..db_models import StaffShiftUnavailability
from ..store import ShiftRepository, ShiftRepositoryDep

router = APIRouter(prefix="/shifts", tags=["shift_requests_admin"])


@router.get("/requests", response_class=HTMLResponse)
def admin_shift_requests_list(
    request: Request,
    current_user: StaffUser = Depends(get_current_staff_user),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> HTMLResponse:
    require_admin(current_user)

    all_users = repo.session.exec(select(User)).all()
    user_name_map = {}
    for u in all_users:
        name = u.display_name or u.email
        user_name_map[str(u.id)] = name
        user_name_map[u.id.hex] = name

    requests = repo.session.exec(
        select(StaffShiftUnavailability)
        .order_by(StaffShiftUnavailability.target_date.desc(), StaffShiftUnavailability.id.desc())
    ).all()

    from template_utils import create_templates
    templates = create_templates()
    return templates.TemplateResponse(
        request,
        "shift_schedule/requests_admin.html",
        {
            "request": request,
            "requests": requests,
            "user_name_map": user_name_map,
        },
    )


@router.post("/requests/{req_id}/approve")
def admin_approve_shift_request(
    req_id: int,
    request: Request,
    current_user: StaffUser = Depends(get_current_staff_user),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    require_admin(current_user)

    item = repo.session.get(StaffShiftUnavailability, req_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Request not found")

    item.status = "approved"
    repo.session.add(item)
    repo.session.commit()

    record_audit_event(
        actor_user_id=str(current_user.user_id),
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        target_resource="staff_shift_unavailability",
        resource_id=req_id,
        action="shift_request_approved",
        ip_address=request.client.host if request.client else None,
        detail={"target_date": item.target_date.isoformat(), "staff_user_id": item.staff_user_id},
    )
    return RedirectResponse(url="/shifts/requests", status_code=303)


@router.post("/requests/{req_id}/reject")
def admin_reject_shift_request(
    req_id: int,
    request: Request,
    current_user: StaffUser = Depends(get_current_staff_user),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    require_admin(current_user)

    item = repo.session.get(StaffShiftUnavailability, req_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Request not found")

    item.status = "rejected"
    repo.session.add(item)
    repo.session.commit()

    record_audit_event(
        actor_user_id=str(current_user.user_id),
        actor_role=current_user.role.value if hasattr(current_user.role, "value") else str(current_user.role),
        target_resource="staff_shift_unavailability",
        resource_id=req_id,
        action="shift_request_rejected",
        ip_address=request.client.host if request.client else None,
        detail={"target_date": item.target_date.isoformat(), "staff_user_id": item.staff_user_id},
    )
    return RedirectResponse(url="/shifts/requests", status_code=303)

