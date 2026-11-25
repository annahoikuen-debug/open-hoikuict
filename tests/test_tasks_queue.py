"""バックグラウンドタスクキュー（Redis & インメモリフォールバック）のテスト。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from tasks.queue import (
    SOLVE_QUEUE_KEY,
    dequeue_solve_job,
    enqueue_solve_job,
    is_redis_available,
)


class TaskQueueTests(unittest.TestCase):
    def test_is_redis_available_disabled_by_env(self):
        """HOIKUICT_USE_REDIS=0 の場合は即座に False を返すこと。"""
        with patch.dict("os.environ", {"HOIKUICT_USE_REDIS": "0"}):
            assert is_redis_available(force_check=True) is False

    def test_enqueue_falls_back_to_in_memory_when_no_redis(self):
        """Redis が利用できない場合はインメモリスレッドプールへフォールバックすること。"""
        with patch("tasks.queue.is_redis_available", return_value=False), \
             patch("shift_schedule.services.solve_jobs._solve_executor.submit") as mock_submit:
            res = enqueue_solve_job(123)
            assert res == "in_memory"
            mock_submit.assert_called_once()

    def test_enqueue_uses_redis_when_available(self):
        """Redis が利用可能な場合は Redis キューへ投入されること。"""
        mock_client = MagicMock()
        with patch("tasks.queue.is_redis_available", return_value=True), \
             patch("tasks.queue.get_redis_client", return_value=mock_client):
            res = enqueue_solve_job(456)
            assert res == "redis"
            mock_client.rpush.assert_called_once_with(SOLVE_QUEUE_KEY, "456")

    def test_dequeue_solve_job(self):
        """Redis キューからブロッキングデキューできること。"""
        mock_client = MagicMock()
        mock_client.blpop.return_value = (SOLVE_QUEUE_KEY, "789")
        with patch("tasks.queue.get_redis_client", return_value=mock_client):
            job_id = dequeue_solve_job(timeout_sec=1)
            assert job_id == 789
            mock_client.blpop.assert_called_once_with(SOLVE_QUEUE_KEY, timeout=1)

    def test_dequeue_returns_none_when_empty(self):
        """タイムアウト時は None を返すこと。"""
        mock_client = MagicMock()
        mock_client.blpop.return_value = None
        with patch("tasks.queue.get_redis_client", return_value=mock_client):
            job_id = dequeue_solve_job(timeout_sec=1)
            assert job_id is None


def test_solve_queue_key_matches_distributed_worker_and_keda():
    """Producer、分散ワーカー、KEDAオートスケーラー間で既定キューキーが一致すること。"""
    import importlib
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("HOIKUICT_SOLVER_QUEUE_KEY", None)
        import shift_schedule.services.distributed_worker as dw
        import tasks.queue as tq

        importlib.reload(tq)
        importlib.reload(dw)
        assert tq.SOLVE_QUEUE_KEY == "hoikuict:shift:solve_queue"
        assert tq.SOLVE_QUEUE_KEY == dw.SOLVER_QUEUE_KEY
