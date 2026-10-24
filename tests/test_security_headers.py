"""HTTPセキュリティヘッダーMiddleware のリグレッション防止テスト。

任意のエンドポイント（HTML/JSON）へのGETレスポンスに、セキュリティヘッダーが
正しく付与されていることを検証する。
"""

from __future__ import annotations

import os

# 本番環境バリデーションを回避するため、テスト前には development 環境とする
os.environ.setdefault("HOIKUICT_ENV", "development")

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from security_headers import SecurityHeadersMiddleware


def _create_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/html")
    def html_page():
        return HTMLResponse(content="<html><body>test</body></html>")

    app.add_middleware(SecurityHeadersMiddleware)
    return app


def _get_headers(client: TestClient, path: str = "/healthz") -> dict[str, str]:
    response = client.get(path)
    return response.headers


def test_security_headers_x_frame_options_deny() -> None:
    """X-Frame-Options: DENY が付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert headers.get("x-frame-options") == "DENY"


def test_security_headers_x_content_type_options_nosniff() -> None:
    """X-Content-Type-Options: nosniff が付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert headers.get("x-content-type-options") == "nosniff"


def test_security_headers_x_xss_protection() -> None:
    """X-XSS-Protection: 1; mode=block が付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert headers.get("x-xss-protection") == "1; mode=block"


def test_security_headers_referrer_policy() -> None:
    """Referrer-Policy: strict-origin-when-cross-origin が付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_security_headers_content_security_policy() -> None:
    """Content-Security-Policy が付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        csp = headers.get("content-security-policy")
        assert csp is not None
        assert "default-src 'self'" in csp


def test_security_headers_no_hsts_in_development_http() -> None:
    """開発環境かつHTTP時は Strict-Transport-Security が付与されないこと。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert "strict-transport-security" not in headers


def test_security_headers_hsts_in_production_https(monkeypatch) -> None:
    """本番環境かつHTTPS時は Strict-Transport-Security が付与されること。"""
    monkeypatch.setenv("HOIKUICT_ENV", "production")
    # is_production() はモジュール読み込み時に評価されるため、再インポートする
    import importlib

    import security_headers

    importlib.reload(security_headers)

    from security_headers import SecurityHeadersMiddleware as ReloadedMiddleware

    app = FastAPI()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    app.add_middleware(ReloadedMiddleware)

    with TestClient(app, base_url="https://testserver") as client:
        headers = client.get("/healthz").headers
        assert headers.get("strict-transport-security") == "max-age=31536000; includeSubDomains"


def test_security_headers_websocket_bypasses_security_headers() -> None:
    """WebSocket エンドポイントはセキュリティヘッダーを付与しない（CSP等で通信阻害を防ぐ）。"""
    app = FastAPI()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("connected")
        await websocket.close()

    app.add_middleware(SecurityHeadersMiddleware)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            # WebSocket 接続が正常に確立し、メッセージを受信できること
            assert websocket.receive_text() == "connected"
