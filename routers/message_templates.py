from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, col, select

from auth import get_current_staff_user, require_can_edit
from database import get_session
from models import MessageTemplate
from template_utils import create_templates
from time_utils import utc_now

router = APIRouter(prefix="/message-templates", tags=["message-templates"])
templates = create_templates()

CATEGORY_LABELS = {
    "daily_contact_reply": "連絡帳返信",
    "notice": "お知らせ",
    "generic": "共通・その他",
}

DEFAULT_TEMPLATES = [
    {
        "category": "daily_contact_reply",
        "title": "園庭遊び（元気・完食）",
        "content": "今日は晴天の下、園庭でお友達とかけっこや砂場遊びを元気いっぱい楽しみました。給食も笑顔でおかわりして完食しています。",
        "display_order": 1,
    },
    {
        "category": "daily_contact_reply",
        "title": "お昼寝ぐっすり・機嫌良好",
        "content": "午前中の活動でたくさん体を動かし、お昼寝は途中で起きることなくぐっすり眠っていました。目覚めも機嫌よく過ごしています。",
        "display_order": 2,
    },
    {
        "category": "daily_contact_reply",
        "title": "給食おかわり・スプーン練習",
        "content": "今日のメニューが大好きだったようで、スープとご飯を笑顔でおかわりしていました。スプーンの使い方も日増しに上手になっています。",
        "display_order": 3,
    },
    {
        "category": "daily_contact_reply",
        "title": "少し鼻水・検温平熱",
        "content": "日中、少し鼻水が出ていたためこまめに拭き取ってケアしています。検温は36.6℃で平熱です。ご家庭でもゆっくり休ませてあげてください。",
        "display_order": 4,
    },
    {
        "category": "notice",
        "title": "雨天時の登園・持ち物について",
        "content": "雨天時は長靴での登園をお願いいたします。靴箱のスペースの都合上、レインコートは個人フックにお掛けください。",
        "display_order": 1,
    },
    {
        "category": "notice",
        "title": "季節の感染症予防のお願い",
        "content": "園内でも手洗い・うがい・換気を徹底しております。登園前にお子様の検温を行い、37.5℃以上の発熱や体調不良時は登園をお控えください。",
        "display_order": 2,
    },
]


def ensure_default_templates(session: Session) -> None:
    count = session.exec(select(MessageTemplate)).first()
    if count is None:
        now = utc_now()
        for item in DEFAULT_TEMPLATES:
            t = MessageTemplate(
                category=item["category"],
                title=item["title"],
                content=item["content"],
                display_order=item["display_order"],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(t)
        session.commit()


@router.get("", response_class=HTMLResponse)
def list_message_templates(
    request: Request,
    category: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """定型文テンプレート一覧管理画面。"""
    ensure_default_templates(session)

    query = select(MessageTemplate).order_by(
        col(MessageTemplate.category),
        col(MessageTemplate.display_order),
        col(MessageTemplate.id),
    )
    if category:
        query = query.where(MessageTemplate.category == category)

    items = session.exec(query).all()
    return templates.TemplateResponse(
        request,
        "message_templates/index.html",
        {
            "request": request,
            "current_user": current_user,
            "templates": items,
            "selected_category": category,
            "category_labels": CATEGORY_LABELS,
        },
    )


@router.get("/options", response_class=JSONResponse)
def get_template_options(
    category: Optional[str] = Query(default=None),
    scope: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """連絡帳返信・お知らせ作成モーダル用の定型文一覧JSON。"""
    ensure_default_templates(session)
    cat = category or scope
    query = select(MessageTemplate).where(MessageTemplate.is_active.is_(True)).order_by(
        col(MessageTemplate.display_order),
        col(MessageTemplate.id),
    )
    if cat:
        query = query.where(MessageTemplate.category == cat)

    items = session.exec(query).all()
    return [
        {
            "id": t.id,
            "category": t.category,
            "category_label": CATEGORY_LABELS.get(t.category, t.category),
            "title": t.title,
            "content": t.content,
        }
        for t in items
    ]


@router.post("")
def create_template(
    title: str = Form(...),
    content: str = Form(...),
    category: str = Form(default="daily_contact_reply"),
    display_order: int = Form(default=0),
    is_active: bool = Form(default=True),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """定型文テンプレートの新規登録。"""
    require_can_edit(current_user)
    t = MessageTemplate(
        category=category,
        title=title.strip(),
        content=content.strip(),
        display_order=display_order,
        is_active=is_active,
        created_at=utc_now(),
        updated_at=utc_now(),
    )
    session.add(t)
    session.commit()
    return RedirectResponse(url="/message-templates", status_code=303)


@router.post("/{template_id}/update")
def update_template(
    template_id: int,
    title: str = Form(...),
    content: str = Form(...),
    category: str = Form(default="daily_contact_reply"),
    display_order: int = Form(default=0),
    is_active: bool = Form(default=True),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """定型文テンプレートの更新。"""
    require_can_edit(current_user)
    t = session.get(MessageTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="定型文が見つかりません")
    t.title = title.strip()
    t.content = content.strip()
    t.category = category
    t.display_order = display_order
    t.is_active = is_active
    t.updated_at = utc_now()
    session.add(t)
    session.commit()
    return RedirectResponse(url="/message-templates", status_code=303)


@router.post("/{template_id}/delete")
def delete_template(
    template_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    """定型文テンプレートの削除。"""
    require_can_edit(current_user)
    t = session.get(MessageTemplate, template_id)
    if not t:
        raise HTTPException(status_code=404, detail="定型文が見つかりません")
    session.delete(t)
    session.commit()
    return RedirectResponse(url="/message-templates", status_code=303)
