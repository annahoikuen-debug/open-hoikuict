from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

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
    "nushift": "NuShiftデータ",
}

EXPORT_FORMAT_LABELS = {
    "csv": "CSV",
    "xlsx": "Excel",
    "pdf": "PDF",
    "txt": "テキスト",
    "zip": "ZIP",
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

    base_query = select(DocumentExportLog)
    count_query = select(func.count(DocumentExportLog.id))
    if export_type:
        base_query = base_query.where(DocumentExportLog.export_type == export_type)
        count_query = count_query.where(DocumentExportLog.export_type == export_type)
    if status:
        base_query = base_query.where(DocumentExportLog.status == status)
        count_query = count_query.where(DocumentExportLog.status == status)

    total = session.exec(count_query).one()

    per_page = 50
    start = (page - 1) * per_page
    end = start + per_page
    paginated_logs = session.exec(
        base_query.order_by(DocumentExportLog.created_at.desc()).offset(start).limit(per_page)
    ).all()
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


@router.get("/preview/{export_type}")
def get_document_preview(
    export_type: str,
    target_month: Optional[str] = Query(default=None),
    classroom_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """帳票エクスポート前のプレビューデータおよび監査・配置事前チェック警告を返す。"""
    require_document_exporter(session, current_user)

    if export_type not in EXPORT_TYPE_LABELS:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="未対応の帳票種別です")

    month_str = target_month or utc_now().strftime("%Y-%m")
    warnings: list[dict[str, str]] = []
    preview_data: dict[str, Any] = {
        "export_type": export_type,
        "export_type_label": EXPORT_TYPE_LABELS.get(export_type, export_type),
        "target_month": month_str,
        "facility_name": "社会福祉法人 ぬのはな保育園",
        "is_sample": True,
        "sample_notice": "※表示されている内容は書面レイアウトおよび配置基準の確認用サンプルです。",
    }

    if export_type == "attendance":
        preview_data["title"] = "勤 務 割 実 績 表（監 査 提 出 用）"
        preview_data["sections"] = [
            {"label": "対象期間", "value": f"{month_str} (1日〜末日)"},
            {"label": "集計対象職員", "value": "常勤・非常勤 全18名"},
            {"label": "配置基準連動", "value": "厚生労働省告示第49号 準拠"},
        ]
        preview_data["sample_headers"] = ["日付・曜日", "早番 (7:00-)", "日勤 (8:30-)", "遅番 (10:00-)", "配置充足率"]
        preview_data["sample_rows"] = [
            [f"{month_str}-01 (月)", "2名", "6名", "3名", "100% (基準クリア)"],
            [f"{month_str}-02 (火)", "2名", "7名", "2名", "100% (基準クリア)"],
            [f"{month_str}-03 (水)", "2名", "6名", "3名", "100% (基準クリア)"],
        ]

    elif export_type == "monthly_plan":
        preview_data["title"] = "月 次 指 導 計 画 書（月 案）"
        preview_data["sections"] = [
            {"label": "対象クラス", "value": "3歳児 すみれ組"},
            {"label": "対象月", "value": month_str},
            {"label": "作成担当者", "value": current_user.name or "担任保育士"},
        ]
        preview_data["fields"] = [
            {"name": "今月のねらい", "content": "秋の自然物に触れ、落ち葉や木の実を使って見立て遊びや集団遊びを楽しむ。"},
            {"name": "養護（生命・情緒）", "content": "手洗い・うがいを丁寧に行い、衣服の調節を自分で試みる。"},
            {"name": "教育（5領域）", "content": "散歩先で拾った自然物を使って造形遊びを行い、形や色の違いに気づく機会を設ける。"},
            {"name": "保護者・地域支援", "content": "感染症予防の呼びかけを行い、家庭での健康管理についての情報共有を図る。"},
        ]

    elif export_type == "billing":
        preview_data["title"] = "延 長 保 育 料 ・ 請 求 明 細 書"
        preview_data["sections"] = [
            {"label": "対象月", "value": month_str},
            {"label": "請求対象児童", "value": "全園児 84名"},
            {"label": "振替指定日", "value": f"{month_str}-27"},
        ]
        preview_data["sample_headers"] = ["園児氏名", "基本保育料", "延長保育料", "実費・給食費", "請求合計"]
        preview_data["sample_rows"] = [
            ["山田 太郎", "¥0 (無償化)", "¥3,500 (7時間)", "¥5,500", "¥9,000"],
            ["佐藤 健太", "¥0 (無償化)", "¥1,500 (3時間)", "¥5,500", "¥7,000"],
            ["高橋 蓮", "¥0 (無償化)", "¥0 (延長なし)", "¥5,500", "¥5,500"],
        ]

    elif export_type == "zengin":
        preview_data["title"] = "全 銀 協 フ ォ ー マ ッ ト 振 替 デ ー タ"
        preview_data["sections"] = [
            {"label": "対象サイクル", "value": month_str},
            {"label": "電文種別", "value": "預金口座振替依頼電文 (固定長120B)"},
            {"label": "文字コード", "value": "CP932 (半角カタカナ・英数字)"},
        ]

    return {
        "export_type": export_type,
        "target_month": month_str,
        "warnings": warnings,
        "preview_data": preview_data,
    }


def log_export(
    session: Session,
    *,
    export_type: str,
    export_format: str,
    target_month: Optional[str] = None,
    exported_by_user_id: Optional[UUID | str] = None,
    exported_by_name: Optional[str] = None,
    record_count: Optional[int] = None,
    file_size_bytes: Optional[int] = None,
    status: str = "success",
    error_message: Optional[str] = None,
) -> None:
    """帳票エクスポート履歴を記録する。"""
    user_uuid: Optional[UUID] = None
    if exported_by_user_id is not None:
        if isinstance(exported_by_user_id, UUID):
            user_uuid = exported_by_user_id
        else:
            try:
                user_uuid = UUID(exported_by_user_id)
            except (ValueError, TypeError):
                user_uuid = None

    log = DocumentExportLog(
        export_type=export_type,
        export_format=export_format,
        target_month=target_month,
        exported_by_user_id=user_uuid,
        exported_by_name=exported_by_name,
        record_count=record_count,
        file_size_bytes=file_size_bytes,
        status=status,
        error_message=error_message,
    )
    session.add(log)
    session.commit()
