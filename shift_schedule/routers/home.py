"""Shift schedule home/dashboard router.

GET /shifts/ - シフト管理トップ画面。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from template_utils import create_templates

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])
templates = create_templates()


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "shift_schedule/home.html",
        {
            "request": request,
        },
    )
