"""rate_limiter.py のリグレッション防止テスト。"""

from __future__ import annotations

from rate_limiter import RateLimiter, check_rate_limit, DEFAULT_RATE_LIMITER


def _make_limiter(max_requests: int = 3, window_seconds: int = 1) -> RateLimiter:
    return RateLimiter(max_requests=max_requests, window_seconds=window_seconds)


def test_allow_requests_within_limit() -> None:
    """ウィンドウ内の許容回数以内のリクエストは正常に通過する。"""
    limiter = _make_limiter(max_requests=3, window_seconds=60)
    for _ in range(3):
        allowed, retry_after = limiter.check("test-key")
        assert allowed is True
        assert retry_after is None


def test_reject_requests_over_limit() -> None:
    """許容回数を超えた場合に拒否される。"""
    limiter = _make_limiter(max_requests=2, window_seconds=60)
    limiter.check("test-key")
    limiter.check("test-key")
    allowed, retry_after = limiter.check("test-key")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1


def test_window_expiry_allows_requests_again() -> None:
    """ウィンドウ時間経過後に再びリクエスト可能になる。"""
    limiter = _make_limiter(max_requests=1, window_seconds=0)  # 0秒で即座に期限切れ
    limiter.check("test-key")
    # ウィンドウが0秒なので、次回チェック時には期限切れクリーンアップされ再許可
    allowed, retry_after = limiter.check("test-key")
    assert allowed is True


def test_check_rate_limit_raises_429() -> None:
    """check_rate_limit は超過時に HTTP 429 を送出する。"""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.check("key-429")
    try:
        check_rate_limit("key-429", max_requests=1, window_seconds=60, limiter=limiter)
        assert False, "HTTPException が送出されるべき"
    except Exception as exc:  # noqa: BLE001 - FastAPI HTTPException をキャッチ
        from fastapi import HTTPException

        assert isinstance(exc, HTTPException)
        assert exc.status_code == 429


def test_reset_clears_rate_limit() -> None:
    """reset でキーのレート制限状態をリセットできる。"""
    limiter = _make_limiter(max_requests=1, window_seconds=60)
    limiter.check("reset-key")
    allowed, _ = limiter.check("reset-key")
    assert allowed is False
    limiter.reset("reset-key")
    allowed, _ = limiter.check("reset-key")
    assert allowed is True


def test_get_remaining() -> None:
    """残り許容リクエスト数を取得できる。"""
    limiter = _make_limiter(max_requests=3, window_seconds=60)
    assert limiter.get_remaining("rem-key") == 3
    limiter.check("rem-key")
    assert limiter.get_remaining("rem-key") == 2


def test_default_limiter_is_singleton() -> None:
    """DEFAULT_RATE_LIMITER はデフォルトの1分間10回設定である。"""
    assert DEFAULT_RATE_LIMITER.max_requests == 10
    assert DEFAULT_RATE_LIMITER.window_seconds == 60
