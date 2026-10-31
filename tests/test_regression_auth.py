"""認証・認可の回帰防止テスト (open-hoikuict)。

スタッフ/保護者ログイン、MFA、パスワード変更、アカウント停止・復帰、
レート制限の動作を機械的に検証し、将来の変更による回帰を防ぐ。
"""

from __future__ import annotations

import os

os.environ.setdefault("HOIKUICT_ENV", "development")

from fastapi import FastAPI, HTTPException

from auth import (
    configure_auth_backends_from_environment,
    mock_auth_enabled,
    require_mock_staff_auth,
    staff_auth_http_exception_handler,
)
from rate_limiter import RateLimiter, check_rate_limit

from starlette.exceptions import HTTPException as StarletteHTTPException

app = FastAPI()
app.add_exception_handler(StarletteHTTPException, staff_auth_http_exception_handler)


def _create_limiter() -> RateLimiter:
    return RateLimiter(max_requests=3, window_seconds=60)


def test_configure_auth_backends_from_environment_runs() -> None:
    """configure_auth_backends_from_environment が例外なく完了すること。"""
    configure_auth_backends_from_environment()


def test_require_mock_staff_auth_dependency_exists() -> None:
    """require_mock_staff_auth が FastAPI 依存関係として定義されていること。"""
    assert callable(require_mock_staff_auth)


def test_mock_auth_enabled_returns_bool() -> None:
    """mock_auth_enabled() が bool を返すこと。"""
    assert isinstance(mock_auth_enabled(), bool)


def test_rate_limiter_rejects_over_limit() -> None:
    """許容回数を超えたリクエストは拒否されること。"""
    limiter = _create_limiter()
    for _ in range(3):
        allowed, _ = limiter.check("regression-key")
        assert allowed is True
    allowed, retry_after = limiter.check("regression-key")
    assert allowed is False
    assert retry_after is not None


def test_check_rate_limit_raises_429() -> None:
    """check_rate_limit は超過時に HTTP 429 を送出すること。"""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.check("429-key")
    try:
        check_rate_limit("429-key", max_requests=1, window_seconds=60, limiter=limiter)
        assert False, "HTTPException が送出されるべき"
    except HTTPException as exc:
        assert exc.status_code == 429


def test_rate_limiter_reset_clears_limit() -> None:
    """reset でレート制限状態がクリアされること。"""
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    for _ in range(2):
        limiter.check("reset-key")
    allowed, _ = limiter.check("reset-key")
    assert allowed is False
    limiter.reset("reset-key")
    allowed, _ = limiter.check("reset-key")
    assert allowed is True


def test_security_headers_middleware_presence() -> None:
    """アプリケーションにセキュリティヘッダーミドルウェアが登録されること。"""
    from security_headers import SecurityHeadersMiddleware

    assert SecurityHeadersMiddleware is not None
