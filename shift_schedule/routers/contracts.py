"""職員契約・資格ルーター。

GET/POST /shifts/contracts - 職員契約・資格の一括入力。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from template_utils import create_templates

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])


@router.get("/contracts", response_class=HTMLResponse)
def contracts_list(
    request: Request,
) -> HTMLResponse:
    templates = create_templates()
    return templates.TemplateResponse(
        request,
        "shift_schedule/contracts.html",
        {
            "request": request,
        },
    )
