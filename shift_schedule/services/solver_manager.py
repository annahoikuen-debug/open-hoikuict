"""Timefold 思想に基づく SolverManager 実装。

ジョブ優先度管理、協調的キャンセル（CancellationToken）、
求解進捗イベントのリアルタイム配信・キャッシュを担当する。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from enum import IntEnum
from typing import Any, Optional

from sqlmodel import Session, select

from database import engine
from shift_schedule.contracts import SolveJobStatus
from shift_schedule.db_models import ShiftSolveJobs
from time_utils import utc_now
from vendor.nushift.shiftai.domain import CancellationToken

logger = logging.getLogger(__name__)


class JobPriority(IntEnum):
    """求解ジョブの優先度。数値が小さいほど優先度が高い。"""

    URGENT_REPLAN = 1   # 突発欠勤・現場緊急再計画
    INTERACTIVE = 2     # UIからの通常手動求解
    BATCH_BACKGROUND = 3  # 夜間バッチ・ローリングホライズン自動再計画


class SolverManager:
    """求解ジョブのライフサイクル・キャンセル・進捗を集中管理するマネージャー。"""

    _instance: Optional[SolverManager] = None
    _lock = threading.Lock()

    def __new__(cls) -> SolverManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._init_manager()
            return cls._instance

    def _init_manager(self) -> None:
        self._tokens: dict[int, CancellationToken] = {}
        self._progress: dict[int, dict[str, Any]] = {}
        self._last_db_sync: dict[int, float] = {}
        self._state_lock = threading.Lock()

    def register_job(self, job_id: int) -> CancellationToken:
        """ジョブのキャンセルトークンを生成・登録する。"""
        with self._state_lock:
            token = CancellationToken()
            self._tokens[job_id] = token
            self._progress[job_id] = {
                "job_id": job_id,
                "stage": "QUEUED",
                "progress_percent": 0,
                "current_day": None,
                "total_days": 0,
                "updated_at": utc_now().isoformat(),
            }
            self._last_db_sync[job_id] = time.time()
            return token

    def get_token(self, job_id: int) -> CancellationToken:
        """ジョブのキャンセルトークンを取得する。存在しない場合は新規登録。"""
        with self._state_lock:
            if job_id not in self._tokens:
                self._tokens[job_id] = CancellationToken()
            return self._tokens[job_id]

    def cancel_job(self, job_id: int) -> bool:
        """実行中または待機中ジョブに対して協調的キャンセルを要求する。"""
        with self._state_lock:
            token = self._tokens.get(job_id)
            if token:
                token.cancel()

            if job_id in self._progress:
                self._progress[job_id]["stage"] = "CANCELLED"
                self._progress[job_id]["is_cancelled"] = True

        # DB のステータスを即座に CANCELLED に更新
        try:
            with Session(engine) as session:
                job = session.exec(
                    select(ShiftSolveJobs).where(ShiftSolveJobs.id == job_id)
                ).first()
                if job:
                    if job.status in (SolveJobStatus.QUEUED, SolveJobStatus.RUNNING):
                        job.status = SolveJobStatus.CANCELLED
                        job.finished_at = utc_now()
                        job.error_message = "ユーザーによってキャンセルされました。"
                        session.add(job)
                        session.commit()
                        logger.info("Job %d cancelled successfully", job_id)
                        return True
        except Exception as e:
            logger.error("Failed to cancel job %d in DB: %s", job_id, e)

        return token is not None

    def is_cancelled(self, job_id: int) -> bool:
        """ジョブがキャンセルされているか判定する。"""
        with self._state_lock:
            token = self._tokens.get(job_id)
            return token.is_cancelled() if token else False

    def update_progress(self, job_id: int, payload: dict[str, Any]) -> None:
        """求解進捗をリアルタイムキャッシュに記録し、一定間隔でDBにも同期する。"""
        now = time.time()
        should_sync_db = False

        with self._state_lock:
            current = self._progress.get(job_id, {"job_id": job_id})
            current.update(payload)
            current["updated_at"] = utc_now().isoformat()
            self._progress[job_id] = current

            last_sync = self._last_db_sync.get(job_id, 0.0)
            stage = payload.get("stage", "")
            # ステージ完了時または3秒以上経過している場合にDB書き込み
            if stage in ("STAGE_1_DONE", "DONE", "CANCELLED") or (now - last_sync >= 3.0):
                should_sync_db = True
                self._last_db_sync[job_id] = now

        if should_sync_db:
            try:
                with Session(engine) as session:
                    job = session.exec(
                        select(ShiftSolveJobs).where(ShiftSolveJobs.id == job_id)
                    ).first()
                    if job and job.status == SolveJobStatus.RUNNING:
                        stats_dict = {}
                        if job.stats:
                            try:
                                stats_dict = json.loads(job.stats)
                            except Exception:
                                pass
                        stats_dict["progress"] = payload
                        job.stats = json.dumps(stats_dict, ensure_ascii=False)
                        session.add(job)
                        session.commit()
            except Exception as e:
                logger.debug("Minor failure updating job progress in DB: %s", e)

    def get_progress(self, job_id: int) -> dict[str, Any]:
        """ジョブの最新進捗を取得する。メモリキャッシュを優先し、なければDBから復元。"""
        with self._state_lock:
            if job_id in self._progress:
                return dict(self._progress[job_id])

        # DB から読み出し
        try:
            with Session(engine) as session:
                job = session.exec(
                    select(ShiftSolveJobs).where(ShiftSolveJobs.id == job_id)
                ).first()
                if job:
                    res: dict[str, Any] = {
                        "job_id": job.id,
                        "status": job.status,
                        "started_at": job.started_at.isoformat() if job.started_at else None,
                        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                        "time_limit_sec": job.time_limit_sec,
                    }
                    if job.stats:
                        try:
                            s = json.loads(job.stats)
                            if "progress" in s:
                                res.update(s["progress"])
                            if "score" in s:
                                res["score"] = s["score"]
                        except Exception:
                            pass
                    return res
        except Exception as e:
            logger.error("Failed to get progress for job %d: %s", job_id, e)

        return {"job_id": job_id, "status": "unknown"}

    def cleanup_job(self, job_id: int) -> None:
        """完了したジョブのリソース（トークン・キャッシュ）を解放する。"""
        with self._state_lock:
            self._tokens.pop(job_id, None)
            self._last_db_sync.pop(job_id, None)
            # 進捗キャッシュは一定時間照会されるため即座には消さず保持


solver_manager = SolverManager()
