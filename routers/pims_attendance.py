from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime, time
from typing import List, Optional
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response, RedirectResponse
from sqlmodel import Session, select

from database import get_session
from models.pims import PunchChild, PunchLog
import pims_service
from template_utils import create_templates
from time_utils import local_naive_now, local_today

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/toukouen", tags=["toukouen"])
templates = create_templates()


@router.get("", response_class=HTMLResponse)
def toukouen_top(
    request: Request,
    session: Session = Depends(get_session),
):
    """F-01: モード選択TOP画面"""
    pims_service.sync_core_children_if_empty(session)
    children = pims_service.get_all_active_children(session)
    child_states = pims_service.get_daily_child_states(session)

    in_care_count = sum(1 for st in child_states.values() if st["status"] == "登園中")
    departed_count = sum(1 for st in child_states.values() if st["status"] == "降園済")
    absent_count = sum(1 for st in child_states.values() if st["status"] == "欠席")

    return templates.TemplateResponse(
        request,
        "toukouen/index.html",
        {
            "request": request,
            "total_children_count": len(children),
            "in_care_count": in_care_count,
            "departed_count": departed_count,
            "absent_count": absent_count,
        },
    )


@router.get("/select", response_class=HTMLResponse)
def toukouen_select(
    request: Request,
    mode: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    """F-02: 園児一覧・タッチ打刻画面 (F-02〜F-07)
    
    mode未指定時は時間帯から自動判定（朝05:00〜11:59は登園、12:00以降は降園）
    """
    if not mode or mode not in {"check_in", "check_out", "absence"}:
        now_time = local_naive_now().time()
        if time(5, 0) <= now_time < time(12, 0):
            mode = "check_in"
        else:
            mode = "check_out"

    pims_service.sync_core_children_if_empty(session)
    children = pims_service.get_all_active_children(session)
    child_states = pims_service.get_daily_child_states(session)

    # クラス名一覧の抽出 & クラスごとの園児数集計
    classrooms = []
    class_counts = {}
    for c in children:
        cname = c.class_name or "未設定"
        if cname not in class_counts:
            classrooms.append(cname)
            class_counts[cname] = 0
        class_counts[cname] += 1

    # 各園児の兄弟リスト辞書 (F-04: 世帯ID連動)
    child_siblings = {}
    for c in children:
        sibs = pims_service.find_siblings(session, c)
        child_siblings[c.child_id] = [
            {"child_id": s.child_id, "name": s.name, "class_name": s.class_name}
            for s in sibs
        ]

    return templates.TemplateResponse(
        request,
        "toukouen/select.html",
        {
            "request": request,
            "mode": mode,
            "children": children,
            "classrooms": classrooms,
            "class_counts": class_counts,
            "child_states": child_states,
            "child_siblings": child_siblings,
        },
    )


@router.post("/punch")
def toukouen_punch(
    request: Request,
    child_ids: List[str] = Form(...),
    punch_type: str = Form(...),
    absence_reason: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
):
    """打刻API (F-02, F-04, F-05, F-06, F-08)"""
    if punch_type not in {"登園", "降園", "欠席"}:
        return JSONResponse({"success": False, "error": "無効な打刻区分です。"}, status_code=400)

    try:
        logs, messages = pims_service.record_punch(
            session=session,
            child_ids=child_ids,
            punch_type=punch_type,
            absence_reason=absence_reason,
            send_email=True,
        )
        log_ids = [l.id for l in logs if l.id is not None]
        updated_states = pims_service.get_daily_child_states(session)

        return JSONResponse({
            "success": True,
            "message": messages[0] if messages else "打刻を記録しました",
            "log_ids": log_ids,
            "child_ids": child_ids,
            "updated_states": updated_states,
        })
    except Exception as exc:
        logger.exception("打刻処理エラー")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@router.post("/undo")
def toukouen_undo(
    request: Request,
    log_ids: List[int] = Form(...),
    session: Session = Depends(get_session),
):
    """直前の打刻取り消し (Undo) API (提案2)"""
    try:
        success, msg, states = pims_service.undo_punch(session, log_ids)
        if not success:
            return JSONResponse({"success": False, "error": msg}, status_code=400)
        return JSONResponse({
            "success": True,
            "message": msg,
            "updated_states": states,
        })
    except Exception as exc:
        logger.exception("打刻取消エラー")
        return JSONResponse({"success": False, "error": str(exc)}, status_code=500)


@router.get("/import/codmon", response_class=HTMLResponse)
def toukouen_import_codmon_get(request: Request):
    """F-09: コドモンCSV取込画面"""
    return templates.TemplateResponse(request, "toukouen/import_codmon.html", {"request": request})


@router.post("/import/codmon", response_class=HTMLResponse)
async def toukouen_import_codmon_post(
    request: Request,
    csv_file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """F-09: コドモンCSV取込実行"""
    try:
        content = await csv_file.read()
        result = pims_service.import_codmon_csv(session, content)
        return templates.TemplateResponse(
            request,
            "toukouen/import_codmon.html",
            {"request": request, "result": result},
        )
    except Exception as exc:
        logger.exception("コドモンCSV取込エラー")
        return templates.TemplateResponse(
            request,
            "toukouen/import_codmon.html",
            {"request": request, "error": str(exc)},
        )


@router.get("/export/pims", response_class=HTMLResponse)
def toukouen_export_pims_get(
    request: Request,
    month: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    """F-10, F-11: ピムスCSV出力設定画面"""
    today = local_today()
    selected_month = month or today.strftime("%Y-%m")
    return templates.TemplateResponse(
        request,
        "toukouen/export_pims.html",
        {
            "request": request,
            "selected_month": selected_month,
            "exported": False,
        },
    )


@router.post("/export/pims", response_class=HTMLResponse)
def toukouen_export_pims_post(
    request: Request,
    target_month: str = Form(...),
    session: Session = Depends(get_session),
):
    """F-10, F-11: ピムスCSV出力生成＆降園抜けチェック"""
    try:
        parts = target_month.split("-")
        year = int(parts[0])
        month = int(parts[1])
    except Exception:
        today = local_today()
        year, month = today.year, today.month

    csv_bytes, missing_checkouts = pims_service.export_pims_csv(session, year, month)
    filename = f"月次報告_児童表_{year}{month:02d}.csv"

    return templates.TemplateResponse(
        request,
        "toukouen/export_pims.html",
        {
            "request": request,
            "selected_month": target_month,
            "exported": True,
            "export_filename": filename,
            "target_year": year,
            "target_month_num": month,
            "missing_checkouts": missing_checkouts,
        },
    )


@router.get("/export/pims/download")
def toukouen_export_pims_download(
    year: int = Query(...),
    month: int = Query(...),
    session: Session = Depends(get_session),
):
    """F-10: ピムス9列CSVダウンロード"""
    csv_bytes, _ = pims_service.export_pims_csv(session, year, month)
    filename = f"月次報告_児童表_{year}{month:02d}.csv"
    encoded_filename = quote(filename)

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
    )


@router.get("/export/missing-checkout/download")
def toukouen_export_missing_checkout_download(
    year: int = Query(...),
    month: int = Query(...),
    session: Session = Depends(get_session),
):
    """F-11: 降園打刻忘れ一覧CSVダウンロード"""
    _, missing_checkouts = pims_service.export_pims_csv(session, year, month)
    csv_bytes = pims_service.export_missing_checkouts_csv(missing_checkouts, year, month)
    filename = f"降園打刻忘れ一覧_{year}{month:02d}.csv"
    encoded_filename = quote(filename)

    return Response(
        content=csv_bytes,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
    )


@router.get("/children", response_class=HTMLResponse)
def toukouen_children_list(
    request: Request,
    notice: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    """園児マスタ管理画面"""
    pims_service.sync_core_children_if_empty(session)
    children = session.exec(select(PunchChild).order_by(PunchChild.sort_order, PunchChild.name)).all()
    return templates.TemplateResponse(
        request,
        "toukouen/children.html",
        {"request": request, "children": children, "notice": notice},
    )


@router.post("/children/save")
def toukouen_children_save(
    request: Request,
    child_id: str = Form(...),
    name: str = Form(...),
    kana: Optional[str] = Form(default=None),
    birth_date: Optional[str] = Form(default=None),
    class_name: str = Form(default="未設定"),
    family_id: Optional[str] = Form(default=None),
    parent_email: Optional[str] = Form(default=None),
    sort_order: int = Form(default=0),
    is_active: Optional[str] = Form(default=None),
    is_edit: str = Form(default="0"),
    session: Session = Depends(get_session),
):
    """園児マスタ保存（新規・編集）"""
    cid = child_id.strip()
    parsed_birth = pims_service.parse_date_str(birth_date)
    active_val = bool(is_active)

    existing = session.get(PunchChild, cid)
    if existing:
        existing.name = name.strip()
        existing.kana = kana.strip() if kana else None
        existing.birth_date = parsed_birth
        existing.class_name = class_name.strip()
        existing.family_id = family_id.strip() if family_id else None
        existing.parent_email = parent_email.strip() if parent_email else None
        existing.sort_order = sort_order
        existing.is_active = active_val
        session.add(existing)
        msg = f"園児「{existing.name}」の情報を更新しました。"
    else:
        new_child = PunchChild(
            child_id=cid,
            name=name.strip(),
            kana=kana.strip() if kana else None,
            birth_date=parsed_birth,
            class_name=class_name.strip(),
            family_id=family_id.strip() if family_id else None,
            parent_email=parent_email.strip() if parent_email else None,
            sort_order=sort_order,
            is_active=active_val,
        )
        session.add(new_child)
        msg = f"園児「{new_child.name}」を新規登録しました。"

    session.commit()
    return RedirectResponse(f"/toukouen/children?notice={quote(msg)}", status_code=303)


@router.post("/children/sync")
def toukouen_children_sync(
    session: Session = Depends(get_session),
):
    """既存台帳からの同期"""
    from models.core import Child, ChildStatus
    core_children = session.exec(select(Child).where(Child.status == ChildStatus.enrolled)).all()
    count = 0
    for cc in core_children:
        cid = str(cc.id)
        existing = session.get(PunchChild, cid)
        c_name = cc.classroom.name if cc.classroom else "未設定"
        if not existing:
            p_child = PunchChild(
                child_id=cid,
                name=f"{cc.last_name} {cc.first_name}".strip(),
                kana=f"{cc.last_name_kana} {cc.first_name_kana}".strip(),
                birth_date=cc.birth_date,
                class_name=c_name,
                family_id=str(cc.family_id) if cc.family_id else None,
                parent_email=cc.guardians[0].email if cc.guardians and cc.guardians[0].email else None,
                sort_order=cc.id or 0,
                is_active=True,
            )
            session.add(p_child)
            count += 1
    session.commit()
    msg = f"既存台帳から {count} 名の園児を同期しました。"
    return RedirectResponse(f"/toukouen/children?notice={quote(msg)}", status_code=303)


@router.get("/logs", response_class=HTMLResponse)
def toukouen_logs(
    request: Request,
    target_date: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    """打刻トランザクションログ一覧画面"""
    day = pims_service.parse_date_str(target_date) or local_today()
    start_dt = datetime.combine(day, time.min)
    end_dt = datetime.combine(day, time.max)

    logs = session.exec(
        select(PunchLog)
        .where(PunchLog.punched_at >= start_dt, PunchLog.punched_at <= end_dt)
        .order_by(PunchLog.punched_at.desc())
    ).all()

    all_children = session.exec(select(PunchChild)).all()
    children_map = {c.child_id: c for c in all_children}

    return templates.TemplateResponse(
        request,
        "toukouen/logs.html",
        {
            "request": request,
            "logs": logs,
            "children_map": children_map,
            "selected_date": day,
        },
    )
