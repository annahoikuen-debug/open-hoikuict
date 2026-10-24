"""スライディングウィンドウ型インメモリレートリミッター。

外部依存（Redisなど）を持たず、単一プロセス・小規模保育園の
オンプレ/コンテナ環境でも即座に動作するレートリミッターを提供する。

キー（IPアドレス、ユーザーID、アカウント識別子）ごとにタイムスタンプリストを管理し、
期限切れの古いタイムスタンプを自動クリーンアップする。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from fastapi import Depends, HTTPException, Request, status


@dataclass
class RateLimiter:
    """スライディングウィンドウ型インメモリレートリミッター。

    キーごとにリクエスト時刻のリストを保持し、ウィンドウ内のリクエスト数を
    カウントする。スレッドセーフ。
    """

    max_requests: int
    window_seconds: int
    _timestamps: dict[str, list[float]] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def _now(self) -> float:
        return time.monotonic()

    def _cleanup_expired(self, key: str, now: float) -> None:
        """ウィンドウ外の古いタイムスタンプを削除する。"""
        cutoff = now - self.window_seconds
        timestamps = self._timestamps.get(key, [])
        self._timestamps[key] = [ts for ts in timestamps if ts > cutoff]

    def check(self, key: str) -> tuple[bool, int | None]:
        """キーに対してリクエストを許可するか判定する。

        Returns:
            (許可可否, Retry-After秒数。拒否時のみ設定)
        """
        now = self._now()
        with self._lock:
            self._cleanup_expired(key, now)
            timestamps = self._timestamps.get(key, [])
            if len(timestamps) >= self.max_requests:
                oldest = timestamps[0]
                retry_after = int(oldest + self.window_seconds - now) + 1
                if retry_after < 1:
                    retry_after = 1
                return False, retry_after
            timestamps.append(now)
            self._timestamps[key] = timestamps
            return True, None

    def reset(self, key: str) -> None:
        """キーのレート制限状態をリセットする。"""
        with self._lock:
            self._timestamps.pop(key, None)

    def get_remaining(self, key: str) -> int:
        """キーの残り許容リクエスト数を取得する。"""
        now = self._now()
        with self._lock:
            self._cleanup_expired(key, now)
            timestamps = self._timestamps.get(key, [])
            remaining = self.max_requests - len(timestamps)
            return max(remaining, 0)


# デフォルトレートリミッターインスタンス（スタッフログイン用：1分間に10回）
DEFAULT_RATE_LIMITER = RateLimiter(max_requests=10, window_seconds=60)


def rate_limit_key_from_request(request: Request, prefix: str = "") -> str:
    """リクエストからレート制限キーを生成する（クライアントIPベース）。"""
    client_host = request.client.host if request.client else "unknown"
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        client_host = forwarded_for.split(",")[0].strip()
    return f"{prefix}{client_host}"


def check_rate_limit(
    key: str,
    max_requests: int,
    window_seconds: int,
    limiter: RateLimiter | None = None,
) -> None:
    """FastAPI Depends で利用できるレート制限チェックヘルパー。

    超過時は HTTP 429 Too Many Requests と Retry-After ヘッダーを返す。
    """
    limiter_instance = limiter or DEFAULT_RATE_LIMITER
    allowed, retry_after = limiter_instance.check(key)
    if not allowed:
        headers = {"Retry-After": str(retry_after)} if retry_after else {}
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="リクエストが多すぎます。しばらくお待ちください。",
            headers=headers,
        )


def rate_limit_dependency(
    max_requests: int,
    window_seconds: int,
    key_func: Callable[[Request], str] | None = None,
    limiter: RateLimiter | None = None,
):
    """FastAPI の Depends として利用できるレート制限デコーダーを返す。

    Args:
        max_requests: ウィンドウ内の最大許可リクエスト数
        window_seconds: ウィンドウ秒数
        key_func: リクエストからキーを生成する関数（デフォルトは IP ベース）
        limiter: 使用する RateLimiter インスタンス（未指定時はデフォルト）
    """
    if key_func is None:
        key_func = rate_limit_key_from_request

    async def dependency(request: Request) -> None:
        key = key_func(request)
        check_rate_limit(key, max_requests, window_seconds, limiter)

    return Depends(dependency)
