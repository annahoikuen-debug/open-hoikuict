from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import StaffUser, get_current_staff_user, require_admin
from csrf import verify_csrf
from database import get_session
from models import FacilitySettings
from template_utils import create_templates
from time_utils import utc_now

router = APIRouter(prefix="/settings/facility", tags=["facility-settings"])
templates = create_templates()

TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _get_or_create_settings(session: Session) -> FacilitySettings:
    settings = session.exec(select(FacilitySettings).where(FacilitySettings.id == 1)).first()
    if settings is None:
        settings = FacilitySettings(
            id=1,
            final_pickup_time="19:00",
            supplementary_meal_time="18:00",
            supplementary_meal_fee=100,
            updated_at=utc_now(),
        )
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def facility_settings_view(
    request: Request,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_admin(current_user)
    settings = _get_or_create_settings(session)
    csrf_token = getattr(request.state, "csrf_token", "")
    return templates.TemplateResponse(
        request,
        "facility_settings/index.html",
        {
            "request": request,
            "current_user": current_user,
            "settings": settings,
            "csrf_token": csrf_token,
            "saved": request.query_params.get("saved") == "1",
        },
    )


@router.post("", dependencies=[Depends(verify_csrf)])
@router.post("/", dependencies=[Depends(verify_csrf)])
def facility_settings_update(
    request: Request,
    final_pickup_time: str = Form(...),
    supplementary_meal_time: str = Form(...),
    supplementary_meal_fee: int = Form(...),
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_admin(current_user)

    final_pickup_time = final_pickup_time.strip()
    supplementary_meal_time = supplementary_meal_time.strip()

    if not TIME_RE.match(final_pickup_time):
        raise HTTPException(status_code=422, detail="お迎え最終時刻の形式が不正です (HH:MM)")
    if not TIME_RE.match(supplementary_meal_time):
        raise HTTPException(status_code=422, detail="補食判定時刻の形式が不正です (HH:MM)")
    if supplementary_meal_fee < 0 or supplementary_meal_fee > 10000:
        raise HTTPException(status_code=422, detail="補食費は0〜10,000円の範囲で入力してください")

    settings = _get_or_create_settings(session)
    settings.final_pickup_time = final_pickup_time
    settings.supplementary_meal_time = supplementary_meal_time
    settings.supplementary_meal_fee = supplementary_meal_fee
    settings.updated_at = utc_now()
    session.add(settings)
    session.commit()

    return RedirectResponse(url="/settings/facility?saved=1", status_code=303)
