"""セキュリティヘッダー、レート制限、CSP の回帰防止テスト。

セキュリティヘッダー付与、CSP nonce、レート制限ブロック、
HSTS の本番/開発環境分岐を検証する。
"""

from __future__ import annotations

import os

os.environ.setdefault("HOIKUICT_ENV", "development")

from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from rate_limiter import RateLimiter, check_rate_limit, DEFAULT_RATE_LIMITER
from security_headers import SecurityHeadersMiddleware, build_csp_header


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


def _get_headers(client: TestClient, path: str = "/healthz"):
    response = client.get(path)
    return response.headers


# ---------------------------------------------------------------------------
# セキュリティヘッダー
# ---------------------------------------------------------------------------


def test_security_headers_x_frame_options_deny():
    """X-Frame-Options: DENY が付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert headers.get("x-frame-options") == "DENY"


def test_security_headers_x_content_type_options_nosniff():
    """X-Content-Type-Options: nosniff が付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert headers.get("x-content-type-options") == "nosniff"


def test_security_headers_x_xss_protection():
    """X-XSS-Protection: 1; mode=block が付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert headers.get("x-xss-protection") == "1; mode=block"


def test_security_headers_referrer_policy():
    """Referrer-Policy: strict-origin-when-cross-origin が付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"


def test_security_headers_content_security_policy():
    """Content-Security-Policy が付与され、default-src 'self' を含むこと。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        csp = headers.get("content-security-policy")
        assert csp is not None
        assert "default-src 'self'" in csp


def test_security_headers_no_hsts_in_development_http():
    """開発環境かつHTTP時は Strict-Transport-Security が付与されないこと。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client)
        assert "strict-transport-security" not in headers


def test_security_headers_hsts_in_production_https(monkeypatch):
    """本番環境かつHTTPS時は Strict-Transport-Security が付与されること。"""
    monkeypatch.setenv("HOIKUICT_ENV", "production")
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
        assert headers.get("strict-transport-security") == (
            "max-age=31536000; includeSubDomains"
        )


def test_security_headers_websocket_bypasses():
    """WebSocket エンドポイントはセキュリティヘッダーを付与しないこと。"""
    app = FastAPI()

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("connected")
        await websocket.close()

    app.add_middleware(SecurityHeadersMiddleware)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            assert websocket.receive_text() == "connected"


# ---------------------------------------------------------------------------
# CSP nonce
# ---------------------------------------------------------------------------


def test_build_csp_header_has_default_src_self():
    """CSP ヘッダーに default-src 'self' が含まれること。"""
    csp = build_csp_header()
    assert "default-src 'self'" in csp


def test_build_csp_header_with_nonce():
    """nonce 指定時に script-src に nonce が含まれること。"""
    csp = build_csp_header(nonce="abc123")
    assert "'nonce-abc123'" in csp


def test_build_csp_header_without_nonce():
    """nonce なしでは unsafe-inline が含まれること。"""
    csp = build_csp_header()
    assert "'unsafe-inline'" in csp
    assert "nonce-" not in csp


# ---------------------------------------------------------------------------
# レート制限
# ---------------------------------------------------------------------------


def test_rate_limit_allows_within_limit():
    """ウィンドウ内の許容回数以内のリクエストは通過すること。"""
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        allowed, retry_after = limiter.check("key")
        assert allowed is True
        assert retry_after is None


def test_rate_limit_rejects_over_limit():
    """許容回数を超えると拒否されること。"""
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    limiter.check("key")
    limiter.check("key")
    allowed, retry_after = limiter.check("key")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1


def test_rate_limit_separate_keys():
    """異なるキーは独立してカウントされること。"""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    assert limiter.check("key_a")[0] is True
    assert limiter.check("key_a")[0] is False
    assert limiter.check("key_b")[0] is True


def test_rate_limit_reset_allows_retry():
    """reset() でキー状態をクリアし再試行を許可すること。"""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    assert limiter.check("key")[0] is True
    assert limiter.check("key")[0] is False
    limiter.reset("key")
    assert limiter.check("key")[0] is True


def test_check_rate_limit_raises_429():
    """check_rate_limit は超過時に HTTP 429 を送出すること。"""
    from fastapi import HTTPException

    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.check("key-429")
    try:
        check_rate_limit(
            "key-429", max_requests=1, window_seconds=60, limiter=limiter
        )
        assert False, "HTTPException が送出されるべき"
    except HTTPException as exc:
        assert exc.status_code == 429


def test_default_limiter_singleton():
    """DEFAULT_RATE_LIMITER はデフォルト設定（1分間10回）であること。"""
    assert DEFAULT_RATE_LIMITER.max_requests == 10
    assert DEFAULT_RATE_LIMITER.window_seconds == 60
