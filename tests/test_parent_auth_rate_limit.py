"""保護者ログインレート制限のリグレッション防止テスト。"""

from __future__ import annotations

from rate_limiter import RateLimiter


def test_parent_login_rate_limit_blocks_after_limit() -> None:
    """IP単位・アカウント単位のレート制限で上限後にブロックされる。"""
    ip_limiter = RateLimiter(max_requests=10, window_seconds=60)
    account_limiter = RateLimiter(max_requests=5, window_seconds=60)

    # IP単位: 10回まで許可
    for _ in range(10):
        allowed, _ = ip_limiter.check("parent_login_ip:192.168.1.1")
        assert allowed is True
    # 11回目で拒否
    allowed, retry_after = ip_limiter.check("parent_login_ip:192.168.1.1")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1

    # アカウント単位: 5回まで許可
    for _ in range(5):
        allowed, _ = account_limiter.check("parent_login_account:user1")
        assert allowed is True
    # 6回目で拒否
    allowed, retry_after = account_limiter.check("parent_login_account:user1")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1


def test_parent_login_rate_limit_retry_after_header() -> None:
    """拒否時に Retry-After 秒数が返される。"""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.check("key")
    allowed, retry_after = limiter.check("key")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1


def test_parent_login_rate_limit_separate_keys() -> None:
    """異なるIP・アカウントキーは独立してカウントされる。"""
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.check("parent_login_ip:192.168.1.1")[0] is True
    assert limiter.check("parent_login_ip:192.168.1.1")[0] is True
    assert limiter.check("parent_login_ip:192.168.1.1")[0] is False
    # 異なるIPは別カウント
    assert limiter.check("parent_login_ip:192.168.1.2")[0] is True
    # 異なるアカウントも別カウント
    assert limiter.check("parent_login_account:user_a")[0] is True


def test_parent_login_rate_limit_reset_allows_retry() -> None:
    """レート制限: reset() でキーの状態をクリアし再試行を許可する。"""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    assert limiter.check("key")[0] is True
    assert limiter.check("key")[0] is False
    limiter.reset("key")
    assert limiter.check("key")[0] is True


def test_parent_login_rate_limit_remaining_count() -> None:
    """レート制限: get_remaining() で残り許容リクエスト数を取得できる。"""
    limiter = RateLimiter(max_requests=3, window_seconds=60)
    assert limiter.get_remaining("key") == 3
    limiter.check("key")
    assert limiter.get_remaining("key") == 2
    limiter.check("key")
    assert limiter.get_remaining("key") == 1
