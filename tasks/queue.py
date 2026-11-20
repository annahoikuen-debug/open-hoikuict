"""Background task queue management for open-hoikuict.

Redis が利用可能な場合は Redis キューによるプロセス分離ワーカーへジョブを委譲し、
開発環境・テスト等で Redis が未起動の場合はインメモリスレッドプールで即座に実行する
透過的ハイブリッド・ディスパッチャーを提供します。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SOLVE_QUEUE_KEY = "hoikuict:queue:solve_jobs"

_redis_client: Optional[object] = None
_redis_available_cached: Optional[bool] = None


def get_redis_client():
    """Redis クライアントのシングルトンを取得する。"""
    global _redis_client
    if _redis_client is None:
        try:
            import redis

            _redis_client = redis.Redis.from_url(
                REDIS_URL,
                socket_timeout=1.0,
                socket_connect_timeout=1.0,
                decode_responses=True,
            )
        except Exception as exc:
            logger.debug("Redis クライアントの初期化に失敗しました: %s", exc)
            _redis_client = None
    return _redis_client


def is_redis_available(force_check: bool = False) -> bool:
    """Redis サーバーが稼働しているかを高速に判定する。"""
    global _redis_available_cached
    if os.getenv("HOIKUICT_USE_REDIS") == "0":
        return False
    if _redis_available_cached is not None and not force_check:
        return _redis_available_cached

    client = get_redis_client()
    if client is None:
        _redis_available_cached = False
        return False
    try:
        client.ping()
        _redis_available_cached = True
    except Exception:
        _redis_available_cached = False
    return _redis_available_cached


def enqueue_solve_job(job_id: int) -> str:
    """シフト求解ジョブをキューに投入する。

    Redis が利用可能な場合は Redis リストへ投入し、
    未稼働の場合はインメモリスレッドプールへフォールバックする。

    Returns:
        "redis" | "in_memory"
    """
    if is_redis_available():
        try:
            client = get_redis_client()
            if client is not None:
                client.rpush(SOLVE_QUEUE_KEY, str(job_id))
                logger.info("求解ジョブ %d を Redis キュー (%s) に投入しました", job_id, SOLVE_QUEUE_KEY)
                return "redis"
        except Exception as exc:
            logger.warning("Redis キュー投入に失敗したためインメモリにフォールバックします: %s", exc)

    # インメモリスレッドプールへフォールバック
    from shift_schedule.services.solve_jobs import _solve_executor, process_next_solve_job

    _solve_executor.submit(process_next_solve_job)
    logger.info("求解ジョブ %d をインメモリスレッドプールに投入しました", job_id)
    return "in_memory"


def dequeue_solve_job(timeout_sec: int = 2) -> Optional[int]:
    """Redis キューから次の求解ジョブ ID を取得する（ワーカー用ブロッキングポップ）。"""
    client = get_redis_client()
    if client is None:
        return None
    try:
        item = client.blpop(SOLVE_QUEUE_KEY, timeout=timeout_sec)
        if item:
            _, job_id_str = item
            return int(job_id_str)
    except Exception as exc:
        logger.error("Redis デキューエラー: %s", exc)
    return None


def get_queue_length() -> int:
    """現在のキュー待機ジョブ数を取得する。"""
    if is_redis_available():
        client = get_redis_client()
        if client is not None:
            try:
                return client.llen(SOLVE_QUEUE_KEY)
            except Exception:
                return 0
    return 0

