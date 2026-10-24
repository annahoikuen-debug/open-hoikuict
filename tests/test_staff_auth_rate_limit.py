"""スタッフログインレート制限のリグレッション防止テスト。"""

from __future__ import annotations

from rate_limiter import RateLimiter


def test_staff_login_rate_limit_blocks_after_limit() -> None:
    """IP単位・アカウント単位のレート制限で上限後にブロックされる。"""
    ip_limiter = RateLimiter(max_requests=10, window_seconds=60)
    account_limiter = RateLimiter(max_requests=5, window_seconds=60)

    # IP単位: 10回まで許可
    for _ in range(10):
        allowed, _ = ip_limiter.check("ip:192.168.1.1")
        assert allowed is True
    # 11回目で拒否
    allowed, retry_after = ip_limiter.check("ip:192.168.1.1")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1

    # アカウント単位: 5回まで許可
    for _ in range(5):
        allowed, _ = account_limiter.check("account:user1")
        assert allowed is True
    # 6回目で拒否
    allowed, retry_after = account_limiter.check("account:user1")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1


def test_staff_login_rate_limit_retry_after_header() -> None:
    """拒否時に Retry-After 秒数が返される。"""
    limiter = RateLimiter(max_requests=1, window_seconds=60)
    limiter.check("key")
    allowed, retry_after = limiter.check("key")
    assert allowed is False
    assert retry_after is not None
    assert retry_after >= 1


def test_staff_login_rate_limit_separate_keys() -> None:
    """異なるIP・アカウントキーは独立してカウントされる。"""
    limiter = RateLimiter(max_requests=2, window_seconds=60)
    assert limiter.check("ip:192.168.1.1")[0] is True
    assert limiter.check("ip:192.168.1.1")[0] is True
    assert limiter.check("ip:192.168.1.1")[0] is False
    # 異なるIPは別カウント
    assert limiter.check("ip:192.168.1.2")[0] is True
    # 異なるアカウントも別カウント
    assert limiter.check("account:user_a")[0] is True
