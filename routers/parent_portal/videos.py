"""Parent portal video streaming routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from database import get_session
from models import Video, VideoStatus, VideoTargetType
from time_utils import utc_now

router = APIRouter()


@router.get("/videos", response_class=HTMLResponse)
def parent_videos_list(
    request: Request,
    page: int = Query(1, ge=1),
    per_page: int = Query(9, ge=1, le=50),
    session: Session = Depends(get_session),
):
    from routers.parent_portal import _classroom_ids, _get_parent_account, templates

    current_parent_user = _get_parent_account(request, session)
    if not current_parent_user:
        return RedirectResponse(url="/parent-portal/login", status_code=303)

    classroom_ids = _classroom_ids(current_parent_user)
    now = utc_now()

    videos = session.exec(
        select(Video)
        .options(selectinload(Video.target_classroom))
        .where(Video.status == VideoStatus.published)
        .order_by(Video.published_at.desc())
    ).all()

    accessible_videos = []
    for video in videos:
        if not video.is_currently_active(now):
            continue
        if video.target_type == VideoTargetType.all:
            accessible_videos.append(video)
        elif video.target_type == VideoTargetType.classroom and video.target_classroom_id in classroom_ids:
            accessible_videos.append(video)

    total_count = len(accessible_videos)
    total_pages = max(1, (total_count + per_page - 1) // per_page)
    offset = (page - 1) * per_page
    paged_videos = accessible_videos[offset : offset + per_page]

    return templates.TemplateResponse(
        request,
        "parent_portal/videos.html",
        {
            "request": request,
            "current_parent_user": current_parent_user,
            "videos": paged_videos,
            "total_count": total_count,
            "page": page,
            "total_pages": total_pages,
            "per_page": per_page,
            "now": now,
        },
    )


@router.get("/videos/{video_id}", response_class=HTMLResponse)
def parent_video_detail(
    video_id: int,
    request: Request,
    session: Session = Depends(get_session),
):
    from routers.parent_portal import _classroom_ids, _get_parent_account, templates

    current_parent_user = _get_parent_account(request, session)
    if not current_parent_user:
        return RedirectResponse(url="/parent-portal/login", status_code=303)

    video = session.get(Video, video_id)
    if not video:
        raise HTTPException(status_code=404, detail="指定された動画が見つかりません。")

    now = utc_now()
    if not video.is_currently_active(now):
        raise HTTPException(status_code=404, detail="この動画は現在公開されていません。")

    classroom_ids = _classroom_ids(current_parent_user)
    if video.target_type == VideoTargetType.classroom and video.target_classroom_id not in classroom_ids:
        raise HTTPException(status_code=403, detail="この動画はお子様のクラス向けに限定公開されています。")

    return templates.TemplateResponse(
        request,
        "parent_portal/video_detail.html",
        {
            "request": request,
            "current_parent_user": current_parent_user,
            "video": video,
            "now": now,
        },
    )
