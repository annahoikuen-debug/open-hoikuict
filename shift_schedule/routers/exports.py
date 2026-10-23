"""シフト結果エクスポートルーター。

GET/POST /shifts/plans/{id}/export/* - CSV / Excel / ICS 出力。
"""

from __future__ import annotations

import io
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from database import get_session
from shift_schedule.contracts import PlanStatus
from shift_schedule.store import SqlModelShiftRepository
from template_utils import create_templates

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])

DISCLAIMER_TEXT = "【免責事項】本シフト表は数理最適化による提案です。最終的な人員配置および法令適合の確認・承認責任は施設管理者が負います。"


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


@router.get("/plans/{plan_id}/export.csv")
def export_shift_csv(
    plan_id: int,
    session: Session = Depends(get_session),
) -> Response:
    repo = SqlModelShiftRepository(session)
    plan = repo.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="シフト計画が見つかりません")
    cells = repo.list_plan_cells(plan_id)

    output = io.StringIO()
    output.write(f"# {DISCLAIMER_TEXT}\n")
    output.write("職員ID,日付,スロット,状態\n")
    for cell in sorted(cells, key=lambda c: (c.target_date, c.staff_user_id)):
        output.write(f"{cell.staff_user_id},{cell.target_date},{cell.slot_label},{cell.cell_state}\n")

    content = "\ufeff" + output.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=shift_plan_{plan_id}.csv"
        },
    )


@router.get("/plans/{plan_id}/export.ics")
def export_shift_ics(
    plan_id: int,
    session: Session = Depends(get_session),
) -> Response:
    repo = SqlModelShiftRepository(session)
    plan = repo.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="シフト計画が見つかりません")
    cells = repo.list_plan_cells(plan_id)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//open-hoikuict//Shift Schedule//JA",
        f"X-WR-CALNAME:シフト勤務割表 (Plan #{plan_id})",
        f"X-WR-CALDESC:{DISCLAIMER_TEXT}",
    ]
    for cell in cells:
        dt_str = cell.target_date.strftime("%Y%m%d")
        lines.extend([
            "BEGIN:VEVENT",
            f"UID:shift-{plan_id}-{cell.staff_user_id}-{dt_str}@open-hoikuict",
            f"DTSTAMP:{dt_str}T000000Z",
            f"DTSTART;VALUE=DATE:{dt_str}",
            f"DTEND;VALUE=DATE:{dt_str}",
            f"SUMMARY:シフト: {cell.slot_label} (職員ID {cell.staff_user_id})",
            f"DESCRIPTION:状態: {cell.cell_state}\\n{DISCLAIMER_TEXT}",
            "END:VEVENT",
        ])
    lines.append("END:VCALENDAR")
    lines.append("")

    return Response(
        content="\r\n".join(lines).encode("utf-8"),
        media_type="text/calendar",
        headers={
            "Content-Disposition": f"attachment; filename=shift_plan_{plan_id}.ics"
        },
    )
