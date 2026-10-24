"""クライアントIP安全取得およびレートリミッター・マルチワーカー検証テスト。"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from rate_limiter import RateLimiter, client_ip
from security_config import validate_runtime_security


def _dummy_request(client_host: str = "127.0.0.1", headers: dict[str, str] | None = None) -> Request:
    raw_headers = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))
    scope = {
        "type": "http",
        "client": (client_host, 12345),
        "headers": raw_headers,
    }
    return Request(scope)


def test_client_ip_direct_connection():
    """プロキシを経由しない直接接続の場合、client.host が返ること。"""
    req = _dummy_request("192.168.1.100")
    assert client_ip(req) == "192.168.1.100"


def test_client_ip_spoofed_header_from_untrusted_host(monkeypatch):
    """信頼できないホストから偽造された X-Forwarded-For が送信されても、直接の接続元IPを返すこと。"""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.1")
    req = _dummy_request("203.0.113.195", {"X-Forwarded-For": "1.1.1.1"})
    assert client_ip(req) == "203.0.113.195"


def test_client_ip_trusted_proxy_single_ip(monkeypatch):
    """信頼できるプロキシ（10.0.0.1）からのリクエストの場合、X-Forwarded-For のIPを採用すること。"""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.1")
    req = _dummy_request("10.0.0.1", {"X-Forwarded-For": "203.0.113.50"})
    assert client_ip(req) == "203.0.113.50"


def test_client_ip_trusted_proxy_multiple_hops(monkeypatch):
    """多段プロキシの場合、右から走査して最初の非信頼IP（クライアント実IP）を採用すること。"""
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.1, 10.0.0.2")
    # クライアント(203.0.113.5) -> プロキシ1(10.0.0.2) -> プロキシ2(10.0.0.1) -> アプリ
    req = _dummy_request("10.0.0.1", {"X-Forwarded-For": "203.0.113.5, 10.0.0.2"})
    assert client_ip(req) == "203.0.113.5"


def test_rate_limiter_empty_keys_cleanup():
    """有効期限が切れたキーが _timestamps 辞書から自動削除されること。"""
    limiter = RateLimiter(max_requests=2, window_seconds=10)
    simulated_now = 1000.0
    limiter._now = lambda: simulated_now

    limiter.check("key1")
    assert "key1" in limiter._timestamps

    # 15秒進める（ウィンドウ経過）
    simulated_now = 1015.0
    # 次の別キーの check または sweep で key1 が消えること
    limiter.sweep()
    assert "key1" not in limiter._timestamps


def test_production_multiworker_validation_fails(monkeypatch):
    """本番環境かつマルチワーカー（WEB_CONCURRENCY > 1）の場合、例外を送出すること。"""
    monkeypatch.setenv("HOIKUICT_ENV", "production")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    # 他の必須項目をモックして validate_runtime_security を実行
    monkeypatch.setenv("HOIKUICT_SECRET_KEY", "a" * 32)
    monkeypatch.setenv("HOIKUICT_STAFF_AUTH_MODE", "local_password")
    monkeypatch.setenv("HOIKUICT_PARENT_AUTH_MODE", "local_password")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
    monkeypatch.setenv("HOIKUICT_COOKIE_SECURE", "1")
    monkeypatch.setenv("HOIKUICT_CSRF_ENFORCE", "1")
    monkeypatch.setenv("HOIKUICT_LOGIN_THROTTLE_HMAC_KEY", "b" * 32)

    with pytest.raises(RuntimeError) as exc_info:
        validate_runtime_security()
    assert "単一ワーカーのみ許可されます" in str(exc_info.value)


def test_production_multiworker_validation_allows_with_flag(monkeypatch):
    """HOIKUICT_ALLOW_MULTIWORKER_RATE_LIMIT=1 の場合はマルチワーカーでもエラーにならないこと。"""
    monkeypatch.setenv("HOIKUICT_ENV", "production")
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    monkeypatch.setenv("HOIKUICT_ALLOW_MULTIWORKER_RATE_LIMIT", "1")
    # validate_runtime_security 内でマルチワーカーのエラーメッセージが出ないこと
    # (他の設定エラーが出る可能性はあるが、マルチワーカーエラーでないことを確認)
    try:
        validate_runtime_security()
    except RuntimeError as exc:
        assert "単一ワーカーのみ許可されます" not in str(exc)
