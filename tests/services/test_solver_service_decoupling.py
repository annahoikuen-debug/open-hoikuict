"""Phase 4 Test: Solver-as-a-Service Decoupling & Distributed Worker.

検証内容:
1. process_single_distributed_job によるステートレス求解処理
2. 不正ペイロードのバリデーション
3. publish_progress_event による進捗イベント発行
"""

from datetime import date
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlmodel import Session

from database import engine, create_db_and_tables
from models import User
from shift_schedule.contracts import PlanStatus
from shift_schedule.db_models import (
    ShiftFacilitySettings,
    ShiftPlans,
    ShiftSolveJobs,
    StaffContracts,
    StaffQualifications,
)
from shift_schedule.services.distributed_worker import (
    SOLVER_PROGRESS_CHANNEL,
    process_single_distributed_job,
    publish_progress_event,
)
from shift_schedule.store import SqlModelShiftRepository


def test_process_single_distributed_job():
    """分散ワーカーがペイロードを受信し、ステートレスに求解を完了できること。"""
    create_db_and_tables()

    uid1 = uuid4()
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        fs = repo.facility_settings()
        if fs is None:
            fs = ShiftFacilitySettings(
                day_open="08:00",
                day_close="18:00",
                granularity_min=30,
                capacity=15,
                staffing_standard_key="全国基準（厚労省）",
            )
            session.add(fs)
            session.commit()

        u = User(
            id=uid1,
            email=f"dist_{uid1.hex[:6]}@example.com",
            display_name="分散職員",
            role="staff",
            is_active=True,
        )
        session.add(u)
        session.add(
            StaffQualifications(
                staff_user_id=uid1.hex,
                role="保育士",
                effective_from=date(2026, 4, 1),
            )
        )
        session.add(
            StaffContracts(
                staff_user_id=uid1.hex,
                employment_type="正職員",
                weekly_hours=40.0,
                daily_hours=8.0,
                effective_from=date(2026, 4, 1),
            )
        )
        plan = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.DRAFT.value,
            staffing_standard_key="全国基準（厚労省）",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        plan_id = plan.id

        job = ShiftSolveJobs(plan_id=plan_id, status="queued")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    payload = {
        "job_id": job_id,
        "plan_id": plan_id,
        "target_month": "2026-11",
        "staffing_standard_key": "全国基準（厚労省）",
        "time_limit_sec": 5,
    }

    result = process_single_distributed_job(payload)

    assert result["job_id"] == job_id
    assert result["plan_id"] == plan_id
    assert result["status"] == "succeeded"
    assert "elapsed_sec" in result
    assert result["stats"]["cells"] > 0


def test_distributed_worker_payload_validation():
    """必須キーが不足しているペイロードで ValueError が送出されること。"""
    with pytest.raises(ValueError, match="不正なジョブペイロード"):
        process_single_distributed_job({"job_id": 1})  # plan_id, target_month 欠落


def test_publish_progress_event():
    """進捗イベントが正しいチャネルとJSONで発行されること。"""
    mock_redis = MagicMock()

    publish_progress_event(
        redis_client=mock_redis,
        job_id=42,
        stage="STAGE_1_DAILY_PATTERNS",
        progress_percent=50,
    )

    assert mock_redis.publish.called
    channel, message = mock_redis.publish.call_args[0]
    assert channel == SOLVER_PROGRESS_CHANNEL
    import json
    parsed = json.loads(message)
    assert parsed["job_id"] == 42
    assert parsed["stage"] == "STAGE_1_DAILY_PATTERNS"
    assert parsed["progress_percent"] == 50
