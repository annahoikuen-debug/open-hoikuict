"""Parent portal QR code and board check-in routes."""

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from database import get_session
from facility_settings_service import get_board_qr_version, is_board_qr_enabled
from guardian_qr_service import (
    execute_sibling_qr_punch,
    generate_parent_qr_svg,
    generate_parent_qr_token,
    get_sibling_qr_punch_info,
    verify_board_qr_token,
)

router = APIRouter()


@router.get("/qr-code.svg")
def parent_qr_code_image(
    request: Request,
    session: Session = Depends(get_session),
):
    from routers.parent_portal import _get_parent_account

    current_parent_user = _get_parent_account(request, session)
    if not current_parent_user:
        raise HTTPException(status_code=401, detail="ログインが必要です")

    token = generate_parent_qr_token(
        parent_account_id=current_parent_user.id,
        family_id=current_parent_user.family_id,
        expires_in_days=30,
    )
    svg_str = generate_parent_qr_svg(token)
    response = Response(content=svg_str, media_type="image/svg+xml")
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response


@router.get("/board-check-in", response_class=HTMLResponse)
def parent_board_check_in_page(
    request: Request,
    t: str = Query(default=""),
    session: Session = Depends(get_session),
):
    from routers.parent_portal import _get_parent_account, templates

    current_parent_user = _get_parent_account(request, session)
    if not current_parent_user:
        next_path = f"/parent-portal/board-check-in?t={quote(t, safe='')}" if t else "/parent-portal/board-check-in"
        return RedirectResponse(url=f"/parent-portal/login?redirect={quote(next_path, safe='')}", status_code=303)

    error_message = ""
    punch_info = None
    try:
        verify_board_qr_token(
            t,
            expected_version=get_board_qr_version(session),
            enabled=is_board_qr_enabled(session),
        )
        punch_info = get_sibling_qr_punch_info(session, parent_account_id=current_parent_user.id)
    except ValueError as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "parent_portal/board_check_in.html",
        {
            "current_parent_user": current_parent_user,
            "parent_portal_mode": True,
            "board_token": t,
            "error_message": error_message,
            "punch_info": punch_info,
            "completed": False,
            "completed_action": "",
            "punched_count": 0,
        },
        status_code=400 if error_message else 200,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/board-check-in", response_class=HTMLResponse)
async def parent_board_check_in_submit(
    request: Request,
    session: Session = Depends(get_session),
):
    from routers.parent_portal import _get_parent_account, templates

    current_parent_user = _get_parent_account(request, session)
    if not current_parent_user:
        return RedirectResponse(url="/parent-portal/login", status_code=303)

    form = await request.form()
    token = str(form.get("t") or "").strip()
    action = str(form.get("action") or "").strip()
    actual_pickup_person = str(form.get("actual_pickup_person") or "").strip()
    raw_child_ids = form.getlist("child_ids")

    error_message = ""
    punch_info = None
    completed = False
    punched_count = 0

    try:
        verify_board_qr_token(
            token,
            expected_version=get_board_qr_version(session),
            enabled=is_board_qr_enabled(session),
        )
        punch_info = get_sibling_qr_punch_info(session, parent_account_id=current_parent_user.id)
        allowed_ids = {int(c["child_id"]) for c in punch_info["children"]}
        selected_ids = []
        for raw_id in raw_child_ids:
            try:
                cid = int(raw_id)
            except (TypeError, ValueError):
                continue
            if cid in allowed_ids and cid not in selected_ids:
                selected_ids.append(cid)

        if action not in {"check_in", "check_out"}:
            raise ValueError("打刻種別（登園・降園）を選択してください。")
        if not selected_ids:
            raise ValueError("打刻対象のお子さまを1名以上選択してください。")

        records = execute_sibling_qr_punch(
            session,
            child_ids=selected_ids,
            action=action,
            actual_pickup_person=actual_pickup_person,
            actor_name=f"掲示板QR({current_parent_user.display_name})",
        )
        session.commit()
        punched_count = len(records)
        completed = True
        punch_info = get_sibling_qr_punch_info(session, parent_account_id=current_parent_user.id)
    except ValueError as exc:
        error_message = str(exc)

    return templates.TemplateResponse(
        request,
        "parent_portal/board_check_in.html",
        {
            "current_parent_user": current_parent_user,
            "parent_portal_mode": True,
            "board_token": token,
            "error_message": error_message,
            "punch_info": punch_info,
            "completed": completed,
            "completed_action": action,
            "punched_count": punched_count,
        },
        status_code=400 if error_message else 200,
        headers={"Cache-Control": "private, no-store"},
    )
