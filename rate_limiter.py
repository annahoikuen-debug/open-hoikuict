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

    _check_counter: int = 0
    sweep_interval: int = 1000

    def _now(self) -> float:
        return time.monotonic()

    def _cleanup_expired(self, key: str, now: float) -> None:
        """ウィンドウ外の古いタイムスタンプを削除する。空になったキーは破棄する。"""
        cutoff = now - self.window_seconds
        timestamps = self._timestamps.get(key, [])
        valid = [ts for ts in timestamps if ts > cutoff]
        if valid:
            self._timestamps[key] = valid
        else:
            self._timestamps.pop(key, None)

    def sweep(self) -> None:
        """全キーを走査し、期限切れタイムスタンプおよび空キーを一括削除する。"""
        now = self._now()
        with self._lock:
            cutoff = now - self.window_seconds
            empty_keys = []
            for k, ts_list in self._timestamps.items():
                valid = [ts for ts in ts_list if ts > cutoff]
                if valid:
                    self._timestamps[k] = valid
                else:
                    empty_keys.append(k)
            for k in empty_keys:
                self._timestamps.pop(k, None)

    def check(self, key: str) -> tuple[bool, int | None]:
        """キーに対してリクエストを許可するか判定する。

        Returns:
            (許可可否, Retry-After秒数。拒否時のみ設定)
        """
        now = self._now()
        with self._lock:
            self._check_counter += 1
            if self._check_counter >= self.sweep_interval:
                self._check_counter = 0
                cutoff = now - self.window_seconds
                empty_keys = [k for k, ts in self._timestamps.items() if not any(t > cutoff for t in ts)]
                for k in empty_keys:
                    self._timestamps.pop(k, None)

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


def client_ip(request: Request) -> str:
    """リクエストから信頼できるクライアントIPアドレスを取得する。

    直接接続されたクライアントIP（request.client.host）を基本とし、
    そのIPが FORWARDED_ALLOW_IPS で設定された信頼できるプロキシ（またはローカルホスト）
    である場合にのみ、X-Forwarded-For の最右端（直近の非信頼IP）を採用する。
    信頼できないホストからの X-Forwarded-For による偽装を防止する。
    """
    client_host = request.client.host if request.client else "unknown"
    if client_host == "unknown":
        return "unknown"

    from security_config import forwarded_allow_ips
    trusted_raw = forwarded_allow_ips()
    trusted_proxies = set(trusted_raw) if trusted_raw else {"127.0.0.1", "::1", "testserver"}

    is_trusted = client_host in trusted_proxies
    if not is_trusted:
        import ipaddress
        for t in trusted_proxies:
            try:
                if "/" in t and ipaddress.ip_address(client_host) in ipaddress.ip_network(t, strict=False):
                    is_trusted = True
                    break
            except ValueError:
                pass

    if is_trusted:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # カンマ区切りの右から順に走査し、信頼できるプロキシでない最初のIPを採用
            parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
            for ip in reversed(parts):
                if ip not in trusted_proxies:
                    return ip
            if parts:
                return parts[0]

    return client_host


def rate_limit_key_from_request(request: Request, prefix: str = "") -> str:
    """リクエストからレート制限キーを生成する（クライアントIPベース）。"""
    return f"{prefix}{client_ip(request)}"


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
