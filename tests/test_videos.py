from datetime import date, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from csrf import CSRF_COOKIE_NAME, generate_csrf_token
from testing_helpers import authenticate_mock_staff, configure_test_environment

configure_test_environment()

from main import app
from models import (
    Child,
    Classroom,
    Family,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    Video,
    VideoStatus,
    VideoTargetType,
)
from time_utils import utc_now
from youtube_utils import extract_youtube_video_id


def test_extract_youtube_video_id():
    """Various YouTube URL formats parsing test."""
    # Standard watch URL
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    # With extra query params
    assert extract_youtube_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&feature=shared") == "dQw4w9WgXcQ"
    # Short URL
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_video_id("https://youtu.be/dQw4w9WgXcQ?t=10") == "dQw4w9WgXcQ"
    # Mobile URL
    assert extract_youtube_video_id("https://m.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    # Embed URLs
    assert extract_youtube_video_id("https://www.youtube.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_youtube_video_id("https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    # Raw 11-char ID
    assert extract_youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    # Shorts URL
    assert extract_youtube_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"

    # Invalid cases
    assert extract_youtube_video_id("") is None
    assert extract_youtube_video_id("   ") is None
    assert extract_youtube_video_id("https://example.com/not-youtube") is None
    assert extract_youtube_video_id("invalid-short-id") is None


def test_staff_video_crud_flow():
    """Staff can create, view, edit, and delete videos with CSRF protection."""
    client = TestClient(app)
    authenticate_mock_staff(client)

    token = generate_csrf_token()
    client.cookies.set(CSRF_COOKIE_NAME, token)

    # 1. View list
    resp = client.get("/videos")
    assert resp.status_code == 200
    assert "動画配信管理" in resp.text

    # 2. View new form
    resp = client.get("/videos/new")
    assert resp.status_code == 200
    assert "新規動画登録" in resp.text

    # 3. Create video (Validation error with invalid URL)
    resp = client.post(
        "/videos",
        data={
            "csrf_token": token,
            "title": "運動会動画",
            "youtube_url": "https://example.com/not-youtube",
            "target_type": "all",
            "status": "published",
        },
    )
    assert resp.status_code in (200, 422)
    assert "有効なYouTubeのURLまたは動画IDを入力してください" in resp.text

    # 4. Create video successfully
    resp = client.post(
        "/videos",
        data={
            "csrf_token": token,
            "title": "2026年度 運動会ハイライト",
            "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "description": "子どもたちのかけっこの様子です。",
            "target_type": "all",
            "status": "published",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    redirect_url = resp.headers["location"]
    assert redirect_url.startswith("/videos/")

    # 5. View detail
    detail_resp = client.get(redirect_url)
    assert detail_resp.status_code == 200
    assert "2026年度 運動会ハイライト" in detail_resp.text
    assert "youtube-nocookie.com/embed/dQw4w9WgXcQ" in detail_resp.text

    video_id = int(redirect_url.split("?")[0].split("/")[-1])

    # 6. Edit video
    edit_resp = client.post(
        f"/videos/{video_id}/edit",
        data={
            "csrf_token": token,
            "title": "2026年度 運動会ハイライト（更新版）",
            "youtube_url": "https://youtu.be/dQw4w9WgXcQ",
            "description": "更新された説明です。",
            "target_type": "all",
            "status": "published",
        },
        follow_redirects=True,
    )
    assert edit_resp.status_code == 200
    assert "2026年度 運動会ハイライト（更新版）" in edit_resp.text

    # 7. Delete video
    del_resp = client.post(
        f"/videos/{video_id}/delete",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert del_resp.status_code == 303
    assert del_resp.headers["location"] == "/videos?deleted=1"


def test_parent_portal_video_access_control():
    """Parent portal respects class restrictions and active expiry dates."""
    client = TestClient(app)
    from database import engine

    with Session(engine) as session:
        # Get or create classrooms
        c1 = session.exec(select(Classroom).where(Classroom.name == "ひよこ組")).first()
        if not c1:
            c1 = Classroom(name="ひよこ組", display_order=1)
            session.add(c1)
        c2 = session.exec(select(Classroom).where(Classroom.name == "うさぎ組")).first()
        if not c2:
            c2 = Classroom(name="うさぎ組", display_order=2)
            session.add(c2)
        session.commit()
        session.refresh(c1)
        session.refresh(c2)

        # Create family and child in c1
        family = Family(family_name="山田")
        session.add(family)
        session.commit()
        session.refresh(family)

        child = Child(
            first_name="太郎",
            last_name="山田",
            first_name_kana="タロウ",
            last_name_kana="ヤマダ",
            birth_date=date(2022, 4, 1),
            enrollment_date=date(2024, 4, 1),
            family_id=family.id,
            classroom_id=c1.id,
        )
        session.add(child)
        session.commit()
        session.refresh(child)

        # Create parent account linked to child
        parent = ParentAccount(
            display_name="山田花子",
            email=f"parent_test_{child.id}@example.com",
            status=ParentAccountStatus.active,
        )
        session.add(parent)
        session.commit()
        session.refresh(parent)

        link = ParentChildLink(parent_account_id=parent.id, child_id=child.id)
        session.add(link)
        session.commit()

        # Create videos:
        # 1. Global video (all)
        v_all = Video(
            title="全体向け動画",
            youtube_url="https://youtu.be/vid00000001",
            youtube_video_id="vid00000001",
            target_type=VideoTargetType.all,
            status=VideoStatus.published,
            published_at=utc_now() - timedelta(days=1),
        )
        # 2. C1 only video (matches parent's child)
        v_c1 = Video(
            title="ひよこ組限定動画",
            youtube_url="https://youtu.be/vid00000002",
            youtube_video_id="vid00000002",
            target_type=VideoTargetType.classroom,
            target_classroom_id=c1.id,
            status=VideoStatus.published,
            published_at=utc_now() - timedelta(days=1),
        )
        # 3. C2 only video (does NOT match parent's child)
        v_c2 = Video(
            title="うさぎ組限定動画",
            youtube_url="https://youtu.be/vid00000003",
            youtube_video_id="vid00000003",
            target_type=VideoTargetType.classroom,
            target_classroom_id=c2.id,
            status=VideoStatus.published,
            published_at=utc_now() - timedelta(days=1),
        )
        # 4. Draft video
        v_draft = Video(
            title="下書き動画",
            youtube_url="https://youtu.be/vid00000004",
            youtube_video_id="vid00000004",
            target_type=VideoTargetType.all,
            status=VideoStatus.draft,
        )
        # 5. Expired video
        v_expired = Video(
            title="期限切れ動画",
            youtube_url="https://youtu.be/vid00000005",
            youtube_video_id="vid00000005",
            target_type=VideoTargetType.all,
            status=VideoStatus.published,
            published_at=utc_now() - timedelta(days=5),
            expires_at=utc_now() - timedelta(days=1),
        )

        session.add_all([v_all, v_c1, v_c2, v_draft, v_expired])
        session.commit()
        session.refresh(v_all)
        session.refresh(v_c1)
        session.refresh(v_c2)
        session.refresh(v_draft)
        session.refresh(v_expired)

        parent_id = parent.id
        v_all_id = v_all.id
        v_c1_id = v_c1.id
        v_c2_id = v_c2.id
        v_draft_id = v_draft.id
        v_expired_id = v_expired.id

    # Login as parent
    from auth import MOCK_PARENT_ACCOUNT_COOKIE

    client.cookies.set(MOCK_PARENT_ACCOUNT_COOKIE, str(parent_id))

    # Test parent portal video list
    list_resp = client.get("/parent-portal/videos")
    assert list_resp.status_code == 200
    assert "全体向け動画" in list_resp.text
    assert "ひよこ組限定動画" in list_resp.text
    # Should NOT see C2 only, draft, or expired
    assert "うさぎ組限定動画" not in list_resp.text
    assert "下書き動画" not in list_resp.text
    assert "期限切れ動画" not in list_resp.text

    # Test video detail access
    # Accessible: All
    r1 = client.get(f"/parent-portal/videos/{v_all_id}")
    assert r1.status_code == 200
    assert "全体向け動画" in r1.text

    # Accessible: C1
    r2 = client.get(f"/parent-portal/videos/{v_c1_id}")
    assert r2.status_code == 200
    assert "ひよこ組限定動画" in r2.text

    # Inaccessible: C2 (403 forbidden)
    r3 = client.get(f"/parent-portal/videos/{v_c2_id}")
    assert r3.status_code == 403

    # Inaccessible: Expired (404 not found)
    r4 = client.get(f"/parent-portal/videos/{v_expired_id}")
    assert r4.status_code == 404

    # Inaccessible: Draft (404 not found)
    r5 = client.get(f"/parent-portal/videos/{v_draft_id}")
    assert r5.status_code == 404


def test_videos_pagination_and_oembed_preview():
    """Test pagination parameters and oEmbed preview endpoint."""
    client = TestClient(app)
    authenticate_mock_staff(client)

    # 1. Test pagination on staff videos list
    resp = client.get("/videos?page=1&per_page=5")
    assert resp.status_code == 200

    # 2. Test pagination with invalid query parameter returns 422
    resp_inv = client.get("/videos?page=-1&per_page=0")
    assert resp_inv.status_code == 422

    # 3. Test oEmbed preview endpoint with missing/invalid URL
    resp_empty = client.get("/videos/oembed-preview")
    assert resp_empty.status_code == 422

    resp_invalid = client.get("/videos/oembed-preview?url=https://example.com/not-youtube")
    assert resp_invalid.status_code == 400


def test_storage_driver_abstraction(tmp_path):
    """Test LocalFileSystemStorageDriver basic file operations."""
    from storage_driver import LocalFileSystemStorageDriver

    driver = LocalFileSystemStorageDriver(base_dir=str(tmp_path))
    test_rel = "media/sample.txt"
    test_bytes = b"Hello OpenICT Storage Driver"

    # Save returns bytes written
    bytes_written = driver.save(test_rel, test_bytes)
    assert bytes_written == len(test_bytes)
    assert driver.exists(test_rel) is True

    local_path = driver.get_local_path(test_rel)
    assert local_path.is_file()
    assert local_path.name == "sample.txt"

    # Read
    read_bytes = driver.read(test_rel)
    assert read_bytes == test_bytes

    # Delete
    assert driver.delete(test_rel) is True
    assert driver.exists(test_rel) is False
    assert driver.delete(test_rel) is False

