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
    is_pinned: bool = Form(False),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    from sqlmodel import select
    from ..contracts import SolveJobStatus
    from ..db_models import ShiftSolveJobs

    plan = repo.get_plan(plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Plan not found")

    if plan.status == PlanStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Approved plan cannot be edited")

    # 求解中のセル編集競合を防止
    active_job = repo.session.exec(
        select(ShiftSolveJobs).where(
            ShiftSolveJobs.plan_id == plan_id,
            ShiftSolveJobs.status.in_([SolveJobStatus.QUEUED, SolveJobStatus.RUNNING]),
        )
    ).first()
    if active_job is not None:
        raise HTTPException(status_code=409, detail="求解ジョブ実行中はセルを編集できません")

    parsed_date = date.fromisoformat(target_date)
    existing_cell = repo.get_plan_cell(plan_id, staff_user_id, parsed_date)

    # cell_state='pinned' で送られてきた場合の互換性
    pinned_flag = is_pinned or (cell_state == "pinned")

    if existing_cell is not None:
        existing_cell.slot_label = slot_label
        existing_cell.cell_state = cell_state
        existing_cell.is_pinned = pinned_flag
        repo.save_plan_cell(existing_cell)
    else:
        new_cell = ShiftPlanCells(
            plan_id=plan_id,
            staff_user_id=staff_user_id,
            target_date=parsed_date,
            slot_label=slot_label,
            cell_state=cell_state,
            is_pinned=pinned_flag,
        )
        repo.create_plan_cell(new_cell)

    return RedirectResponse(url=f"/shifts/plans/{plan_id}", status_code=303)
