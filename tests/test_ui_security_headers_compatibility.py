"""セキュリティヘッダー回帰テスト＋既存UI互換検証。

新規ヘッダー付与によって既存の静的アセット（CSS、インラインスクリプト、
SVGアイコン、Chart.js等のグラフ）がCSP違反で破損しないことを検証する。
"""

from __future__ import annotations

import os

# 本番環境バリデーションを回避するため、テスト前には development 環境とする
os.environ.setdefault("HOIKUICT_ENV", "development")

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from security_headers import SecurityHeadersMiddleware


def _create_test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    @app.get("/staff/portal", response_class=HTMLResponse)
    def staff_portal():
        return HTMLResponse(
            content=(
                "<!DOCTYPE html><html><head>"
                "<style>body { color: #333; }</style>"
                "<script>console.log('portal');</script>"
                "</head><body>Staff Portal</body></html>"
            )
        )

    @app.get("/children", response_class=HTMLResponse)
    def children():
        return HTMLResponse(
            content=(
                "<!DOCTYPE html><html><head>"
                '<link rel="stylesheet" href="/static/css/style.css">'
                '<script src="/static/js/chart.js"></script>'
                "</head><body>Children</body></html>"
            )
        )

    @app.get("/shifts/plans", response_class=HTMLResponse)
    def shifts_plans():
        return HTMLResponse(
            content=(
                "<!DOCTYPE html><html><head>"
                '<link rel="stylesheet" href="/static/css/plans.css">'
                '<script src="/static/js/plans.js"></script>'
                "</head><body>Shift Plans</body></html>"
            )
        )

    @app.get("/parent-portal", response_class=HTMLResponse)
    def parent_portal():
        return HTMLResponse(
            content=(
                "<!DOCTYPE html><html><head>"
                '<style>body { margin: 0; }</style>'
                "<script>document.title = 'Parent Portal';</script>"
                "</head><body>Parent Portal</body></html>"
            )
        )

    app.add_middleware(SecurityHeadersMiddleware)
    return app


def _get_headers(client: TestClient, path: str = "/healthz") -> dict[str, str]:
    response = client.get(path)
    return response.headers


def test_ui_security_headers_all_present() -> None:
    """主要ページにすべてのセキュリティヘッダーが付与されること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client, "/healthz")
        assert headers.get("x-frame-options") == "DENY"
        assert headers.get("x-content-type-options") == "nosniff"
        assert headers.get("x-xss-protection") == "1; mode=block"
        assert headers.get("referrer-policy") == "strict-origin-when-cross-origin"
        csp = headers.get("content-security-policy")
        assert csp is not None
        assert "default-src 'self'" in csp


def test_ui_security_headers_csp_allows_unsafe_inline() -> None:
    """CSPがインラインスクリプト・スタイルのため'unsafe-inline'を許容すること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client, "/staff/portal")
        csp = headers.get("content-security-policy")
        assert csp is not None
        assert "'unsafe-inline'" in csp


def test_ui_security_headers_csp_allows_data_uri_images() -> None:
    """CSPがデータURI画像（data:）を許容すること。"""
    app = _create_test_app()
    with TestClient(app) as client:
        headers = _get_headers(client, "/children")
        csp = headers.get("content-security-policy")
        assert csp is not None
        assert "data:" in csp


def test_ui_security_headers_html_response_unchanged() -> None:
    """セキュリティヘッダー付与後もHTMLレスポンスボディが破損しないこと。"""
    app = _create_test_app()
    with TestClient(app) as client:
        response = client.get("/staff/portal")
        assert response.status_code == 200
        body = response.text
        assert "Staff Portal" in body
        assert "<style>" in body
        assert "<script>" in body


def test_ui_security_headers_all_pages_consistent() -> None:
    """すべての主要ページでセキュリティヘッダーが一貫して付与されること。"""
    app = _create_test_app()
    paths = [
        "/healthz",
        "/staff/portal",
        "/children",
        "/shifts/plans",
        "/parent-portal",
    ]
    with TestClient(app) as client:
        for path in paths:
            headers = client.get(path).headers
            assert headers.get("x-frame-options") == "DENY", f"Failed for {path}"
            assert headers.get("x-content-type-options") == "nosniff", f"Failed for {path}"
            csp = headers.get("content-security-policy")
            assert csp is not None, f"No CSP for {path}"
            assert "default-src 'self'" in csp, f"No default-src 'self' for {path}"
