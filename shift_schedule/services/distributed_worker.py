"""NuShift Solver-as-a-Service 分散ワーカー (Distributed Solver Worker).

Web API（FastAPI）本体から数理最適化ソルバー（HiGHS / CBC）を完全にデカップリングし、
Kubernetes (KEDA) やコンテナクラスタ上で独立してイベント駆動オートスケールする
ステートレス計算ワーカー。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

from sqlmodel import Session

from database import engine
from shift_schedule.contracts import SolveJobStatus
from shift_schedule.db_models import ShiftSolveJobs
from shift_schedule.services.solve_jobs import _run_solve_sync
from time_utils import utc_now

logger = logging.getLogger(__name__)

SOLVER_QUEUE_KEY = os.getenv("HOIKUICT_SOLVER_QUEUE_KEY", "hoikuict:shift:solve_queue")
SOLVER_PROGRESS_CHANNEL = os.getenv("HOIKUICT_SOLVER_PROGRESS_CHANNEL", "hoikuict:shift:progress")


def process_single_distributed_job(
    job_payload: dict[str, Any],
    session: Optional[Session] = None,
) -> dict[str, Any]:
    """キューから受信した求解ジョブペイロードを処理し、結果ステータスを返す。"""
    job_id = job_payload.get("job_id")
    plan_id = job_payload.get("plan_id")
    target_month = job_payload.get("target_month")
    staffing_standard_key = job_payload.get("staffing_standard_key", "全国基準（厚労省）")
    time_limit_sec = job_payload.get("time_limit_sec", 30)

    if not job_id or not plan_id or not target_month:
        raise ValueError(f"不正なジョブペイロードです: {job_payload}")

    start_t = time.perf_counter()

    # 同期求解ループを実行
    _run_solve_sync(
        job_id=job_id,
        plan_id=plan_id,
        target_month=target_month,
        staffing_standard_key=staffing_standard_key,
        time_limit_sec=time_limit_sec,
    )

    elapsed = round(time.perf_counter() - start_t, 3)

    # 完了後のジョブステータスを確認
    with Session(engine) as sess:
        job = sess.get(ShiftSolveJobs, job_id)
        status = job.status if job else SolveJobStatus.FAILED
        stats = json.loads(job.stats) if job and job.stats else {}

    return {
        "job_id": job_id,
        "plan_id": plan_id,
        "status": status,
        "elapsed_sec": elapsed,
        "stats": stats,
    }


def publish_progress_event(
    redis_client: Any,
    job_id: int,
    stage: str,
    progress_percent: int,
) -> None:
    """Redis Pub/Sub 経由で進捗イベントを発行する。"""
    if not redis_client:
        return
    event = {
        "job_id": job_id,
        "stage": stage,
        "progress_percent": progress_percent,
        "timestamp": utc_now().isoformat(),
    }
    try:
        redis_client.publish(SOLVER_PROGRESS_CHANNEL, json.dumps(event, ensure_ascii=False))
    except Exception as e:
        logger.warning(f"進捗イベントの発行に失敗しました: {e}")
