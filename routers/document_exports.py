from __future__ import annotations

import io
import logging
import re
import zipfile
from datetime import timedelta
from typing import Any, Optional
from urllib.parse import quote
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse
from sqlmodel import Session, func, select

from auth import get_current_staff_user
from database import get_session
from models import Child, Classroom, DocumentExportLog
from plan_docs.contracts import DocumentType
from plan_docs.db_models import PlanDocumentRow
from plan_docs.services.monthly_export import pdf_bytes
from plan_docs.services.monthly_export_layout import make_layout
from plan_docs.services.monthly_library import new_sheet
from staff_permissions import require_document_exporter
from template_utils import create_templates
from time_utils import utc_now

router = APIRouter(prefix="/document-exports", tags=["document-exports"])
templates = create_templates()

EXPORT_TYPE_LABELS = {
    "attendance": "出勤表",
    "zengin": "Zengin",
    "monthly_plan": "月案",
    "daily_plan": "日案",
    "billing": "請求明細",
    "nushift": "NuShiftデータ",
    "monthly_class_batch": "複数クラス月案一括(ZIP)",
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

# 一括 ZIP 出力に必要な reportlab PDF 生成はクラスごとに同期的に走るため、
# 長時間応答なし・メモリ圧迫を防ぐため上限を設ける。
MAX_BATCH_CLASSROOMS = 20


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

    classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()

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
            "classrooms": classrooms,
            "current_month": utc_now().strftime("%Y-%m"),
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

    elif export_type == "daily_plan":
        preview_data["title"] = "デ イ リ ー 指 導 計 画（日 案）"
        preview_data["sections"] = [
            {"label": "対象クラス", "value": "3歳児 さくら組"},
            {"label": "対象日", "value": f"{month_str}-16 (月)"},
            {"label": "作成担当者", "value": current_user.name or "担任保育士"},
        ]
        preview_data["fields"] = [
            {"name": "本日のねらい", "content": "秋の自然物に親しみながら、友達と一緒に集めた落ち葉や木の実を使って見立て遊びを楽しむ。"},
            {"name": "健康・安全への配慮", "content": "気温の変化に合わせた衣服の調整を行い、外遊び後の手洗い・うがいを丁寧に行う。"},
            {"name": "1日の主な活動", "content": "近隣公園への散歩（落ち葉拾い）、見立て遊び、給食指導"},
            {"name": "評価・反省", "content": "公園での落ち葉集めはどの子も意欲的に参加し、見立て遊びへ発展させることができた。"},
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


def _determine_classroom_age(session: Session, classroom: Classroom, target_month: str) -> int:
    """クラスの対象年齢（0〜5歳）を判定する。"""
    row = session.exec(
        select(PlanDocumentRow).where(
            PlanDocumentRow.document_type == DocumentType.MONTHLY_PLAN.value,
            PlanDocumentRow.classroom_ref == classroom.name,
            PlanDocumentRow.target_month == target_month,
        )
    ).first()
    if row and row.monthly_sheet and "age" in row.monthly_sheet:
        return int(row.monthly_sheet["age"])

    match = re.search(r"([0-5])歳", classroom.name)
    if match:
        return int(match.group(1))

    try:
        from datetime import date
        y, m = map(int, target_month.split("-"))
        ref_date = date(y, m, 1)
        children = session.exec(select(Child).where(Child.classroom_id == classroom.id)).all()
        if children:
            ages = []
            for child in children:
                if child.birth_date:
                    age = ref_date.year - child.birth_date.year - (
                        (ref_date.month, ref_date.day) < (child.birth_date.month, child.birth_date.day)
                    )
                    ages.append(max(0, min(5, age)))
            if ages:
                return max(set(ages), key=ages.count)
    except Exception:
        logger.warning("Failed to determine classroom age from children birth dates", exc_info=True)

    return 3


@router.get("/download/monthly-class-batch")
def download_monthly_class_batch(
    month: Optional[str] = Query(default=None),
    classroom_ids: list[int] = Query(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """選択された複数クラスの月案PDFを一括でZIPアーカイブ化してダウンロードする。"""
    require_document_exporter(session, current_user)

    if not classroom_ids:
        raise HTTPException(status_code=400, detail="対象クラスを1つ以上選択してください")
    unique_classroom_ids = list(dict.fromkeys(classroom_ids))
    if len(unique_classroom_ids) > MAX_BATCH_CLASSROOMS:
        raise HTTPException(
            status_code=400,
            detail=f"一括出力できるクラスは{MAX_BATCH_CLASSROOMS}件までです",
        )

    month_str = month or utc_now().strftime("%Y-%m")
    try:
        y, m = map(int, month_str.split("-"))
        if not (2000 <= y <= 2100 and 1 <= m <= 12):
            raise ValueError
    except Exception:
        raise HTTPException(status_code=400, detail="対象月の形式が正しくありません (YYYY-MM)")

    classrooms = session.exec(
        select(Classroom).where(Classroom.id.in_(unique_classroom_ids)).order_by(Classroom.display_order, Classroom.id)
    ).all()
    if not classrooms:
        raise HTTPException(status_code=404, detail="指定されたクラスが見つかりません")

    zip_buffer = io.BytesIO()
    record_count = 0

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for classroom in classrooms:
            row = session.exec(
                select(PlanDocumentRow).where(
                    PlanDocumentRow.document_type == DocumentType.MONTHLY_PLAN.value,
                    PlanDocumentRow.classroom_ref == classroom.name,
                    PlanDocumentRow.target_month == month_str,
                )
            ).first()

            if row and row.monthly_sheet:
                sheet = row.monthly_sheet
                owner_name = row.owner_name or (getattr(current_user, "name", None) or "担任")
                age = sheet.get("age", 3)
            else:
                age = _determine_classroom_age(session, classroom, month_str)
                sheet = new_sheet(session, classroom, month_str, age)
                owner_name = getattr(current_user, "name", None) or "担任"

            context = {
                "target_month": month_str,
                "age": age,
                "classroom_name": classroom.name,
                "owner_name": owner_name,
                "sheet": sheet,
            }
            layout = make_layout(context)
            pdf_data = pdf_bytes(layout)

            pdf_filename = f"{month_str}_{age}歳児_{classroom.name}_月案.pdf"
            zf.writestr(pdf_filename, pdf_data)
            record_count += 1

    zip_bytes = zip_buffer.getvalue()
    file_size = len(zip_bytes)

    log_export(
        session,
        export_type="monthly_class_batch",
        export_format="zip",
        target_month=month_str,
        exported_by_user_id=getattr(current_user, "user_id", getattr(current_user, "id", None)),
        exported_by_name=getattr(current_user, "name", None),
        record_count=record_count,
        file_size_bytes=file_size,
        status="success",
    )

    zip_filename = f"{month_str}_月案一括_{record_count}クラス.zip"
    quoted_filename = quote(zip_filename)

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )


@router.get("/download-daily-plan", response_class=Response)
def download_daily_plan_pdf_route(
    date_str: Optional[str] = Query(default=None, alias="date"),
    classroom_id: Optional[int] = Query(default=None),
    document_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """日案のA4縦PDF帳票を出力・ダウンロードする (P2-1, P2-2)。"""
    require_document_exporter(session, current_user)
    from plan_docs.services.daily_export_layout import render_daily_plan_pdf
    from plan_docs.db_models import PlanDocumentAttachmentRow, PlanDocumentRow

    target_date_val = date_str or utc_now().strftime("%Y-%m-%d")
    cls_name = "さくら組"
    if classroom_id:
        cls = session.exec(select(Classroom).where(Classroom.id == classroom_id)).first()
        if cls:
            cls_name = cls.name

    sample_plan = {
        "title": "デイリー指導計画（日案）",
        "facility_name": "あんな保育園",
        "target_date": target_date_val,
        "weather": "晴",
        "classroom_name": cls_name,
        "age_class": "3歳児",
        "owner_name": current_user.name or "担任",
        "daily_aims": "秋の自然物に親しみながら、友達と一緒に集めた落ち葉や木の実を使って見立て遊びを楽しむ。",
        "daily_health_safety": "気温の変化に合わせた衣服の調整を行い、外遊び後の手洗い・うがいを丁寧に行う。",
        "timeline_rows": [
            {
                "time_label": "9:00〜9:30",
                "child_state": "順次登園。身の回りの整理（タオル掛け・シール貼り）を自分で進める。",
                "support": "笑顔で受け入れ、視診を行い保護者からの引き継ぎ事項を確認する。",
                "considerations": "健康観察シート記入、室温・湿度管理",
            },
            {
                "time_label": "10:00〜11:15",
                "child_state": "南児童公園へ散歩。様々な形の落ち葉やどんぐりを友達と見せ合い、袋に集める。",
                "support": "危険箇所には近寄らないよう見守り、発見した自然物の名前を一緒に調べる。",
                "considerations": "道路横断時の安全確認、人数確認徹底",
            },
            {
                "time_label": "11:30〜12:30",
                "child_state": "手洗い・うがいをして給食準備。友達と楽しく食事をする。",
                "support": "正しい手洗いを援助する。楽しい雰囲気で食事が進むよう声がけする。",
                "considerations": "アレルギー誤配膳防止の指差し確認",
            },
            {
                "time_label": "12:45〜14:45",
                "child_state": "着替え、絵本の読み聞かせを聞きながら入眠する。",
                "support": "背中をやさしくトントンし、安心して眠れるよう配慮する。",
                "considerations": "午睡チェック（呼吸・顔色）5分間隔記録",
            },
        ],
        "reflection": "公園での落ち葉集めはどの子も意欲的に参加し、見立て遊びへ発展させることができた。道路歩行の際に列が崩れそうになったため、明日はペアの友達と手をつなぎ続ける意識付けを徹底したい。",
    }

    if document_id:
        doc = session.get(PlanDocumentRow, document_id)
        if doc:
            sample_plan["title"] = doc.title
            sample_plan["target_date"] = doc.target_date or target_date_val
            sample_plan["owner_name"] = doc.owner_name or sample_plan["owner_name"]
            attachments = session.exec(
                select(PlanDocumentAttachmentRow).where(PlanDocumentAttachmentRow.plan_document_id == doc.id)
            ).all()
            sample_plan["attachments"] = [
                {
                    "file_name": att.file_name,
                    "caption": att.caption,
                    "content": att.content,
                    "layout_position": att.layout_position,
                }
                for att in attachments
            ]

    pdf_bytes_data = render_daily_plan_pdf(sample_plan)

    log_export(
        session,
        export_type="daily_plan",
        export_format="pdf",
        target_month=target_date_val[:7],
        exported_by_user_id=getattr(current_user, "user_id", getattr(current_user, "id", None)),
        exported_by_name=getattr(current_user, "name", None),
        record_count=1,
        file_size_bytes=len(pdf_bytes_data),
        status="success",
    )

    filename = f"daily_plan_{cls_name}_{target_date_val}.pdf"
    encoded_filename = quote(filename.encode("utf-8"))

    return Response(
        content=pdf_bytes_data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Cache-Control": "no-store",
            "Pragma": "no-cache",
        },
    )
