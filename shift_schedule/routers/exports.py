"""シフト結果エクスポートルーター。

GET/POST /shifts/plans/{id}/export/* - CSV / Excel / ICS 出力。
"""

from __future__ import annotations

import io
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from database import get_session
from shift_schedule.store import SqlModelShiftRepository
from template_utils import create_templates

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])

DISCLAIMER_TEXT = "【免責事項】本シフト表は数理最適化による提案です。最終的な人員配置および法令適合の確認・承認責任は施設管理者が負います。"


@router.get("/plans/{plan_id}/export", response_class=HTMLResponse)
def exports_menu(
    plan_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    repo = SqlModelShiftRepository(session)
    plan = repo.get_plan(plan_id)
    templates = create_templates()
    return templates.TemplateResponse(
        request,
        "shift_schedule/export_menu.html",
        {
            "request": request,
            "plan_id": plan_id,
            "plan": plan,
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


@router.get("/plans/{plan_id}/export.xlsx")
def export_shift_xlsx(
    plan_id: int,
    session: Session = Depends(get_session),
) -> Response:
    """シフト結果を勤務記号マトリクス＋日別明細の Excel (.xlsx) として出力する。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    repo = SqlModelShiftRepository(session)
    plan = repo.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="シフト計画が見つかりません")
    cells = repo.list_plan_cells(plan_id)

    wb = Workbook()
    ws_matrix = wb.active
    ws_matrix.title = "勤務記号マトリクス"

    # 免責事項ヘッダー
    ws_matrix.append([DISCLAIMER_TEXT])
    ws_matrix.append([f"対象月: {plan.target_month}", f"基準: {plan.staffing_standard_key}"])
    ws_matrix.append([])

    dates = sorted({c.target_date for c in cells})
    staff_ids = sorted({c.staff_user_id for c in cells})
    cell_map: dict[tuple[int, object], list[str]] = {}
    for c in cells:
        if c.cell_state and c.cell_state != "off":
            cell_map.setdefault((c.staff_user_id, c.target_date), []).append(c.slot_label)

    header_row = ["職員ID"] + [d.strftime("%m/%d") for d in dates] + ["出勤日数"]
    ws_matrix.append(header_row)
    header_fill = PatternFill(start_color="E0E7FF", end_color="E0E7FF", fill_type="solid")
    for cell_obj in ws_matrix[ws_matrix.max_row]:
        cell_obj.font = Font(bold=True)
        cell_obj.fill = header_fill
        cell_obj.alignment = Alignment(horizontal="center")

    for sid in staff_ids:
        work_days = 0
        row_vals: list[object] = [f"職員 {sid}"]
        for d in dates:
            labels = cell_map.get((sid, d), [])
            if labels:
                work_days += 1
                row_vals.append(f"{labels[0]}〜{labels[-1]}" if len(labels) > 1 else labels[0])
            else:
                row_vals.append("休")
        row_vals.append(work_days)
        ws_matrix.append(row_vals)

    ws_detail = wb.create_sheet("日別明細")
    ws_detail.append(["職員ID", "日付", "スロット", "状態"])
    for c in sorted(cells, key=lambda x: (x.target_date, x.staff_user_id, x.slot_label)):
        ws_detail.append([c.staff_user_id, c.target_date.isoformat(), c.slot_label, c.cell_state])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return Response(
        content=buf.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename=shift_plan_{plan_id}.xlsx"
        },
    )


@router.get("/plans/{plan_id}/print", response_class=HTMLResponse)
def print_shift_plan(
    plan_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """掲示用・PDF保存用の印刷最適化HTMLビューを返す。"""
    repo = SqlModelShiftRepository(session)
    plan = repo.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="シフト計画が見つかりません")
    cells = repo.list_plan_cells(plan_id)
    dates = sorted({c.target_date for c in cells})
    staff_ids = sorted({c.staff_user_id for c in cells})
    cell_map: dict[tuple[int, object], list[str]] = {}
    for c in cells:
        if c.cell_state and c.cell_state != "off":
            cell_map.setdefault((c.staff_user_id, c.target_date), []).append(c.slot_label)

    rows = []
    for sid in staff_ids:
        day_cells = []
        work_days = 0
        for d in dates:
            labels = cell_map.get((sid, d), [])
            if labels:
                work_days += 1
                summary = f"{labels[0]}-{labels[-1]}" if len(labels) > 1 else labels[0]
            else:
                summary = "休"
            day_cells.append(summary)
        rows.append({"staff_id": sid, "day_cells": day_cells, "work_days": work_days})

    templates = create_templates()
    return templates.TemplateResponse(
        request,
        "shift_schedule/print_view.html",
        {
            "request": request,
            "plan": plan,
            "dates": dates,
            "rows": rows,
            "disclaimer": DISCLAIMER_TEXT,
        },
    )
