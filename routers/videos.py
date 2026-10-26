from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import get_current_staff_user, require_can_edit
from database import get_session
from models import Classroom, Video, VideoStatus, VideoTargetType
from template_utils import create_templates
from time_utils import ensure_utc_from_local, utc_now
from youtube_utils import extract_youtube_video_id

router = APIRouter(prefix="/videos", tags=["videos"])
templates = create_templates()


def _parse_datetime_input(dt_str: Optional[str]) -> Optional[datetime]:
    if not dt_str or not dt_str.strip():
        return None
    try:
        # Expected format from <input type="datetime-local">: YYYY-MM-DDTHH:MM
        local_dt = datetime.fromisoformat(dt_str.strip())
        return ensure_utc_from_local(local_dt)
    except (ValueError, TypeError):
        return None


@router.get("", response_class=HTMLResponse)
def list_videos(
    request: Request,
    status: Optional[str] = Query(None),
    classroom_id: Optional[int] = Query(None),
    session: Session = Depends(get_session),
    staff_user=Depends(get_current_staff_user),
):
    query = select(Video).order_by(Video.published_at.desc())

    if status and status in VideoStatus.__members__:
        query = query.where(Video.status == VideoStatus(status))
    if classroom_id:
        query = query.where(Video.target_classroom_id == classroom_id)

    videos = session.exec(query).all()
    classrooms = session.exec(select(Classroom).order_by(Classroom.id)).all()

    # Pre-calculate active counts
    now = utc_now()
    active_count = sum(1 for v in videos if v.is_currently_active(now))
    draft_count = sum(1 for v in videos if v.status == VideoStatus.draft)

    return templates.TemplateResponse(
        request,
        "videos/list.html",
        {
            "request": request,
            "videos": videos,
            "classrooms": classrooms,
            "selected_status": status,
            "selected_classroom_id": classroom_id,
            "active_count": active_count,
            "draft_count": draft_count,
            "total_count": len(videos),
            "now": now,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_video_form(
    request: Request,
    session: Session = Depends(get_session),
    staff_user=Depends(require_can_edit),
):
    classrooms = session.exec(select(Classroom).order_by(Classroom.id)).all()
    return templates.TemplateResponse(
        request,
        "videos/form.html",
        {
            "request": request,
            "video": None,
            "classrooms": classrooms,
            "errors": [],
        },
    )


@router.post("", response_class=HTMLResponse)
def create_video(
    request: Request,
    title: str = Form(...),
    youtube_url: str = Form(...),
    description: Optional[str] = Form(None),
    target_type: str = Form("all"),
    target_classroom_id: Optional[int] = Form(None),
    status: str = Form("published"),
    published_at: Optional[str] = Form(None),
    expires_at: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    staff_user=Depends(require_can_edit),
):
    errors = []
    title = title.strip()
    if not title:
        errors.append("タイトルを入力してください。")

    video_id = extract_youtube_video_id(youtube_url)
    if not video_id:
        errors.append("有効なYouTubeのURLまたは動画IDを入力してください（例: https://www.youtube.com/watch?v=... または https://youtu.be/...）。")

    target_enum = VideoTargetType(target_type) if target_type in VideoTargetType.__members__ else VideoTargetType.all
    if target_enum == VideoTargetType.classroom and not target_classroom_id:
        errors.append("対象クラスを選択してください。")

    status_enum = VideoStatus(status) if status in VideoStatus.__members__ else VideoStatus.published

    parsed_published_at = _parse_datetime_input(published_at) or utc_now()
    parsed_expires_at = _parse_datetime_input(expires_at)

    if parsed_expires_at and parsed_expires_at <= parsed_published_at:
        errors.append("公開期限（終了日時）は公開開始日時より後に設定してください。")

    if errors:
        classrooms = session.exec(select(Classroom).order_by(Classroom.id)).all()
        return templates.TemplateResponse(
            request,
            "videos/form.html",
            {
                "request": request,
                "video": {
                    "title": title,
                    "youtube_url": youtube_url,
                    "description": description,
                    "target_type": target_enum,
                    "target_classroom_id": target_classroom_id,
                    "status": status_enum,
                },
                "classrooms": classrooms,
                "errors": errors,
            },
            status_code=422,
        )

    now = utc_now()
    video = Video(
        title=title,
        description=description.strip() if description else None,
        youtube_url=youtube_url.strip(),
        youtube_video_id=video_id,
        target_type=target_enum,
        target_classroom_id=target_classroom_id if target_enum == VideoTargetType.classroom else None,
        status=status_enum,
        published_at=parsed_published_at,
        expires_at=parsed_expires_at,
        created_by_staff_id=getattr(staff_user, "staff_id", None) or getattr(staff_user, "name", None),
        created_at=now,
        updated_at=now,
    )
    session.add(video)
    session.commit()
    session.refresh(video)

    return RedirectResponse(url=f"/videos/{video.id}?created=1", status_code=303)


@router.get("/{video_id}", response_class=HTMLResponse)
def view_video(
    video_id: int,
    request: Request,
    created: Optional[int] = Query(None),
    updated: Optional[int] = Query(None),
    session: Session = Depends(get_session),
    staff_user=Depends(get_current_staff_user),
):
    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="指定された動画が見つかりません。")

    return templates.TemplateResponse(
        request,
        "videos/detail.html",
        {
            "request": request,
            "video": video,
            "created": bool(created),
            "updated": bool(updated),
            "now": utc_now(),
        },
    )


@router.get("/{video_id}/edit", response_class=HTMLResponse)
def edit_video_form(
    video_id: int,
    request: Request,
    session: Session = Depends(get_session),
    staff_user=Depends(require_can_edit),
):
    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="指定された動画が見つかりません。")

    classrooms = session.exec(select(Classroom).order_by(Classroom.id)).all()
    return templates.TemplateResponse(
        request,
        "videos/form.html",
        {
            "request": request,
            "video": video,
            "classrooms": classrooms,
            "errors": [],
        },
    )


@router.post("/{video_id}/edit", response_class=HTMLResponse)
def update_video(
    video_id: int,
    request: Request,
    title: str = Form(...),
    youtube_url: str = Form(...),
    description: Optional[str] = Form(None),
    target_type: str = Form("all"),
    target_classroom_id: Optional[int] = Form(None),
    status: str = Form("published"),
    published_at: Optional[str] = Form(None),
    expires_at: Optional[str] = Form(None),
    session: Session = Depends(get_session),
    staff_user=Depends(require_can_edit),
):
    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="指定された動画が見つかりません。")

    errors = []
    title = title.strip()
    if not title:
        errors.append("タイトルを入力してください。")

    new_video_id = extract_youtube_video_id(youtube_url)
    if not new_video_id:
        errors.append("有効なYouTubeのURLまたは動画IDを入力してください。")

    target_enum = VideoTargetType(target_type) if target_type in VideoTargetType.__members__ else VideoTargetType.all
    if target_enum == VideoTargetType.classroom and not target_classroom_id:
        errors.append("対象クラスを選択してください。")

    status_enum = VideoStatus(status) if status in VideoStatus.__members__ else VideoStatus.published

    parsed_published_at = _parse_datetime_input(published_at) or video.published_at
    parsed_expires_at = _parse_datetime_input(expires_at)

    if parsed_expires_at and parsed_expires_at <= parsed_published_at:
        errors.append("公開期限（終了日時）は公開開始日時より後に設定してください。")

    if errors:
        classrooms = session.exec(select(Classroom).order_by(Classroom.id)).all()
        return templates.TemplateResponse(
            request,
            "videos/form.html",
            {
                "request": request,
                "video": video,
                "classrooms": classrooms,
                "errors": errors,
            },
            status_code=422,
        )

    video.title = title
    video.description = description.strip() if description else None
    video.youtube_url = youtube_url.strip()
    video.youtube_video_id = new_video_id
    video.target_type = target_enum
    video.target_classroom_id = target_classroom_id if target_enum == VideoTargetType.classroom else None
    video.status = status_enum
    video.published_at = parsed_published_at
    video.expires_at = parsed_expires_at
    video.updated_at = utc_now()

    session.add(video)
    session.commit()

    return RedirectResponse(url=f"/videos/{video.id}?updated=1", status_code=303)


@router.post("/{video_id}/delete")
def delete_video(
    video_id: int,
    session: Session = Depends(get_session),
    staff_user=Depends(require_can_edit),
):
    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="指定された動画が見つかりません。")

    session.delete(video)
    session.commit()
    return RedirectResponse(url="/videos?deleted=1", status_code=303)
