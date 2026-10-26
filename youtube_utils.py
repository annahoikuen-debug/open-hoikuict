import re
from typing import Optional
from urllib.parse import parse_qs, urlparse


def extract_youtube_video_id(url_or_id: str) -> Optional[str]:
    """Extract YouTube video ID from various URL formats or raw ID.

    Supported formats:
    - https://www.youtube.com/watch?v=dQw4w9WgXcQ
    - https://m.youtube.com/watch?v=dQw4w9WgXcQ
    - https://youtu.be/dQw4w9WgXcQ
    - https://www.youtube.com/embed/dQw4w9WgXcQ
    - https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ
    - https://www.youtube.com/v/dQw4w9WgXcQ
    - https://www.youtube.com/shorts/dQw4w9WgXcQ
    - Raw 11-char ID (e.g., dQw4w9WgXcQ)
    """
    if not url_or_id:
        return None

    cleaned = url_or_id.strip()
    if not cleaned:
        return None

    # Direct 11-character ID check
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", cleaned):
        return cleaned

    parsed = urlparse(cleaned)
    hostname = (parsed.hostname or "").lower()

    # youtu.be/VIDEO_ID
    if "youtu.be" in hostname:
        path = parsed.path.strip("/")
        if path:
            video_id = path.split("/")[0]
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                return video_id

    # youtube.com or youtube-nocookie.com
    if "youtube" in hostname:
        # /watch?v=VIDEO_ID
        if parsed.path.startswith("/watch"):
            qs = parse_qs(parsed.query)
            v_list = qs.get("v")
            if v_list and v_list[0] and re.fullmatch(r"[A-Za-z0-9_-]{11}", v_list[0]):
                return v_list[0]

        # /embed/VIDEO_ID, /v/VIDEO_ID, /shorts/VIDEO_ID
        for prefix in ("/embed/", "/v/", "/shorts/"):
            if parsed.path.startswith(prefix):
                rest = parsed.path[len(prefix):]
                video_id = rest.split("/")[0].split("?")[0]
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
                    return video_id

    # Fallback regex search within the string
    match = re.search(r"(?:v=|\/embed\/|\/shorts\/|youtu\.be\/|\/v\/)([A-Za-z0-9_-]{11})", cleaned)
    if match:
        return match.group(1)

    return None
