from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

import parent_contact_fields as contact_fields
from parent_contact_preview import render_preview
from models import ParentContactFieldAudit

from auth import get_current_staff_user
from database import get_session
from facility_settings_service import (
    DEFAULTS as FACILITY_DEFAULTS,
    get_board_qr_version,
    is_board_qr_enabled,
    record_change_history,
)
from guardian_qr_service import generate_board_qr_token, generate_qr_svg
from models import FacilitySettings, GuardianHoursAudit, GuardianHoursSetting, StaffSessionPolicyAudit
from guardian_hours import closing_time, parse_closing_time
from time_utils import utc_now
from health_check_service import run_facility_health_check
from staff_permissions import require_live_admin
from staff_session_settings import get_staff_session_policy, parse_session_policy, save_staff_session_policy
from template_utils import create_templates

router = APIRouter(prefix="/settings", tags=["settings"])
templates = create_templates()


def _contact_fields_page(request, session, current_user, *, policy=None, revision=None,
                         error="", status_code=200, saved=False, form=None):
    persisted, current_revision = contact_fields.get_policy(session)
    policy = policy if policy is not None else persisted
    rooms = contact_fields.classrooms(session)
    policy = contact_fields.policy_for_rooms(policy, rooms)
    form = form or {}
    preview_age = form.get("preview_age", "0")
    preview_class = form.get("preview_class", str(rooms[0].id) if rooms else "")
    preview_state = form.get("preview_state", "empty")
    group = preview_age if policy["mode"] == "age" else preview_class
    return templates.TemplateResponse(request, "settings/parent_contact_fields.html", {
        "current_user": current_user, "policy": policy, "groups": contact_fields.GROUPS,
        "tables": contact_fields.policy_groups(policy, rooms),
        "room_ids": contact_fields.room_revision(rooms),
        "revision": current_revision if revision is None else revision,
        "error": error, "saved": saved, "conflict": status_code == 409,
        "preview_age": preview_age, "preview_class": preview_class, "preview_state": preview_state,
        "preview_html": render_preview(templates, policy, group, preview_state),
        "latest": session.exec(select(ParentContactFieldAudit).order_by(ParentContactFieldAudit.id.desc())).first(),
    }, status_code=status_code, headers={"Cache-Control": "private, no-store"})


@router.get("/parent-contact-fields", response_class=HTMLResponse)
def parent_contact_fields(request: Request, saved: bool = False, session: Session = Depends(get_session),
                          current_user=Depends(get_current_staff_user)):
    require_live_admin(session, current_user)
    return _contact_fields_page(request, session, current_user, saved=saved)


@router.post("/parent-contact-fields", response_class=HTMLResponse)
async def save_parent_contact_fields(request: Request, session: Session = Depends(get_session),
                                     current_user=Depends(get_current_staff_user)):
    actor = require_live_admin(session, current_user)
    form = await request.form()
    previous, _ = contact_fields.get_policy(session)
    policy, revision = previous, form.get("revision", "")
    try:
        policy = contact_fields.parse_policy(form, previous, contact_fields.classrooms(session))
        revision = int(revision)
        if form.get("action") == "preview":
            return _contact_fields_page(request, session, current_user, policy=policy, revision=revision, form=form)
        if form.get("action") != "save":
            raise ValueError("保存またはプレビューを選んでください。")
        contact_fields.save_policy(session, policy, revision, actor)
    except (ValueError, HTTPException) as exc:
        session.rollback()
        return _contact_fields_page(request, session, current_user, policy=policy, revision=revision, form=form,
            error=str(exc.detail) if isinstance(exc, HTTPException) else str(exc),
            status_code=exc.status_code if isinstance(exc, HTTPException) else 400)
    return RedirectResponse("/settings/parent-contact-fields?saved=true", status_code=303,
                            headers={"Cache-Control": "private, no-store"})


@router.get("/guardian-hours", response_class=HTMLResponse)
def guardian_hours(request: Request, saved: bool = False, session: Session = Depends(get_session),
                   current_user=Depends(get_current_staff_user)):
    require_live_admin(session, current_user)
    return _hours_page(request, session, current_user, saved=saved)


def _hours_page(request, session, current_user, *, value=None, error="", saved=False):
    return templates.TemplateResponse(request, "settings/guardian_hours.html", {
        "current_user": current_user, "closing_time": value if value is not None else closing_time(session),
        "error": error, "saved": saved,
        "history": session.exec(select(GuardianHoursAudit).order_by(GuardianHoursAudit.id.desc()).limit(10)).all(),
    }, status_code=400 if error else 200, headers={"Cache-Control": "private, no-store"})


@router.post("/guardian-hours", response_class=HTMLResponse)
def save_guardian_hours(request: Request, closing: str = Form("", alias="closing_time"),
                        session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    actor = require_live_admin(session, current_user)
    try:
        value = parse_closing_time(closing)
    except ValueError as exc:
        return _hours_page(request, session, current_user, value=closing, error=str(exc))
    previous = closing_time(session)
    setting = session.get(GuardianHoursSetting, 1) or GuardianHoursSetting()
    setting.closing_time, setting.updated_by_name, setting.updated_at = value, actor.display_name, utc_now()
    session.add(setting)
    session.add(GuardianHoursAudit(previous_closing_time=previous, closing_time=value,
                                  changed_by_name=actor.display_name, changed_by_user_id=actor.id))
    session.commit()
    return RedirectResponse("/settings/guardian-hours?saved=true", status_code=303)


def _board_checkin_url(request: Request, version: int) -> str:
    token = generate_board_qr_token(version)
    base_url = str(request.base_url).rstrip("/")
    return f"{base_url}/parent-portal/board-check-in?t={token}"


@router.get("/board-qr", response_class=HTMLResponse)
def board_qr_page(
    request: Request,
    saved: bool = False,
    reissued: bool = False,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_live_admin(session, current_user)
    enabled = is_board_qr_enabled(session)
    version = get_board_qr_version(session)
    checkin_url = _board_checkin_url(request, version)
    return templates.TemplateResponse(
        request,
        "settings/board_qr.html",
        {
            "current_user": current_user,
            "board_qr_enabled": enabled,
            "board_qr_version": version,
            "checkin_url": checkin_url,
            "saved": saved,
            "reissued": reissued,
        },
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/board-qr.svg")
def board_qr_svg(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_live_admin(session, current_user)
    version = get_board_qr_version(session)
    checkin_url = _board_checkin_url(request, version)
    svg_str = generate_qr_svg(checkin_url, border=4)
    response = Response(content=svg_str, media_type="image/svg+xml")
    response.headers["Content-Disposition"] = f'inline; filename="board-checkin-qr-v{version}.svg"'
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@router.post("/board-qr")
def update_board_qr_settings(
    request: Request,
    action: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    actor = require_live_admin(session, current_user)
    settings = session.exec(select(FacilitySettings).where(FacilitySettings.id == 1)).first()
    if settings is None:
        settings = FacilitySettings(id=1, **FACILITY_DEFAULTS)
        session.add(settings)
        session.flush()

    previous = {
        "board_qr_enabled": str(settings.board_qr_enabled),
        "board_qr_version": str(settings.board_qr_version),
    }

    if action == "toggle":
        settings.board_qr_enabled = not bool(settings.board_qr_enabled)
        redirect_target = "/settings/board-qr?saved=true"
    elif action == "reissue":
        settings.board_qr_version = int(settings.board_qr_version or 1) + 1
        redirect_target = "/settings/board-qr?reissued=true"
    else:
        return RedirectResponse("/settings/board-qr", status_code=303)

    settings.updated_at = utc_now()
    settings.updated_by_user_id = actor.id
    settings.updated_by_name = actor.display_name
    record_change_history(
        session,
        settings,
        previous,
        actor_name=actor.display_name,
        actor_user_id=actor.id,
    )
    session.commit()
    return RedirectResponse(redirect_target, status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def settings_index(request: Request, current_user=Depends(get_current_staff_user)):
    from restore_control import enabled
    import os
    origin = os.getenv("HOIKUICT_CLASS_KIOSK_ORIGIN", "").rstrip("/")
    kiosk_url = origin + "/settings/class-kiosk/" if os.getenv("HOIKUICT_CLASS_KIOSK_ENABLED") == "1" and origin else None
    return templates.TemplateResponse(
        request, "settings/index.html", {"current_user": current_user, "restore_enabled": enabled(), "class_kiosk_admin_url": kiosk_url},
        headers={"Cache-Control": "private, no-store"},
    )


def _session_page(request, session, current_user, *, values=None, error="", status_code=200, saved=False):
    policy = get_staff_session_policy(session)
    persisted = {
        "idle_value": str(policy.idle_minutes // 60 if policy.idle_minutes % 60 == 0 else policy.idle_minutes),
        "idle_unit": "hours" if policy.idle_minutes % 60 == 0 else "minutes",
        "absolute_hours": str(policy.absolute_hours),
    }
    latest = session.exec(select(StaffSessionPolicyAudit).order_by(
        StaffSessionPolicyAudit.changed_at.desc(), StaffSessionPolicyAudit.id.desc(),
    )).first()
    return templates.TemplateResponse(request, "settings/staff_sessions.html", {
        "current_user": current_user, "values": values if values is not None else persisted,
        "persisted": persisted, "error": error, "saved": saved, "latest": latest,
    }, status_code=status_code, headers={"Cache-Control": "private, no-store"})


@router.get("/staff-sessions", response_class=HTMLResponse)
def staff_sessions(request: Request, saved: bool = False, session: Session = Depends(get_session),
                   current_user=Depends(get_current_staff_user)):
    require_live_admin(session, current_user)
    return _session_page(request, session, current_user, saved=saved)


@router.post("/staff-sessions", response_class=HTMLResponse)
def save_staff_sessions(request: Request, idle_value: str = Form(""), idle_unit: str = Form(""),
                        absolute_hours: str = Form(""), session: Session = Depends(get_session),
                        current_user=Depends(get_current_staff_user)):
    actor = require_live_admin(session, current_user)
    try:
        policy = parse_session_policy(idle_value, idle_unit, absolute_hours)
    except ValueError as exc:
        return _session_page(request, session, current_user, values={
            "idle_value": idle_value, "idle_unit": idle_unit, "absolute_hours": absolute_hours,
        }, error=str(exc), status_code=400)
    save_staff_session_policy(session, policy, actor)
    return RedirectResponse("/settings/staff-sessions?saved=true", status_code=303,
                            headers={"Cache-Control": "private, no-store"})


@router.get("/health-check", response_class=HTMLResponse)
def facility_health_check_page(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """施設・園の初期設定ヘルスチェック診断画面 (P1-1)。"""
    result = run_facility_health_check(session)
    return templates.TemplateResponse(
        request,
        "settings/health_check.html",
        {
            "request": request,
            "current_user": current_user,
            "health": result,
        },
        headers={"Cache-Control": "private, no-store"},
    )


from models import UserOnboardingState


@router.get("/health-check/api")
def facility_health_check_api(
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """施設・園の初期設定ヘルスチェック結果をJSONで返す (P1-1)。"""
    return run_facility_health_check(session)


@router.post("/tour/complete")
def complete_onboarding_tour(
    tour_key: str = Form(default="staff_console_tour"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """職員オンボーディングツアーの完了状態をDBに永続化する (P1-2)。"""
    user_id = getattr(current_user, "user_id", None)
    staff_name = getattr(current_user, "name", "職員")

    state = None
    if user_id:
        state = session.exec(
            select(UserOnboardingState).where(
                UserOnboardingState.user_id == user_id,
                UserOnboardingState.tour_key == tour_key,
            )
        ).first()
    elif staff_name:
        state = session.exec(
            select(UserOnboardingState).where(
                UserOnboardingState.staff_name == staff_name,
                UserOnboardingState.tour_key == tour_key,
            )
        ).first()

    now = utc_now()
    if state:
        state.is_completed = True
        state.completed_at = now
        session.add(state)
    else:
        new_state = UserOnboardingState(
            user_id=user_id,
            staff_name=staff_name,
            tour_key=tour_key,
            is_completed=True,
            completed_at=now,
        )
        session.add(new_state)

    session.commit()
    return {"status": "ok", "tour_key": tour_key, "is_completed": True}


@router.get("/tour/status")
def get_onboarding_tour_status(
    tour_key: str = Query(default="staff_console_tour"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """職員オンボーディングツアーの完了状態を取得する (P1-2)。"""
    user_id = getattr(current_user, "user_id", None)
    staff_name = getattr(current_user, "name", "職員")

    state = None
    if user_id:
        state = session.exec(
            select(UserOnboardingState).where(
                UserOnboardingState.user_id == user_id,
                UserOnboardingState.tour_key == tour_key,
            )
        ).first()
    elif staff_name:
        state = session.exec(
            select(UserOnboardingState).where(
                UserOnboardingState.staff_name == staff_name,
                UserOnboardingState.tour_key == tour_key,
            )
        ).first()

    return {
        "tour_key": tour_key,
        "is_completed": bool(state and state.is_completed),
        "completed_at": state.completed_at.isoformat() if state and state.completed_at else None,
    }


@router.post("/tour/reset")
def reset_onboarding_tour(
    tour_key: str = Form(default="staff_console_tour"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """オンボーディングツアーを再表示するために完了状態をリセットする (P1-2)。"""
    user_id = getattr(current_user, "user_id", None)
    staff_name = getattr(current_user, "name", "職員")

    state = None
    if user_id:
        state = session.exec(
            select(UserOnboardingState).where(
                UserOnboardingState.user_id == user_id,
                UserOnboardingState.tour_key == tour_key,
            )
        ).first()
    elif staff_name:
        state = session.exec(
            select(UserOnboardingState).where(
                UserOnboardingState.staff_name == staff_name,
                UserOnboardingState.tour_key == tour_key,
            )
        ).first()

    if state:
        state.is_completed = False
        session.add(state)
        session.commit()

    return {"status": "ok", "tour_key": tour_key, "is_completed": False}
