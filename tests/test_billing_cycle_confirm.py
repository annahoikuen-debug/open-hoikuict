"""請求サイクル確定時の請求明細(BillingClaim)連動テスト (Phase 1 #1)。"""
from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import child_records.models  # noqa: F401
from auth import Role, StaffUser, get_current_staff_user
from database import get_session
from models import (
    BillingClaim,
    BillingClaimStatus,
    BillingCycle,
    BillingCycleStatus,
    BillingPaymentMethod,
    Family,
    User,
)
from routers.billing import router as billing_router


def test_confirm_and_unconfirm_cycle_syncs_claims() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        admin = User(
            display_name="テスト園長",
            email="test-admin@example.com",
            staff_role="admin",
            is_active=True,
        )
        family = Family(family_name="テスト世帯")
        session.add(admin)
        session.add(family)
        session.flush()

        cycle = BillingCycle(
            year_month="2099-12",
            period_start=date(2099, 12, 1),
            period_end=date(2099, 12, 31),
            withdrawal_date=date(2100, 1, 27),
            due_date=date(2100, 1, 27),
            status=BillingCycleStatus.generated,
        )
        session.add(cycle)
        session.flush()

        claim = BillingClaim(
            billing_cycle_id=cycle.id,
            family_id=family.id,
            payment_method=BillingPaymentMethod.direct_debit,
            total_amount=3000,
            status=BillingClaimStatus.draft,
        )
        session.add(claim)
        session.commit()
        cycle_id, claim_id, admin_id = cycle.id, claim.id, admin.id

    test_app = FastAPI()
    test_app.include_router(billing_router)

    def _override_session():
        with Session(engine) as session:
            yield session

    test_app.dependency_overrides[get_session] = _override_session
    test_app.dependency_overrides[get_current_staff_user] = lambda: StaffUser(
        role=Role.ADMIN,
        name="テスト園長",
        user_id=admin_id,
    )

    try:
        with TestClient(test_app) as client:
            r_conf = client.post(f"/billing/cycles/{cycle_id}/confirm")
            assert r_conf.status_code == 200
            body = r_conf.json()
            assert body["status"] == "confirmed"
            assert body["confirmed_claims_count"] == 1

            with Session(engine) as session:
                updated_claim = session.get(BillingClaim, claim_id)
                assert updated_claim is not None
                assert updated_claim.status == BillingClaimStatus.confirmed

            r_unconf = client.post(f"/billing/cycles/{cycle_id}/unconfirm")
            assert r_unconf.status_code == 200
            unconf_body = r_unconf.json()
            assert unconf_body["status"] == "generated"
            assert unconf_body["reverted_claims_count"] == 1

            with Session(engine) as session:
                reverted_claim = session.get(BillingClaim, claim_id)
                assert reverted_claim is not None
                assert reverted_claim.status == BillingClaimStatus.draft
    finally:
        test_app.dependency_overrides.clear()
        engine.dispose()
