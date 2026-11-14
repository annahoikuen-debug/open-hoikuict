"""施設シフト設定ルーター。

GET/POST /shifts/facility - 開園/閉園・粒度・定員・配置基準等の設定。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from ..services.facility import add_closed_day, get_or_create_settings, list_closed_days, update_settings
from ..store import ShiftRepository, ShiftRepositoryDep

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])


@router.get("/facility", response_class=HTMLResponse)
def facility_settings(
    request: Request,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> HTMLResponse:
    settings = get_or_create_settings(repo)
    closed_days = list_closed_days(repo, settings.id)
    from template_utils import create_templates

    templates = create_templates()
    return templates.TemplateResponse(
        request,
        "shift_schedule/facility.html",
        {
            "request": request,
            "settings": settings,
            "closed_days": closed_days,
        },
    )


@router.post("/facility")
def facility_settings_save(
    day_open: str = Form("07:30"),
    day_close: str = Form("19:30"),
    granularity_min: int = Form(30),
    capacity: int = Form(60),
    staffing_standard_key: str = Form("fukuoka_city"),
    min_two_staff_rule: bool = Form(False),
    enforce_min_two: bool = Form(False),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    update_settings(
        repo,
        day_open=day_open,
        day_close=day_close,
        granularity_min=granularity_min,
        capacity=capacity,
        staffing_standard_key=staffing_standard_key,
        min_two_staff_rule=min_two_staff_rule,
        enforce_min_two=enforce_min_two,
    )
    return RedirectResponse(url="/shifts/facility", status_code=303)


@router.post("/facility/closed-days")
def facility_closed_day_add(
    target_date: str = Form(...),
    kind: str = Form("closed"),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    settings = get_or_create_settings(repo)
    add_closed_day(repo, settings.id, date.fromisoformat(target_date), kind)
    return RedirectResponse(url="/shifts/facility", status_code=303)


# ---------------------------------------------------------------------------
# 制約重み設定 API (Timefold: Runtime Constraint Weights)
# ---------------------------------------------------------------------------


@router.get("/facilities/{facility_id}/constraint-weights")
def get_constraint_weights_api(
    facility_id: int,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
):
    """施設の制約重み一覧を取得する。"""
    from ..services.weights import get_facility_constraint_weights

    return get_facility_constraint_weights(repo.session, facility_id=facility_id)


@router.put("/facilities/{facility_id}/constraint-weights")
async def update_constraint_weights_api(
    facility_id: int,
    request: Request,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
):
    """施設の制約重みを一括更新する。"""
    from ..services.weights import update_facility_constraint_weights

    body = await request.json()
    updates = body if isinstance(body, list) else body.get("weights", [])

    user_id = getattr(request.state, "user_id", "admin")

    updated = update_facility_constraint_weights(
        session=repo.session,
        facility_id=facility_id,
        updates=updates,
        user_id=user_id,
    )
    return {"status": "ok", "weights": updated}

