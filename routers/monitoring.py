"""運用監視・オブザーバビリティエンドポイント (Phase 5.3).

Prometheus メトリクスおよび Kubernetes / クラウドコンテナ向け Liveness / Readiness プローブを提供します。
"""
from __future__ import annotations

import os
import tempfile
import time
from typing import Any, Dict

from fastapi import APIRouter, Response, status
from fastapi.responses import JSONResponse
from sqlmodel import Session, select, func

from database import engine
from models.core import Child, ChildStatus
from models.organization import Facility
from tasks.queue import get_queue_length, is_redis_available
from time_utils import local_naive_now

router = APIRouter(tags=["monitoring"])


@router.get("/health/live")
def liveness_probe() -> Dict[str, Any]:
    """コンテナ・プロセスの生存確認 (Liveness Probe).
    
    プロセスがハングアップせずリクエストに応答できることを保証します。
    """
    return {
        "status": "alive",
        "timestamp": local_naive_now().isoformat(),
    }


@router.get("/health/ready")
def readiness_probe() -> JSONResponse:
    """サービス提供準備状況の確認 (Readiness Probe).
    
    DB 接続、ストレージ書き込み、タスクキューの健全性を検証し、
    トラフィックを受け入れ可能か判定します。
    """
    checks: Dict[str, Any] = {}
    is_healthy = True

    # 1. データベース疎通チェック
    try:
        with Session(engine) as session:
            # 最小クエリで接続確認
            session.exec(select(1)).first()
            checks["database"] = {"status": "ok"}
    except Exception as exc:
        is_healthy = False
        checks["database"] = {"status": "error", "error": str(exc)}

    # 2. ストレージ（テンポラリ）書き込み検証
    try:
        with tempfile.NamedTemporaryFile(delete=True) as tf:
            tf.write(b"health_check")
            tf.flush()
        checks["storage"] = {"status": "ok"}
    except Exception as exc:
        is_healthy = False
        checks["storage"] = {"status": "error", "error": str(exc)}

    # 3. 非同期キュー検証
    redis_online = is_redis_available()
    checks["queue"] = {
        "status": "ok",
        "mode": "redis" if redis_online else "in_memory",
        "pending_jobs": get_queue_length(),
    }

    http_status = status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        status_code=http_status,
        content={
            "status": "ready" if is_healthy else "unhealthy",
            "timestamp": local_naive_now().isoformat(),
            "checks": checks,
        },
    )


@router.get("/metrics")
def prometheus_metrics() -> Response:
    """Prometheus 互換メトリクスエンドポイント."""
    db_ok = 1
    facility_count = 0
    enrolled_children = 0

    try:
        with Session(engine) as session:
            session.exec(select(1)).first()
            facility_count = len(session.exec(select(Facility)).all())
            enrolled_children = len(
                session.exec(select(Child).where(Child.status == ChildStatus.enrolled)).all()
            )
    except Exception:
        db_ok = 0

    pending_queue_jobs = get_queue_length()
    redis_status = 1 if is_redis_available() else 0

    lines = [
        "# HELP hoikuict_up Liveness status of the open-hoikuict application (1=up, 0=down)",
        "# TYPE hoikuict_up gauge",
        "hoikuict_up 1",
        "",
        "# HELP hoikuict_db_status Database connection health status (1=ok, 0=error)",
        "# TYPE hoikuict_db_status gauge",
        f"hoikuict_db_status {db_ok}",
        "",
        "# HELP hoikuict_redis_status Redis worker queue status (1=connected, 0=fallback_memory)",
        "# TYPE hoikuict_redis_status gauge",
        f"hoikuict_redis_status {redis_status}",
        "",
        "# HELP hoikuict_queue_pending_jobs Number of pending solve jobs in the background queue",
        "# TYPE hoikuict_queue_pending_jobs gauge",
        f"hoikuict_queue_pending_jobs {pending_queue_jobs}",
        "",
        "# HELP hoikuict_active_facilities_total Total registered active facilities",
        "# TYPE hoikuict_active_facilities_total gauge",
        f"hoikuict_active_facilities_total {facility_count}",
        "",
        "# HELP hoikuict_enrolled_children_total Total enrolled children count",
        "# TYPE hoikuict_enrolled_children_total gauge",
        f"hoikuict_enrolled_children_total {enrolled_children}",
        "",
    ]
    body = "\n".join(lines)
    return Response(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")
