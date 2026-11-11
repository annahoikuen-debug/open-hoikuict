from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import StaffUser, get_current_staff_user, require_admin
from csrf import verify_csrf
from database import get_session
from facility_settings_service import (
    DEFAULTS,
    parse_hhmm,
    record_change_history,
)
from models import FacilitySettings, FacilitySettingsHistory
from template_utils import create_templates
from time_utils import utc_now

router = APIRouter(prefix="/settings/facility", tags=["facility-settings"])
templates = create_templates()

FIELD_LABELS = {
    "final_pickup_time": "お迎え最終時刻",
    "supplementary_meal_time": "補食判定時刻",
    "supplementary_meal_fee": "補食費",
    "parent_billing_portal_enabled": "保護者ポータル 請求・延長保育料の表示",
}


def _get_or_create_settings(session: Session) -> FacilitySettings:
    settings = session.exec(select(FacilitySettings).where(FacilitySettings.id == 1)).first()
    if settings is None:
        settings = FacilitySettings(id=1, **DEFAULTS, updated_at=utc_now())
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
    history = session.exec(
        select(FacilitySettingsHistory).order_by(FacilitySettingsHistory.id.desc()).limit(20)
    ).all()
    csrf_token = getattr(request.state, "csrf_token", "")
    return templates.TemplateResponse(
        request,
        "facility_settings/index.html",
        {
            "request": request,
            "current_user": current_user,
            "settings": settings,
            "history": history,
            "field_labels": FIELD_LABELS,
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
    fever_return_days: int = Form(2),
    fever_caution_c: str = Form("37.5"),
    fever_review_c: str = Form("38.0"),
    parent_billing_portal_enabled: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_admin(current_user)

    final_pickup_time = parse_hhmm(final_pickup_time.strip(), "お迎え最終時刻")
    supplementary_meal_time = parse_hhmm(supplementary_meal_time.strip(), "補食判定時刻")
    if supplementary_meal_fee < 0 or supplementary_meal_fee > 10000:
        raise HTTPException(status_code=422, detail="補食費は0〜10,000円の範囲で入力してください")
    # 登園判定基準（改善案8）
    try:
        caution_c = float(fever_caution_c.strip())
        review_c = float(fever_review_c.strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="体温しきい値は数値で入力してください") from exc
    if not (35.0 <= caution_c <= 40.0 and 35.0 <= review_c <= 40.0 and caution_c <= review_c):
        raise HTTPException(status_code=422, detail="体温しきい値は35.0〜40.0の範囲で、要注意≦要検討の関係を満たしてください")
    if not (0 <= fever_return_days <= 14):
        raise HTTPException(status_code=422, detail="解熱後の登園目安日数は0〜14日の範囲で入力してください")

    is_billing_enabled = parent_billing_portal_enabled in ("1", "true", "True", "on")

    settings = _get_or_create_settings(session)
    previous = dict(
        final_pickup_time=settings.final_pickup_time,
        supplementary_meal_time=settings.supplementary_meal_time,
        supplementary_meal_fee=str(settings.supplementary_meal_fee),
        parent_billing_portal_enabled=str(settings.parent_billing_portal_enabled),
    )
    settings.final_pickup_time = final_pickup_time
    settings.supplementary_meal_time = supplementary_meal_time
    settings.supplementary_meal_fee = supplementary_meal_fee
    settings.fever_return_days = fever_return_days
    settings.fever_caution_c = f"{caution_c:.1f}"
    settings.fever_review_c = f"{review_c:.1f}"
    settings.parent_billing_portal_enabled = is_billing_enabled
    settings.updated_at = utc_now()
    settings.updated_by_user_id = current_user.user_id
    settings.updated_by_name = current_user.name
    record_change_history(
        session, settings, previous,
        actor_name=current_user.name, actor_user_id=current_user.user_id,
    )
    session.add(settings)
    session.commit()

    return RedirectResponse(url="/settings/facility?saved=1", status_code=303)
