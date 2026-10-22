"""シフトプランセル編集ルーター。

POST /shifts/plans/{id}/cells - セルのピン留め・手動修正。
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse

from ..contracts import PlanStatus
from ..db_models import ShiftPlanCells
from ..store import ShiftRepository, ShiftRepositoryDep

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])


@router.post("/plans/{plan_id}/cells")
def plans_edit_cell(
    plan_id: int,
    staff_user_id: str = Form(...),
    target_date: str = Form(...),
    slot_label: str = Form(...),
    cell_state: str = Form("specified"),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    plan = repo.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.status == PlanStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Approved plan cannot be edited")

    parsed_date = date.fromisoformat(target_date)
    existing_cell = repo.get_plan_cell(plan_id, staff_user_id, parsed_date)

    if existing_cell is not None:
        existing_cell.slot_label = slot_label
        existing_cell.cell_state = cell_state
        repo.save_plan_cell(existing_cell)
    else:
        new_cell = ShiftPlanCells(
            plan_id=plan_id,
            staff_user_id=staff_user_id,
            target_date=parsed_date,
            slot_label=slot_label,
            cell_state=cell_state,
        )
        repo.create_plan_cell(new_cell)

    return RedirectResponse(url=f"/shifts/plans/{plan_id}", status_code=303)
