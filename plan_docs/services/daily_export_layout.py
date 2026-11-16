"""指導案（日案）の A4 縦 PDF 帳票レイアウトエンジン (P2-1)。"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas

FONT_PATH = Path(__file__).resolve().parents[2] / "static/fonts/NotoSansJP-Regular.ttf"
FONT = "DailyNotoSansJP"
try:
    pdfmetrics.registerFont(TTFont(FONT, str(FONT_PATH)))
except Exception:
    FONT = "Helvetica"


def _wrap_text_to_lines(text: str, max_width_pt: float, font_size: float) -> list[str]:
    """与えられた最大幅 (pt) に収まるよう文字列を折り返し、行リストを返す。禁則処理を含む。"""
    if not text:
        return []
    lines: list[str] = []
    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for para in paragraphs:
        if not para:
            lines.append("")
            continue
        cur_line = ""
        for char in para:
            test_line = cur_line + char
            w = pdfmetrics.stringWidth(test_line, FONT, font_size)
            if w <= max_width_pt:
                cur_line = test_line
            else:
                # 追い出し・追い込みの簡易禁則処理
                if char in "、。，．！？)]）］｝」』】〉》" and cur_line:
                    cur_line += char
                    lines.append(cur_line)
                    cur_line = ""
                else:
                    lines.append(cur_line)
                    cur_line = char
        if cur_line:
            lines.append(cur_line)
    return lines


def render_daily_plan_pdf(plan_data: dict[str, Any]) -> bytes:
    """日案データ辞書を受け取り、A4縦 1ページの PDF バイナリを生成する (P2-1)。"""
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    page_w, page_h = A4
    margin = 36.0  # 0.5 inch (約 12.7mm)
    content_w = page_w - (margin * 2)

    title = plan_data.get("title") or "デイリー指導計画（日案）"
    facility_name = plan_data.get("facility_name") or "あんな保育園"
    target_date = plan_data.get("target_date") or ""
    weather = plan_data.get("weather") or "晴"
    classroom_name = plan_data.get("classroom_name") or ""
    age_class = plan_data.get("age_class") or ""
    owner_name = plan_data.get("owner_name") or ""
    daily_aims = plan_data.get("daily_aims") or ""
    daily_health_safety = plan_data.get("daily_health_safety") or plan_data.get("daily_content") or ""
    timeline_rows = plan_data.get("timeline_rows") or []
    reflection = plan_data.get("reflection") or ""

    canvas.setTitle(f"日案_{classroom_name}_{target_date}")
    canvas.setAuthor(facility_name)

    # 1. タイトル
    canvas.setFont(FONT, 16)
    canvas.setFillColorRGB(0.1, 0.1, 0.1)
    canvas.drawCentredString(page_w / 2, page_h - margin - 14, title)

    # 2. 基本情報サブヘッダー
    sub_top = page_h - margin - 32
    canvas.setFont(FONT, 9)
    canvas.setFillColorRGB(0.2, 0.2, 0.2)
    canvas.drawString(margin, sub_top, f"施設名: {facility_name}")
    canvas.drawCentredString(page_w / 2, sub_top, f"実施日: {target_date} ({weather})")
    cls_label = f"対象: {classroom_name} ({age_class})" if age_class else f"対象: {classroom_name}"
    canvas.drawRightString(page_w - margin, sub_top, cls_label)

    # 区切り線
    canvas.setStrokeColorRGB(0.2, 0.2, 0.2)
    canvas.setLineWidth(1.0)
    canvas.line(margin, sub_top - 6, page_w - margin, sub_top - 6)

    cur_y = sub_top - 12

    # 3. ねらい・環境構成 枠（左右2分割）
    box_h = 56.0
    half_w = (content_w - 6) / 2
    # 左枠: ねらい
    canvas.setFillColorRGB(0.96, 0.97, 0.96)
    canvas.rect(margin, cur_y - box_h, half_w, box_h, fill=1, stroke=1)
    canvas.setFillColorRGB(0.1, 0.1, 0.1)
    canvas.setFont(FONT, 8.5)
    canvas.drawString(margin + 6, cur_y - 12, "【本日のねらい】")
    aim_lines = _wrap_text_to_lines(daily_aims, half_w - 12, 7.5)
    canvas.setFont(FONT, 7.5)
    for idx, l in enumerate(aim_lines[:3]):
        canvas.drawString(margin + 6, cur_y - 24 - (idx * 10), l)

    # 右枠: 健康・安全・環境構成
    rx = margin + half_w + 6
    canvas.setFillColorRGB(0.96, 0.97, 0.96)
    canvas.rect(rx, cur_y - box_h, half_w, box_h, fill=1, stroke=1)
    canvas.setFillColorRGB(0.1, 0.1, 0.1)
    canvas.setFont(FONT, 8.5)
    canvas.drawString(rx + 6, cur_y - 12, "【健康・安全・配慮】")
    hs_lines = _wrap_text_to_lines(daily_health_safety, half_w - 12, 7.5)
    canvas.setFont(FONT, 7.5)
    for idx, l in enumerate(hs_lines[:3]):
        canvas.drawString(rx + 6, cur_y - 24 - (idx * 10), l)

    cur_y = cur_y - box_h - 10

    # 4. 1日の流れ タイムライン表 (4列: 時間、子どもの様子、保育士の援助、配慮事項)
    # 列幅比率: 時間(65pt), 様子(160pt), 援助(160pt), 配慮(残り)
    col_w_time = 62.0
    col_w_child = (content_w - col_w_time) * 0.35
    col_w_support = (content_w - col_w_time) * 0.35
    col_w_care = content_w - col_w_time - col_w_child - col_w_support

    # 表見出し
    header_h = 16.0
    canvas.setFillColorRGB(0.92, 0.93, 0.94)
    canvas.rect(margin, cur_y - header_h, content_w, header_h, fill=1, stroke=1)
    canvas.setFillColorRGB(0.1, 0.1, 0.1)
    canvas.setFont(FONT, 8.0)
    canvas.drawCentredString(margin + col_w_time / 2, cur_y - 11, "時間")
    canvas.drawCentredString(margin + col_w_time + col_w_child / 2, cur_y - 11, "子どもの活動・様子")
    canvas.drawCentredString(margin + col_w_time + col_w_child + col_w_support / 2, cur_y - 11, "保育士の援助・配慮")
    canvas.drawCentredString(margin + col_w_time + col_w_child + col_w_support + col_w_care / 2, cur_y - 11, "配慮事項・環境構成")

    # 縦罫線（見出し部）
    canvas.line(margin + col_w_time, cur_y, margin + col_w_time, cur_y - header_h)
    canvas.line(margin + col_w_time + col_w_child, cur_y, margin + col_w_time + col_w_child, cur_y - header_h)
    canvas.line(margin + col_w_time + col_w_child + col_w_support, cur_y, margin + col_w_time + col_w_child + col_w_support, cur_y - header_h)

    cur_y -= header_h

    # タイムライン行の描画（最大 6〜8 行程度）
    min_row_h = 44.0
    for row in timeline_rows:
        time_text = row.get("time_label") or row.get("time") or ""
        child_text = row.get("child_state") or row.get("children") or ""
        support_text = row.get("support") or ""
        care_text = row.get("considerations") or row.get("care") or ""

        c_lines = _wrap_text_to_lines(child_text, col_w_child - 8, 7.0)
        s_lines = _wrap_text_to_lines(support_text, col_w_support - 8, 7.0)
        r_lines = _wrap_text_to_lines(care_text, col_w_care - 8, 7.0)

        max_lines = max(len(c_lines), len(s_lines), len(r_lines), 2)
        row_h = max(min_row_h, max_lines * 9.5 + 8)

        # 枠線
        canvas.setFillColorRGB(1.0, 1.0, 1.0)
        canvas.rect(margin, cur_y - row_h, content_w, row_h, fill=1, stroke=1)
        # 縦罫線
        canvas.line(margin + col_w_time, cur_y, margin + col_w_time, cur_y - row_h)
        canvas.line(margin + col_w_time + col_w_child, cur_y, margin + col_w_time + col_w_child, cur_y - row_h)
        canvas.line(margin + col_w_time + col_w_child + col_w_support, cur_y, margin + col_w_time + col_w_child + col_w_support, cur_y - row_h)

        # 時間
        canvas.setFillColorRGB(0.1, 0.1, 0.1)
        canvas.setFont(FONT, 7.5)
        canvas.drawCentredString(margin + col_w_time / 2, cur_y - 14, time_text)

        # 本文列
        canvas.setFont(FONT, 7.0)
        for i, l in enumerate(c_lines[:6]):
            canvas.drawString(margin + col_w_time + 4, cur_y - 11 - (i * 9), l)
        for i, l in enumerate(s_lines[:6]):
            canvas.drawString(margin + col_w_time + col_w_child + 4, cur_y - 11 - (i * 9), l)
        for i, l in enumerate(r_lines[:6]):
            canvas.drawString(margin + col_w_time + col_w_child + col_w_support + 4, cur_y - 11 - (i * 9), l)

        cur_y -= row_h

    # 5. 評価・反省（振り返り）欄
    cur_y -= 8
    ref_h = 58.0
    canvas.setFillColorRGB(1.0, 1.0, 1.0)
    canvas.rect(margin, cur_y - ref_h, content_w, ref_h, fill=1, stroke=1)
    canvas.setFillColorRGB(0.1, 0.1, 0.1)
    canvas.setFont(FONT, 8.0)
    canvas.drawString(margin + 6, cur_y - 12, "【本日の評価・反省（振り返り）】")
    ref_lines = _wrap_text_to_lines(reflection, content_w - 12, 7.0)
    canvas.setFont(FONT, 7.0)
    for idx, l in enumerate(ref_lines[:4]):
        canvas.drawString(margin + 6, cur_y - 23 - (idx * 9.5), l)

    # 6. 捺印欄（右下）
    cur_y -= (ref_h + 8)
    stamp_w = 46.0
    stamp_h = 42.0
    stamp_roles = ["園長", "主任", "担任"]
    start_x = page_w - margin - (stamp_w * 3)

    for i, role in enumerate(stamp_roles):
        sx = start_x + (i * stamp_w)
        canvas.setFillColorRGB(1.0, 1.0, 1.0)
        canvas.rect(sx, cur_y - stamp_h, stamp_w, stamp_h, fill=1, stroke=1)
        # 上部役職名
        canvas.setFillColorRGB(0.92, 0.93, 0.94)
        canvas.rect(sx, cur_y - 12, stamp_w, 12, fill=1, stroke=1)
        canvas.setFillColorRGB(0.2, 0.2, 0.2)
        canvas.setFont(FONT, 7.0)
        canvas.drawCentredString(sx + stamp_w / 2, cur_y - 9, role)

        if role == "担任" and owner_name:
            canvas.setFont(FONT, 7.5)
            canvas.setFillColorRGB(0.1, 0.1, 0.1)
            canvas.drawCentredString(sx + stamp_w / 2, cur_y - 28, owner_name)

    canvas.showPage()

    # ==========================================
    # P2-2: 添付図表・環境構成（2ページ目以降）
    # ==========================================
    attachments = plan_data.get("attachments") or []
    if attachments:
        from reportlab.lib.utils import ImageReader

        canvas.setFont(FONT, 13.0)
        canvas.setFillColorRGB(0.1, 0.1, 0.1)
        canvas.drawString(margin, page_h - margin - 15, "【参考図表・環境構成】")
        canvas.setFont(FONT, 8.5)
        canvas.setFillColorRGB(0.4, 0.4, 0.4)
        canvas.drawRightString(page_w - margin, page_h - margin - 15, f"{facility_name} / {title}")

        canvas.setStrokeColorRGB(0.8, 0.8, 0.8)
        canvas.line(margin, page_h - margin - 22, page_w - margin, page_h - margin - 22)

        cur_att_y = page_h - margin - 35
        for att in attachments:
            content_bytes = att.get("content")
            if not content_bytes:
                continue
            caption = att.get("caption") or att.get("file_name") or "参考図表"

            try:
                img_reader = ImageReader(BytesIO(content_bytes))
                iw, ih = img_reader.getSize()
                max_w = content_w
                max_h = 240.0
                scale = min(max_w / iw, max_h / ih, 1.0)
                draw_w = iw * scale
                draw_h = ih * scale

                if cur_att_y - draw_h - 25 < margin:
                    canvas.showPage()
                    cur_att_y = page_h - margin - 25

                canvas.setStrokeColorRGB(0.85, 0.88, 0.90)
                canvas.rect(margin, cur_att_y - draw_h, draw_w, draw_h, fill=0, stroke=1)
                canvas.drawImage(img_reader, margin, cur_att_y - draw_h, width=draw_w, height=draw_h, preserveAspectRatio=True)

                canvas.setFont(FONT, 8.5)
                canvas.setFillColorRGB(0.2, 0.2, 0.2)
                canvas.drawString(margin, cur_att_y - draw_h - 12, f"▲ {caption}")

                cur_att_y -= (draw_h + 30)
            except Exception:
                continue

        canvas.showPage()

    canvas.save()
    return buffer.getvalue()
