"""Standalone background worker for open-hoikuict.

Web サーバー（FastAPI）から分離された独立ワーカープロセスとして実行され、
Redis キューから求解ジョブ・重帳票生成ジョブを取り出して処理します。
これにより、求解中の CPU/メモリ高負荷や OOM 発生時も Web サーバーは 100% 安定稼働を維持します。

起動方法:
    python worker.py
"""
from __future__ import annotations

import logging
import signal
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [worker] %(message)s",
)
logger = logging.getLogger("worker")

_running = True


def _signal_handler(signum, frame):
    global _running
    del signum, frame
    logger.info("シャットダウンシグナルを受信しました。処理中のジョブ完了を待機して終了します...")
    _running = False


def run_worker():
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    from tasks.queue import dequeue_solve_job, is_redis_available
    from shift_schedule.services.solve_jobs import process_next_solve_job

    logger.info("open-hoikuict バックグラウンドワーカーを起動しました。")
    if not is_redis_available(force_check=True):
        logger.warning(
            "警告: Redis に接続できません。Redis サーバーが稼働しているか確認してください。"
        )

    idle_count = 0
    while _running:
        try:
            job_id = dequeue_solve_job(timeout_sec=2)
            if job_id is not None:
                idle_count = 0
                logger.info("ジョブ %d を受信しました。求解処理を開始します...", job_id)
                success = process_next_solve_job()
                logger.info("ジョブ %d の処理が完了しました（成功: %s）", job_id, success)
            else:
                idle_count += 1
                if idle_count % 30 == 0:
                    logger.debug("待機中... (キュー空)")
        except Exception as exc:
            logger.error("ワーカー実行ループエラー: %s", exc, exc_info=True)
            time.sleep(1)

    logger.info("バックグラウンドワーカーを正常に終了しました。")


if __name__ == "__main__":
    run_worker()
