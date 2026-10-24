import os

os.environ.setdefault("HOIKUICT_ENV", "development")
os.environ.setdefault("HOIKUICT_ENABLE_MOCK_AUTH", "1")
os.environ.setdefault("HOIKUICT_KIOSK_ACCESS_MODE", "open")

from fastapi.testclient import TestClient

from main import app
from version import __version__


def test_app_version_matches_module():
    """FastAPI インスタンスの version が version.__version__ (0.4.0) と一致すること。"""
    assert app.version == __version__
    assert app.version == "0.4.0"


def test_healthz_includes_version():
    """/healthz エンドポイントがバージョン情報を含むこと。"""
    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("status") == "ok"
        assert data.get("version") == "0.4.0"
