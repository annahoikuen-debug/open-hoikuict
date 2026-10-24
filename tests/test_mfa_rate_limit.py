"""MFA OTP送信・検証エンドポイントのレート制限リグレッション防止テスト。"""

from __future__ import annotations

from rate_limiter import RateLimiter


def test_mfa_send_code_rate_limit_blocks_after_limit() -> None:
    """MFA OTP送信レート制限: アカウント単位で1時間に最大5回まで許可。"""
    limiter = RateLimiter(max_requests=5, window_seconds=3600)

    # 5回まで許可
    for _ in range(5):
        allowed, _ = limiter.check("mfa_send:user1")
        assert allowed is True

    # 6回目で拒否
    allowed, retry_after = limiter.check("mfa_send:user1")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1


def test_mfa_send_code_rate_limit_retry_after_header() -> None:
    """MFA OTP送信レート制限: 拒否時に Retry-After 秒数が返される。"""
    limiter = RateLimiter(max_requests=1, window_seconds=3600)
    limiter.check("key")
    allowed, retry_after = limiter.check("key")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1


def test_mfa_send_code_rate_limit_separate_accounts() -> None:
    """MFA OTP送信レート制限: 異なるアカウントは独立してカウントされる。"""
    limiter = RateLimiter(max_requests=2, window_seconds=3600)
    assert limiter.check("mfa_send:user_a")[0] is True
    assert limiter.check("mfa_send:user_a")[0] is True
    assert limiter.check("mfa_send:user_a")[0] is False
    # 異なるアカウントは別カウント
    assert limiter.check("mfa_send:user_b")[0] is True


def test_mfa_verify_rate_limit_blocks_after_limit() -> None:
    """MFA 検証レート制限: 連続5回失敗まで許可、6回目で拒否。"""
    limiter = RateLimiter(max_requests=5, window_seconds=300)

    # 5回まで許可
    for _ in range(5):
        allowed, _ = limiter.check("mfa_verify:session1")
        assert allowed is True

    # 6回目で拒否
    allowed, retry_after = limiter.check("mfa_verify:session1")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1


def test_mfa_verify_rate_limit_separate_sessions() -> None:
    """MFA 検証レート制限: 異なるセッションは独立してカウントされる。"""
    limiter = RateLimiter(max_requests=2, window_seconds=300)
    assert limiter.check("mfa_verify:session_a")[0] is True
    assert limiter.check("mfa_verify:session_a")[0] is True
    assert limiter.check("mfa_verify:session_a")[0] is False
    # 異なるセッションは別カウント
    assert limiter.check("mfa_verify:session_b")[0] is True


def test_mfa_rate_limit_reset_allows_retry() -> None:
    """MFA レート制限: reset() でキーの状態をクリアし再試行を許可する。"""
    limiter = RateLimiter(max_requests=1, window_seconds=300)
    assert limiter.check("key")[0] is True
    assert limiter.check("key")[0] is False
    limiter.reset("key")
    assert limiter.check("key")[0] is True


def test_mfa_rate_limit_remaining_count() -> None:
    """MFA レート制限: get_remaining() で残り許容リクエスト数を取得できる。"""
    limiter = RateLimiter(max_requests=3, window_seconds=300)
    assert limiter.get_remaining("key") == 3
    limiter.check("key")
    assert limiter.get_remaining("key") == 2
    limiter.check("key")
    assert limiter.get_remaining("key") == 1
