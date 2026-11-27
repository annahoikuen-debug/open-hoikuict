from __future__ import annotations

from datetime import date
import uuid
from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from auth import Role
from database import engine
from main import app
from models import (
    BillingClaim,
    BillingClaimStatus,
    BillingCycle,
    BillingCycleStatus,
    BillingPaymentMethod,
    Child,
    Family,
    User,
)
from testing_helpers import authenticate_mock_staff


def test_offline_sync_queue_script_exists() -> None:
    """施策 2-4: オフライン同期キュー JS が配置されていること。"""
    js_path = Path(__file__).resolve().parent.parent / "static" / "js" / "offline-sync-queue.js"
    assert js_path.exists()
    content = js_path.read_text(encoding="utf-8")
    assert "HoikuOfflineQueue" in content
    assert "idempotency_key" in content


def test_billing_preflight_detects_draft_claims() -> None:
    """施策 2-5: 請求プレフライトAPIが draft 残存を検知し can_export=False を返すこと。"""
    with Session(engine) as session:
        admin_user = User(
            username=f"bill_admin_{uuid.uuid4().hex[:8]}",
            display_name="経理管理者",
            email=f"bill_admin_{uuid.uuid4().hex[:8]}@example.test",
            role="admin",
            staff_role="admin",
            can_manage_billing_accounts=True,
            is_active=True,
        )
        session.add(admin_user)

        family = Family(family_name="プレフライトテスト家")
        session.add(family)
        session.commit()
        session.refresh(admin_user)
        session.refresh(family)

        child = Child(
            family_id=family.id,
            last_name="テスト",
            first_name="太郎",
            last_name_kana="てすと",
            first_name_kana="たろう",
            birth_date=date(2023, 4, 1),
            enrollment_date=date(2024, 4, 1),
        )
        session.add(child)
        session.commit()
        session.refresh(child)

        cycle = BillingCycle(
            year_month=f"2099-{uuid.uuid4().int % 12 + 1:02d}",
            period_start=date(2099, 1, 1),
            period_end=date(2099, 1, 31),
            withdrawal_date=date(2099, 2, 27),
            due_date=date(2099, 2, 27),
            status=BillingCycleStatus.draft,
        )
        session.add(cycle)
        session.commit()
        session.refresh(cycle)

        claim = BillingClaim(
            billing_cycle_id=cycle.id,
            family_id=family.id,
            payment_method=BillingPaymentMethod.direct_debit,
            status=BillingClaimStatus.draft,
            total_amount=5000,
        )
        session.add(claim)
        session.commit()

        admin_id = admin_user.id
        cycle_id = cycle.id

    client = TestClient(app)
    authenticate_mock_staff(client, role=Role.ADMIN, user_id=admin_id, name="経理管理者")
    res = client.get(f"/billing/cycles/{cycle_id}/preflight")
    assert res.status_code == 200
    data = res.json()
    assert data["draft_claims_count"] == 1
    assert data["can_export"] is False
