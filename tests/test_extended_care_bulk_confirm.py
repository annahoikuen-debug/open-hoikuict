"""延長保育料一括確認 (bulk-confirm) の異常値・0円除外テスト。"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import child_records.models  # noqa: F401
from auth import Role, StaffUser, get_current_staff_user
from database import get_session
from models import (
    AttendanceRecord,
    Child,
    ChildStatus,
    ExtendedCareCharge,
    ExtendedCareChargeStatus,
    ExtendedCareFeeRule,
    Family,
)
from routers.extended_care_fees import router as extended_care_fees_router


def test_bulk_confirm_skips_zero_amount_and_anomalies() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        family = Family(family_name="テスト世帯")
        session.add(family)
        session.flush()
        child = Child(
            family_id=family.id,
            last_name="テスト",
            first_name="園児",
            last_name_kana="テスト",
            first_name_kana="エンジ",
            birth_date=date(2022, 4, 1),
            enrollment_date=date(2025, 4, 1),
            status=ChildStatus.enrolled,
        )
        rule = ExtendedCareFeeRule(
            name="標準ルール",
            effective_from=date(2026, 1, 1),
            start_time="18:00",
            grace_minutes=0,
            rounding_minutes=30,
            unit_price=500,
        )
        session.add(child)
        session.add(rule)
        session.flush()

        # 1. 正常な明細 -> 確定されるべき
        rec_ok = AttendanceRecord(
            child_id=child.id,
            attendance_date=date(2026, 11, 10),
            check_in_at=datetime(2026, 11, 10, 8, 30),
            check_out_at=datetime(2026, 11, 10, 18, 45),
        )
        # 2. 翌日03:00超えの異常打刻 -> スキップされるべき
        rec_late = AttendanceRecord(
            child_id=child.id,
            attendance_date=date(2026, 11, 11),
            check_in_at=datetime(2026, 11, 11, 8, 30),
            check_out_at=datetime(2026, 11, 12, 4, 0),
        )
        # 3. 0円明細 -> 対象外 (draft のまま)
        rec_zero = AttendanceRecord(
            child_id=child.id,
            attendance_date=date(2026, 11, 12),
            check_in_at=datetime(2026, 11, 12, 8, 30),
            check_out_at=datetime(2026, 11, 12, 17, 30),
        )
        session.add_all([rec_ok, rec_late, rec_zero])
        session.flush()

        c_ok = ExtendedCareCharge(
            attendance_record_id=rec_ok.id,
            child_id=child.id,
            rule_id=rule.id,
            target_date=date(2026, 11, 10),
            charge_start_at=datetime(2026, 11, 10, 18, 0),
            extended_minutes=45,
            billable_units=2,
            auto_amount=1000,
            final_amount=1000,
            status=ExtendedCareChargeStatus.draft,
        )
        c_late = ExtendedCareCharge(
            attendance_record_id=rec_late.id,
            child_id=child.id,
            rule_id=rule.id,
            target_date=date(2026, 11, 11),
            charge_start_at=datetime(2026, 11, 11, 18, 0),
            extended_minutes=600,
            billable_units=20,
            auto_amount=10000,
            final_amount=10000,
            status=ExtendedCareChargeStatus.draft,
        )
        c_zero = ExtendedCareCharge(
            attendance_record_id=rec_zero.id,
            child_id=child.id,
            rule_id=rule.id,
            target_date=date(2026, 11, 12),
            charge_start_at=datetime(2026, 11, 12, 18, 0),
            extended_minutes=0,
            billable_units=0,
            auto_amount=0,
            final_amount=0,
            status=ExtendedCareChargeStatus.draft,
        )
        session.add_all([c_ok, c_late, c_zero])
        session.commit()
        ok_id, late_id, zero_id = c_ok.id, c_late.id, c_zero.id

    test_app = FastAPI()
    test_app.include_router(extended_care_fees_router)

    def _override_session():
        with Session(engine) as session:
            yield session

    test_app.dependency_overrides[get_session] = _override_session
    test_app.dependency_overrides[get_current_staff_user] = lambda: StaffUser(
        role=Role.ADMIN,
        name="テスト園長",
    )

    try:
        with TestClient(test_app) as client:
            resp = client.post(
                "/extended-care-fees/bulk-confirm",
                data={"month": "2026-11"},
                headers={"Accept": "application/json"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["confirmed_count"] == 1
            assert data["skipped_count"] == 1

        with Session(engine) as session:
            assert session.get(ExtendedCareCharge, ok_id).status == ExtendedCareChargeStatus.confirmed
            assert session.get(ExtendedCareCharge, late_id).status == ExtendedCareChargeStatus.draft
            assert session.get(ExtendedCareCharge, zero_id).status == ExtendedCareChargeStatus.draft
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()
