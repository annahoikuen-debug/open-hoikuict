"""シフトプランセル編集ルーター。

POST /shifts/plans/{id}/cells - セルのピン留め・手動修正。
"""

from __future__ import annotations

from fastapi import APIRouter, Form
from fastapi.responses import RedirectResponse

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])


@router.post("/plans/{plan_id}/cells")
def plans_edit_cell(
    plan_id: int,
    staff_user_id: int = Form(...),
    target_date: str = Form(...),
    slot_label: str = Form(...),
    cell_state: str = Form("specified"),
) -> RedirectResponse:
    # TODO: 実装（セルのアップサート）
    return RedirectResponse(url=f"/shifts/plans/{plan_id}", status_code=303)
