from __future__ import annotations

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from auth import get_current_staff_user
from database import get_session
from models import DocumentExportLog
from staff_permissions import require_document_exporter
from template_utils import create_templates
from time_utils import utc_now

router = APIRouter(prefix="/document-exports", tags=["document-exports"])
templates = create_templates()

EXPORT_TYPE_LABELS = {
    "attendance": "出勤表",
    "zengin": "Zengin",
    "monthly_plan": "月案",
    "billing": "請求明細",
}

EXPORT_FORMAT_LABELS = {
    "csv": "CSV",
    "xlsx": "Excel",
    "pdf": "PDF",
    "txt": "テキスト",
}

STATUS_LABELS = {
    "success": "成功",
    "error": "エラー",
    "warning": "警告",
}


@router.get("", response_class=HTMLResponse)
def document_export_dashboard(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_document_exporter(session, current_user)

    # 過去30日間のログを集計
    since = utc_now() - timedelta(days=30)
    logs = session.exec(
        select(DocumentExportLog)
        .where(DocumentExportLog.created_at >= since)
        .order_by(DocumentExportLog.created_at.desc())
    ).all()

    total_count = len(logs)
    success_count = sum(1 for log in logs if log.status == "success")
    error_count = sum(1 for log in logs if log.status == "error")

    return templates.TemplateResponse(
        request,
        "document_exports/dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "logs": logs,
            "total_count": total_count,
            "success_count": success_count,
            "error_count": error_count,
            "export_type_labels": EXPORT_TYPE_LABELS,
            "export_format_labels": EXPORT_FORMAT_LABELS,
            "status_labels": STATUS_LABELS,
        },
    )


@router.get("/history", response_class=HTMLResponse)
def document_export_history(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
    page: int = Query(default=1, ge=1),
    export_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
):
    require_document_exporter(session, current_user)

    query = select(DocumentExportLog).order_by(DocumentExportLog.created_at.desc())
    if export_type:
        query = query.where(DocumentExportLog.export_type == export_type)
    if status:
        query = query.where(DocumentExportLog.status == status)

    logs = session.exec(query).all()

    per_page = 50
    total = len(logs)
    start = (page - 1) * per_page
    end = start + per_page
    paginated_logs = logs[start:end]
    has_next = end < total

    return templates.TemplateResponse(
        request,
        "document_exports/history.html",
        {
            "request": request,
            "current_user": current_user,
            "logs": paginated_logs,
            "page": page,
            "has_next": has_next,
            "export_type": export_type,
            "status": status,
            "export_type_labels": EXPORT_TYPE_LABELS,
            "export_format_labels": EXPORT_FORMAT_LABELS,
            "status_labels": STATUS_LABELS,
        },
    )


def log_export(
    session: Session,
    *,
    export_type: str,
    export_format: str,
    target_month: Optional[str] = None,
    exported_by_user_id: Optional[str] = None,
    exported_by_name: Optional[str] = None,
    record_count: Optional[int] = None,
    file_size_bytes: Optional[int] = None,
    status: str = "success",
    error_message: Optional[str] = None,
) -> None:
    """帳票エクスポート履歴を記録する。"""
    log = DocumentExportLog(
        export_type=export_type,
        export_format=export_format,
        target_month=target_month,
        exported_by_user_id=exported_by_user_id,
        exported_by_name=exported_by_name,
        record_count=record_count,
        file_size_bytes=file_size_bytes,
        status=status,
        error_message=error_message,
    )
    session.add(log)
    session.commit()
