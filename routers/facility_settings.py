from __future__ import annotations

import json
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import StaffUser, get_current_staff_user, require_admin
from csrf import verify_csrf
from database import get_session
from facility_settings_service import (
    AVAILABLE_SIMPLE_TILES,
    DEFAULT_SIMPLE_TILES,
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
    "attendance_smart_hud_enabled": "スマート・モーニング点呼HUD",
    "staff_simple_mode_enabled": "職員かんたんモード・コマンドバー",
    "simple_mode_custom_tiles": "かんたんモード表示タイル",
    "nap_check_smart_enabled": "スマート午睡チェック（コドモン互換タイムライン）",
    "nap_check_interval_minutes": "午睡チェック間隔（分）",
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

    selected_tile_keys = set(DEFAULT_SIMPLE_TILES)
    if settings.simple_mode_custom_tiles:
        try:
            parsed = json.loads(settings.simple_mode_custom_tiles)
            if isinstance(parsed, list):
                selected_tile_keys = set(parsed)
        except Exception:
            pass

    return templates.TemplateResponse(
        request,
        "facility_settings/index.html",
        {
            "request": request,
            "current_user": current_user,
            "settings": settings,
            "history": history,
            "field_labels": FIELD_LABELS,
            "available_tiles": AVAILABLE_SIMPLE_TILES,
            "selected_tile_keys": selected_tile_keys,
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
    attendance_smart_hud_enabled: Optional[str] = Form(None),
    staff_simple_mode_enabled: Optional[str] = Form(None),
    simple_mode_tiles: list[str] = Form(default=[]),
    nap_check_smart_enabled: Optional[str] = Form(None),
    nap_check_interval_minutes: int = Form(5),
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
    is_hud_enabled = attendance_smart_hud_enabled in ("1", "true", "True", "on")
    is_simple_enabled = staff_simple_mode_enabled in ("1", "true", "True", "on")
    is_nap_enabled = nap_check_smart_enabled in ("1", "true", "True", "on")
    custom_tiles_json = json.dumps(simple_mode_tiles if simple_mode_tiles else DEFAULT_SIMPLE_TILES)

    settings = _get_or_create_settings(session)
    previous = dict(
        final_pickup_time=settings.final_pickup_time,
        supplementary_meal_time=settings.supplementary_meal_time,
        supplementary_meal_fee=str(settings.supplementary_meal_fee),
        parent_billing_portal_enabled=str(settings.parent_billing_portal_enabled),
        attendance_smart_hud_enabled=str(settings.attendance_smart_hud_enabled),
        staff_simple_mode_enabled=str(settings.staff_simple_mode_enabled),
        simple_mode_custom_tiles=str(settings.simple_mode_custom_tiles or ""),
        nap_check_smart_enabled=str(settings.nap_check_smart_enabled),
        nap_check_interval_minutes=str(settings.nap_check_interval_minutes),
    )
    settings.final_pickup_time = final_pickup_time
    settings.supplementary_meal_time = supplementary_meal_time
    settings.supplementary_meal_fee = supplementary_meal_fee
    settings.fever_return_days = fever_return_days
    settings.fever_caution_c = f"{caution_c:.1f}"
    settings.fever_review_c = f"{review_c:.1f}"
    settings.parent_billing_portal_enabled = is_billing_enabled
    settings.attendance_smart_hud_enabled = is_hud_enabled
    settings.staff_simple_mode_enabled = is_simple_enabled
    settings.simple_mode_custom_tiles = custom_tiles_json
    settings.nap_check_smart_enabled = is_nap_enabled
    settings.nap_check_interval_minutes = 10 if nap_check_interval_minutes == 10 else 5
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
