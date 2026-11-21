"""Phase 3 Test: Multi-tenant Data Isolation, Immutable Snapshots, and Optimistic Locking.

検証内容:
1. ShiftSolveSnapshots による求解入力の不変スナップショット永続化
2. lock_version によるセル編集の楽観的ロック（409 Conflict）検知
3. facility_id によるマルチテナント分離
"""

from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from database import engine, create_db_and_tables
from main import app
from models import User
from models.organization import DEFAULT_FACILITY_ID
from shift_schedule.contracts import PlanStatus
from shift_schedule.db_models import (
    ShiftFacilitySettings,
    ShiftPlans,
    ShiftSolveJobs,
    ShiftSolveSnapshots,
    StaffContracts,
    StaffQualifications,
)
from shift_schedule.services.solve_jobs import _run_solve_sync
from shift_schedule.store import SqlModelShiftRepository


@pytest.fixture
def test_client():
    from testing_helpers import authenticate_mock_staff
    from auth import Role

    c = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(c, role=Role.ADMIN)
    return c


def test_shift_solve_snapshot_persistence():
    """求解開始時に ShiftSolveSnapshots に不変スナップショットが保存されること。"""
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
            email=f"snap_{uid1.hex[:6]}@example.com",
            display_name="スナップ職員",
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
            facility_id=DEFAULT_FACILITY_ID,
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

    # 求解同期実行
    _run_solve_sync(
        job_id=job_id,
        plan_id=plan_id,
        target_month="2026-11",
        staffing_standard_key="全国基準（厚労省）",
        time_limit_sec=5,
    )

    with Session(engine) as session:
        snapshot = session.exec(
            select(ShiftSolveSnapshots).where(ShiftSolveSnapshots.job_id == job_id)
        ).first()

        assert snapshot is not None
        assert snapshot.plan_id == plan_id
        assert snapshot.facility_id == DEFAULT_FACILITY_ID
        import json
        payload = json.loads(snapshot.payload)
        assert payload["target_month"] == "2026-11"
        assert payload["staff_count"] >= 1


def test_optimistic_lock_version_conflict(test_client):
    """古い lock_version でセル編集を行うと 409 Conflict が返り、競合が保護されること。"""
    create_db_and_tables()

    uid1 = uuid4()
    with Session(engine) as session:
        u = User(
            id=uid1,
            email=f"opt_{uid1.hex[:6]}@example.com",
            display_name="楽観職員",
            role="staff",
            is_active=True,
        )
        session.add(u)

        plan = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.DRAFT.value,
            staffing_standard_key="全国基準（厚労省）",
            lock_version=2,
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        plan_id = plan.id

    # 1. 不正な（古い）lock_version=1 で更新 → 409 Conflict
    resp_conflict = test_client.post(
        f"/shifts/plans/{plan_id}/cells",
        data={
            "staff_user_id": uid1.hex,
            "target_date": "2026-11-10",
            "slot_label": "09:00-09:30",
            "cell_state": "WORK",
            "is_pinned": "true",
            "lock_version": "1",  # 古いバージョン
        },
    )
    assert resp_conflict.status_code == 409
    assert "更新されました" in resp_conflict.json()["detail"]

    # 2. 正しい lock_version=2 で更新 → 成功 (303 Redirect)
    resp_success = test_client.post(
        f"/shifts/plans/{plan_id}/cells",
        data={
            "staff_user_id": uid1.hex,
            "target_date": "2026-11-10",
            "slot_label": "09:00-09:30",
            "cell_state": "WORK",
            "is_pinned": "true",
            "lock_version": "2",  # 正しいバージョン
        },
        follow_redirects=False,
    )
    assert resp_success.status_code == 303

    # 3. DB側の lock_version が 3 にインクリメントされていること
    with Session(engine) as session:
        updated_plan = session.get(ShiftPlans, plan_id)
        assert updated_plan.lock_version == 3


def test_tenant_isolation_facility_plans():
    """施設ID（テナント）ごとのシフト計画が分離して管理できること。"""
    create_db_and_tables()

    other_facility_id = uuid4()

    with Session(engine) as session:
        plan1 = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.DRAFT.value,
            facility_id=DEFAULT_FACILITY_ID,
        )
        plan2 = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.DRAFT.value,
            facility_id=other_facility_id,
        )
        session.add_all([plan1, plan2])
        session.commit()

        # DEFAULT_FACILITY_ID の計画のみ取得
        facility1_plans = session.exec(
            select(ShiftPlans).where(ShiftPlans.facility_id == DEFAULT_FACILITY_ID)
        ).all()
        assert len(facility1_plans) >= 1
        assert all(p.facility_id == DEFAULT_FACILITY_ID for p in facility1_plans)

        # other_facility_id の計画のみ取得
        facility2_plans = session.exec(
            select(ShiftPlans).where(ShiftPlans.facility_id == other_facility_id)
        ).all()
        assert len(facility2_plans) == 1
        assert facility2_plans[0].facility_id == other_facility_id
