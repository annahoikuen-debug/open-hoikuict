"""Lifespan起動スモークテスト。

アプリケーション全体のlifespan（startup / shutdown）と初期化処理が
例外なく起動し、主要ルートへリクエストできることを検証する。
"""
from __future__ import annotations

import os

os.environ.setdefault("HOIKUICT_ENV", "development")

from starlette.testclient import TestClient
from main import app


def test_lifespan_startup_and_smoke_get() -> None:
    with TestClient(app) as client:
        resp = client.get("/")
        # / はログインリダイレクト(302/303/307)または200を返す
        assert resp.status_code in (200, 302, 303, 307)
