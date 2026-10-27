"""HTTPセキュリティヘッダーMiddleware。

ブラウザ側でのクリックジャッキング、XSS、MIMEタイプスニッフィング、
通信盗聴を遮断するセキュリティヘッダーを全レスポンスに一括注入する。

Starlette BaseHTTPMiddleware を継承し、すべてのレスポンスに対して
以下のヘッダーを付与する。

- X-Frame-Options: DENY（iframe埋め込みによるクリックジャッキング完全防止）
- X-Content-Type-Options: nosniff（Content-Type誤認実行防止）
- X-XSS-Protection: 1; mode=block
- Referrer-Policy: strict-origin-when-cross-origin
- Strict-Transport-Security: max-age=31536000; includeSubDomains
    （本番環境かつHTTPS時のみ）
- Content-Security-Policy: default-src 'self'（デフォルト同一オリジンのみ許可）
"""

import secrets
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from security_config import is_production


def build_csp_header(nonce: str | None = None) -> str:
    """CSPヘッダー文字列を生成する。nonce が指定されている場合は script-src に追加する。"""
    script_src = f"'self' 'unsafe-inline' 'nonce-{nonce}'" if nonce else "'self' 'unsafe-inline'"
    return (
        "default-src 'self'; "
        f"script-src {script_src}; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: https://img.youtube.com https://i.ytimg.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "frame-src 'self' https://www.youtube-nocookie.com https://www.youtube.com; "
        "connect-src 'self';"
    )


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """全レスポンスにセキュリティヘッダーを付与するMiddleware。"""

    # 常に付与するヘッダー
    _BASE_HEADERS: dict[str, str] = {
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "X-XSS-Protection": "1; mode=block",
        "Referrer-Policy": "strict-origin-when-cross-origin",
    }

    # 本番環境かつHTTPS時のみ付与するヘッダー
    _HSTS_HEADER = "Strict-Transport-Security: max-age=31536000; includeSubDomains"

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next) -> Response:
        # リクエストスコープに安全な CSP nonce を生成
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce

        response = await call_next(request)

        # WebSocket Upgrade（scope["type"] == "websocket"）はBaseHTTPMiddlewareが
        # HTTPリクエストのみdispatchするため到達しない。明示的にガードする。
        if request.scope.get("type") != "http":
            return response

        # StarletteのResponse.headersはイミュータブルなコピーを返すため、
        # 生のraw_headersを直接MutableHeadersでラップして書き換える
        mutable_headers = MutableHeaders(raw=response.raw_headers)

        for key, value in self._BASE_HEADERS.items():
            mutable_headers[key] = value

        # 動的 Nonce を付与した CSP をセット
        mutable_headers["Content-Security-Policy"] = build_csp_header(nonce)

        # HSTS: 本番環境かつHTTPS時のみ（開発環境ではlocalhost HTTPS強制事故防止のため付与しない）
        if is_production() and request.url.scheme == "https":
            mutable_headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response
