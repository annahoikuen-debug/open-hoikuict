from __future__ import annotations

from datetime import date, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session

from auth import get_current_staff_user, require_can_edit
from database import get_session
from facility_settings_service import (
    is_nap_check_smart_enabled,
    nap_check_interval_minutes,
)
from nap_check_service import (
    POSTURE_DEFINITIONS,
    bulk_set_slot_for_children,
    get_current_nearest_slot,
    get_next_posture,
    load_nap_check_sheet_data,
    update_child_nap_memo,
    update_child_nap_slot,
    update_classroom_environment,
)
from template_utils import create_templates
from time_utils import local_naive_now, local_today


def _parse_target_date(target_date: str) -> date:
    """ISO形式の対象日付をパースし、不正値なら HTTP 400 を返す。"""
    try:
        return date.fromisoformat(target_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="対象日付の形式が不正です") from exc


def _parse_optional_float(raw_value: Optional[str], label: str) -> Optional[float]:
    """任意の実数フォーム値を検証付きでパースする。"""
    if not raw_value or not raw_value.strip():
        return None
    try:
        return float(raw_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"{label}は数値で入力してください") from exc

router = APIRouter(prefix="/nap-checks", tags=["nap-checks"])
templates = create_templates()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse)
def nap_checks_list(
    request: Request,
    target_date: Optional[str] = Query(default=None, alias="date"),
    classroom_id: Optional[int] = Query(default=None),
    hour: Optional[str] = Query(default=None),
    only_present: Optional[str] = Query(default="1"),
    q: Optional[str] = Query(default=None),
    smart: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """コドモン互換5分刻みタイムライン午睡チェック一覧画面。"""
    # 施設設定に基づくスマートタイムライン有効判定
    smart_setting = is_nap_check_smart_enabled(session)
    if smart is not None:
        smart_enabled = smart.lower() in ("1", "true", "yes")
    else:
        smart_enabled = smart_setting

    interval = nap_check_interval_minutes(session)

    # 日付パース
    if target_date:
        try:
            parsed_date = date.fromisoformat(target_date)
        except ValueError:
            parsed_date = local_today()
    else:
        parsed_date = local_today()

    # 時間帯選択（未指定時は現在時刻から最適な1時間枠を選択）
    now_dt = local_naive_now()
    if not hour:
        if 11 <= now_dt.hour <= 15:
            selected_hour = f"{now_dt.hour:02d}:00"
        else:
            selected_hour = "13:00"
    else:
        selected_hour = hour

    is_only_present = only_present in ("1", "true", "yes", "on")
    search_q = (q or "").strip()

    # データ構築
    data = load_nap_check_sheet_data(
        session=session,
        target_date=parsed_date,
        classroom_id=classroom_id,
        only_present=is_only_present,
        search_query=search_q,
        selected_hour=selected_hour,
        interval=interval,
    )

    prev_date = (parsed_date - timedelta(days=1)).isoformat()
    next_date = (parsed_date + timedelta(days=1)).isoformat()
    today_str = local_today().isoformat()
    current_nearest_slot = get_current_nearest_slot(now_dt, interval)

    context = {
        "request": request,
        "current_user": current_user,
        "sheet": data,
        "smart_enabled": smart_enabled,
        "smart_setting": smart_setting,
        "prev_date": prev_date,
        "next_date": next_date,
        "today_str": today_str,
        "current_nearest_slot": current_nearest_slot,
        "is_today": parsed_date == local_today(),
    }
    return templates.TemplateResponse(request, "nap_checks/index.html", context)


@router.post("/cycle-slot")
def cycle_child_slot(
    request: Request,
    child_id: int = Form(...),
    target_date: str = Form(...),
    time_key: str = Form(...),
    current_posture: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """スロットを1タップして次の体位へトグル（差分入力）。"""
    require_can_edit(current_user)
    parsed_date = _parse_target_date(target_date)
    next_posture = get_next_posture(current_posture)

    update_child_nap_slot(
        session=session,
        child_id=child_id,
        target_date=parsed_date,
        time_key=time_key,
        posture=next_posture,
        breathing="normal",
        staff_name=current_user.name,
    )

    posture_info = POSTURE_DEFINITIONS.get(next_posture, {})
    slot_info = {
        "time": time_key,
        "posture": next_posture,
        "label": posture_info.get("label", ""),
        "symbol": posture_info.get("symbol", ""),
        "badge_class": posture_info.get("badge_class", "bg-slate-50 text-slate-400 border-slate-200 hover:bg-slate-100"),
    }

    # HTMX リクエストの場合はセル単体のフラグメントを返却
    if request.headers.get("HX-Request"):
        context = {
            "request": request,
            "child_id": child_id,
            "target_date": target_date,
            "slot": slot_info,
        }
        return templates.TemplateResponse(request, "nap_checks/_slot_cell.html", context)

    return JSONResponse({"status": "ok", "posture": next_posture, "symbol": slot_info["symbol"]})


@router.post("/bulk-present")
def bulk_present_slot(
    request: Request,
    time_key: str = Form(...),
    target_date: str = Form(...),
    classroom_id: Optional[int] = Form(None),
    only_present: Optional[str] = Form("1"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """指定時刻スロットに対して登園中園児を一括で仰向け・呼吸良好にセット（差分ベース）。"""
    require_can_edit(current_user)
    parsed_date = _parse_target_date(target_date)

    data = load_nap_check_sheet_data(
        session=session,
        target_date=parsed_date,
        classroom_id=classroom_id,
        only_present=only_present in ("1", "true", "yes", "on"),
    )

    target_child_ids = [row["child"].id for row in data["rows"] if row["is_present"]]
    if not target_child_ids:
        # 登園中のみで0名の場合は表示されている園児を対象とする
        target_child_ids = [row["child"].id for row in data["rows"]]

    bulk_set_slot_for_children(
        session=session,
        child_ids=target_child_ids,
        target_date=parsed_date,
        time_key=time_key,
        posture="back",
        breathing="normal",
        staff_name=current_user.name,
    )

    params = {"date": target_date}
    if classroom_id:
        params["classroom_id"] = classroom_id
    hour_prefix = time_key.split(":")[0] + ":00"
    params["hour"] = hour_prefix

    return RedirectResponse(
        url=f"/nap-checks/?{urlencode(params)}&notice=bulk_success",
        status_code=303,
    )


@router.post("/memo")
def save_nap_memo(
    request: Request,
    child_id: int = Form(...),
    target_date: str = Form(...),
    memo: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """園児の「この日の体調・午睡のメモ」を保存する。"""
    require_can_edit(current_user)
    parsed_date = _parse_target_date(target_date)
    rec = update_child_nap_memo(
        session=session,
        child_id=child_id,
        target_date=parsed_date,
        memo=memo,
        staff_name=current_user.name,
    )
    if request.headers.get("HX-Request"):
        return HTMLResponse('<span class="text-xs text-emerald-600 font-medium">✓ 保存済</span>')
    return JSONResponse({"status": "ok", "memo": rec.daily_memo})


@router.post("/environment")
def save_classroom_environment(
    request: Request,
    classroom_id: int = Form(...),
    target_date: str = Form(...),
    weather: Optional[str] = Form(None),
    room_temperature: Optional[str] = Form(None),
    humidity: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """クラスの環境記録（室温・湿度・天気）を保存する。"""
    require_can_edit(current_user)
    parsed_date = _parse_target_date(target_date)
    temp_val = _parse_optional_float(room_temperature, "室温")
    hum_val = _parse_optional_float(humidity, "湿度")

    update_classroom_environment(
        session=session,
        classroom_id=classroom_id,
        target_date=parsed_date,
        weather=weather,
        room_temperature=temp_val,
        humidity=hum_val,
        notes=notes,
        staff_name=current_user.name,
    )
    return RedirectResponse(
        url=f"/nap-checks/?date={parsed_date.isoformat()}&classroom_id={classroom_id}&notice=env_saved",
        status_code=303,
    )


@router.get("/health-redirect")
def health_nap_checks_redirect(
    date: Optional[str] = Query(default=None),
    classroom_id: Optional[int] = Query(default=None),
):
    """/health からのショートカット・リダイレクト。"""
    params = {}
    if date:
        params["date"] = date
    if classroom_id:
        params["classroom_id"] = classroom_id
    query_str = f"?{urlencode(params)}" if params else ""
    return RedirectResponse(url=f"/nap-checks/{query_str}", status_code=302)
