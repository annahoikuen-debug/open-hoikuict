"""シフト結果エクスポートルーター。

GET/POST /shifts/plans/{id}/export/* - CSV / Excel / ICS 出力。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from template_utils import create_templates

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])


@router.get("/plans/{plan_id}/export", response_class=HTMLResponse)
def exports_menu(
    plan_id: int,
    request: Request,
) -> HTMLResponse:
    templates = create_templates()
    return templates.TemplateResponse(
        request,
        "shift_schedule/export_menu.html",
        {
            "request": request,
            "plan_id": plan_id,
        },
    )
