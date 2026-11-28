"""職員契約・資格ルーター。

GET/POST /shifts/contracts - 職員契約・資格の一括入力。
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])


@router.get("/contracts")
def contracts_list(
    request: Request,
) -> RedirectResponse:
    """職員契約・資格設定は /shifts/staff へ統合済み。"""
    return RedirectResponse(url="/shifts/staff", status_code=302)
