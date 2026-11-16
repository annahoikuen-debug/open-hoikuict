from __future__ import annotations

from typing import Any, Optional
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlmodel import Session, col, or_, select

from auth import get_current_staff_user
from database import get_session
from models import Child, DailyContactEntry, Family, ParentAccount
from models.notice import Notice
from template_utils import create_templates

templates = create_templates()
router = APIRouter(prefix="/staff", tags=["search"])


@router.get("/search", response_class=HTMLResponse)
def staff_search(
    request: Request,
    q: Optional[str] = "",
    category: Optional[str] = "all",
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """職員用クイック横断検索: 園児・保護者・お知らせ・連絡帳を横断検索する。"""
    query_text = (q or "").strip()
    selected_category = category or "all"

    results: dict[str, list[dict[str, Any]]] = {
        "child": [],
        "parent": [],
        "notice": [],
        "contact": [],
    }
    counts = {"all": 0, "child": 0, "parent": 0, "notice": 0, "contact": 0}

    if query_text:
        like_pattern = f"%{query_text}%"

        # 1. 園児検索 (Child)
        child_stmt = (
            select(Child)
            .where(
                or_(
                    col(Child.last_name).like(like_pattern),
                    col(Child.first_name).like(like_pattern),
                    col(Child.last_name_kana).like(like_pattern),
                    col(Child.first_name_kana).like(like_pattern),
                )
            )
            .limit(10)
        )
        children = session.exec(child_stmt).all()
        for c in children:
            classroom_name = c.classroom.name if c.classroom else "クラス未設定"
            results["child"].append({
                "type": "child",
                "tag": "園児",
                "title": f"{c.last_name} {c.first_name} ({c.last_name_kana} {c.first_name_kana})",
                "subtitle": f"{classroom_name} / ステータス: {c.status.value}",
                "url": f"/children/{c.id}",
            })

        # 2. 保護者・家族検索 (ParentAccount, Family)
        parent_stmt = (
            select(ParentAccount)
            .where(
                or_(
                    col(ParentAccount.display_name).like(like_pattern),
                    col(ParentAccount.email).like(like_pattern),
                )
            )
            .limit(10)
        )
        parents = session.exec(parent_stmt).all()
        for p in parents:
            fam_name = p.family.family_name if p.family else "家族未設定"
            results["parent"].append({
                "type": "parent",
                "tag": "保護者",
                "title": f"{p.display_name} ({p.email})",
                "subtitle": f"家族名: {fam_name}",
                "url": "/parent-accounts",
            })

        family_stmt = (
            select(Family)
            .where(col(Family.family_name).like(like_pattern))
            .limit(10)
        )
        families = session.exec(family_stmt).all()
        for f in families:
            results["parent"].append({
                "type": "parent",
                "tag": "家族",
                "title": f"{f.family_name}",
                "subtitle": f"住所: {f.home_address or '未登録'}",
                "url": "/families",
            })

        # 3. お知らせ検索 (Notice)
        notice_stmt = (
            select(Notice)
            .where(
                or_(
                    col(Notice.title).like(like_pattern),
                    col(Notice.body).like(like_pattern),
                )
            )
            .order_by(col(Notice.created_at).desc())
            .limit(10)
        )
        notices = session.exec(notice_stmt).all()
        for n in notices:
            results["notice"].append({
                "type": "notice",
                "tag": "お知らせ",
                "title": n.title,
                "subtitle": f"{n.status.label} / 優先度: {n.priority.label} / {n.created_at.strftime('%Y-%m-%d')}",
                "url": f"/notices/{n.id}",
            })

        # 4. 連絡帳検索 (DailyContactEntry)
        contact_stmt = (
            select(DailyContactEntry)
            .where(
                or_(
                    col(DailyContactEntry.contact_note).like(like_pattern),
                    col(DailyContactEntry.condition_note).like(like_pattern),
                    col(DailyContactEntry.absence_note).like(like_pattern),
                )
            )
            .order_by(col(DailyContactEntry.target_date).desc())
            .limit(10)
        )
        contacts = session.exec(contact_stmt).all()
        for entry in contacts:
            c_name = entry.child.full_name if entry.child else f"園児ID:{entry.child_id}"
            body_preview = entry.contact_note or entry.condition_note or entry.absence_note or "記入なし"
            results["contact"].append({
                "type": "contact",
                "tag": "連絡帳",
                "title": f"{c_name}（{entry.target_date.strftime('%Y-%m-%d')}）",
                "subtitle": body_preview[:60] + ("..." if len(body_preview) > 60 else ""),
                "url": f"/daily-contacts/{entry.child_id}?date={entry.target_date}",
            })

        counts["child"] = len(results["child"])
        counts["parent"] = len(results["parent"])
        counts["notice"] = len(results["notice"])
        counts["contact"] = len(results["contact"])
        counts["all"] = sum([counts["child"], counts["parent"], counts["notice"], counts["contact"]])

    if request.headers.get("accept") == "application/json":
        return JSONResponse({
            "query": query_text,
            "category": selected_category,
            "counts": counts,
            "results": results,
        })

    return templates.TemplateResponse(
        request,
        "staff/search_results.html",
        {
            "request": request,
            "current_user": current_user,
            "query": query_text,
            "category": selected_category,
            "counts": counts,
            "results": results,
        },
    )
