"""請求締め解除の段階化（フェーズB B1）のテスト。

- estimate_reopen_delta の L0/L1 分類（dry-run 差額試算）
- L1 の園長確認申請（request / withdraw / approve）と承認スタンプ
- 理由のバリデーション（定型+補足必須、500字）
- ルート: L0 直接解除 / L1 非adminは申請のみ / admin 自己承認スキップ / 権限不足
"""
from __future__ import annotations

import unittest
from datetime import date
from uuid import UUID

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from fastapi import FastAPI
from fastapi.testclient import TestClient

from testing_helpers import (
    DEFAULT_TEST_STAFF_ID,
    Role,
    authenticate_mock_staff,
    configure_test_environment,
)

EXPORTER_STAFF_ID = UUID("00000000-0000-0000-0000-000000000002")
DIRECTOR_STAFF_ID = DEFAULT_TEST_STAFF_ID

OTHER_REASON = "テスト補足"


def _build_engine():
    import models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _seed_export(
    session: Session,
    *,
    meal_amount: int = 4500,
    extension_amount: int = 1000,
    claim_total: int | None = None,
    status="created",
    submitted: bool = False,
):
    """出力済みサイクル（1世帯・2明細）を作り、ZenginExport を返す。"""
    from time_utils import utc_now

    from models import (
        BillingChargeLine,
        BillingClaim,
        BillingClaimStatus,
        BillingCycle,
        BillingCycleStatus,
        BillingChargeSourceType,
        BillingPaymentMethod,
        Family,
        FeeItem,
        ZenginExport,
        ZenginExportLine,
        ZenginExportStatus,
    )

    family = Family(family_name="山田")
    session.add(family)
    session.flush()

    fee_meal = FeeItem(code="MEAL", name="給食費", category="meal", charge_unit="month")
    fee_ext = FeeItem(code="EXT", name="延長保育料", category="extension", charge_unit="month")
    session.add(fee_meal)
    session.add(fee_ext)
    session.flush()

    cycle = BillingCycle(
        year_month="2026-10",
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        withdrawal_date=date(2026, 11, 26),
        status=BillingCycleStatus.exported,
    )
    session.add(cycle)
    session.flush()

    total = (claim_total if claim_total is not None else meal_amount + extension_amount)
    claim = BillingClaim(
        billing_cycle_id=cycle.id,
        family_id=family.id,
        payment_method=BillingPaymentMethod.direct_debit,
        total_amount=total,
        status=BillingClaimStatus.exported,
    )
    session.add(claim)
    session.flush()

    export = ZenginExport(
        billing_cycle_id=cycle.id,
        withdrawal_date=cycle.withdrawal_date,
        file_name="zengin_202610.txt",
        total_count=1,
        total_amount=total,
        status=ZenginExportStatus(status),
        content_hash="hash-" + status,
        created_by="テスト職員",
    )
    session.add(export)
    session.flush()

    claim.zengin_export_id = export.id
    claim.exported_at = utc_now()
    session.add(claim)
    session.flush()

    line_meal = BillingChargeLine(
        billing_claim_id=claim.id,
        fee_item_id=fee_meal.id,
        source_type=BillingChargeSourceType.meal_auto,
        description="給食費",
        amount=meal_amount,
        unit_price=meal_amount,
        quantity=1,
    )
    line_ext = BillingChargeLine(
        billing_claim_id=claim.id,
        fee_item_id=fee_ext.id,
        source_type=BillingChargeSourceType.extension_auto,
        description="延長保育料",
        amount=extension_amount,
        unit_price=extension_amount,
        quantity=1,
    )
    session.add(line_meal)
    session.add(line_ext)

    session.add(ZenginExportLine(
        zengin_export_id=export.id,
        billing_claim_id=claim.id,
        family_id=family.id,
        customer_number="CUST-001",
        amount=total,
    ))
    if submitted:
        from time_utils import utc_now

        export.submitted_at = utc_now()
    session.commit()
    session.refresh(export)
    return export


def _set_line_amounts(session: Session, export: "ZenginExport", meal_amount: int, extension_amount: int):
    """明細行だけを変更して差額（L1）を作る。"""
    from models import BillingChargeLine

    claim_id = session.exec(select_stmt(session, export)).first()
    lines = session.exec(select(BillingChargeLine).where(
        BillingChargeLine.billing_claim_id == claim_id)).all()
    amounts = {"給食費": meal_amount, "延長保育料": extension_amount}
    for line in lines:
        line.amount = amounts[line.description]
    session.add_all(lines)
    session.commit()


def select_stmt(session: Session, export):
    from models import BillingClaim

    return select(BillingClaim.id).where(BillingClaim.billing_cycle_id == export.billing_cycle_id)


class EstimateReopenDeltaTests(unittest.TestCase):
    """estimate_reopen_delta の L0/L1 分類。"""

    def setUp(self):
        self.engine = _build_engine()

    def test_no_diff_is_l0(self):
        from zengin_service import estimate_reopen_delta

        with Session(self.engine) as session:
            export = _seed_export(session)
            result = estimate_reopen_delta(session, export.id)
        self.assertEqual(result["level"], "L0")
        self.assertEqual(result["delta_amount"], 0)
        self.assertEqual(result["delta_count"], 0)
        self.assertEqual(result["changed_claims"], 0)

    def test_changed_line_is_l1(self):
        from zengin_service import estimate_reopen_delta

        with Session(self.engine) as session:
            export = _seed_export(session)
            _set_line_amounts(session, export, meal_amount=5000, extension_amount=1000)
            result = estimate_reopen_delta(session, export.id)
        self.assertEqual(result["level"], "L1")
        self.assertEqual(result["delta_amount"], 500)
        self.assertEqual(result["changed_claims"], 1)

    def test_zero_total_claim_excluded_from_estimate(self):
        from zengin_service import estimate_reopen_delta

        with Session(self.engine) as session:
            export = _seed_export(session)
            _set_line_amounts(session, export, meal_amount=0, extension_amount=0)
            result = estimate_reopen_delta(session, export.id)
        self.assertEqual(result["level"], "L1")
        self.assertEqual(result["estimated_count"], 0)
        self.assertEqual(result["delta_amount"], -5500)


class ReopenReasonValidationTests(unittest.TestCase):
    """理由のバリデーション（定型+補足必須）。"""

    def setUp(self):
        self.engine = _build_engine()

    def test_template_only_is_accepted(self):
        from zengin_service import combine_reopen_reason

        self.assertEqual(
            combine_reopen_reason(["打刻漏れ", "その他"], ""),
            "打刻漏れ、その他",
        )

    def test_other_template_requires_free_text(self):
        from zengin_service import ZenginError, request_reopen_confirm

        with Session(self.engine) as session:
            export = _seed_export(session)
            estimate = {"estimated_amount": 5500, "estimated_count": 1, "delta_amount": 0}
            with self.assertRaises(ZenginError):
                request_reopen_confirm(
                    session, export.id, reason="", reason_templates=["その他"],
                    confirmed_unsubmitted=True, requested_by="田中", estimate=estimate,
                )

    def test_no_reason_rejected(self):
        from zengin_service import ZenginError, request_reopen_confirm

        with Session(self.engine) as session:
            export = _seed_export(session)
            estimate = {"estimated_amount": 5500, "estimated_count": 1, "delta_amount": 0}
            with self.assertRaises(ZenginError):
                request_reopen_confirm(
                    session, export.id, reason="", reason_templates=[],
                    confirmed_unsubmitted=True, requested_by="田中", estimate=estimate,
                )

    def test_free_reason_over_500_rejected(self):
        from zengin_service import REOPEN_REASON_MAX, ZenginError, request_reopen_confirm

        with Session(self.engine) as session:
            export = _seed_export(session)
            estimate = {"estimated_amount": 5500, "estimated_count": 1, "delta_amount": 0}
            with self.assertRaises(ZenginError):
                request_reopen_confirm(
                    session, export.id, reason="あ" * (REOPEN_REASON_MAX + 1),
                    reason_templates=[], confirmed_unsubmitted=True,
                    requested_by="田中", estimate=estimate,
                )

    def test_unsubmitted_check_required_for_request(self):
        from zengin_service import ZenginError, request_reopen_confirm

        with Session(self.engine) as session:
            export = _seed_export(session)
            estimate = {"estimated_amount": 5500, "estimated_count": 1, "delta_amount": 0}
            with self.assertRaises(ZenginError):
                request_reopen_confirm(
                    session, export.id, reason="打刻漏れの修正", reason_templates=[],
                    confirmed_unsubmitted=False, requested_by="田中", estimate=estimate,
                )


class ReopenRequestLifecycleTests(unittest.TestCase):
    """申請 → 承認/取り消し のライフサイクルとスタンプ。"""

    def setUp(self):
        self.engine = _build_engine()

    def _request(self, session, export):
        from zengin_service import request_reopen_confirm

        return request_reopen_confirm(
            session, export.id, reason="写真代の訂正",
            reason_templates=["項目誤入力"], confirmed_unsubmitted=True,
            requested_by="田中 主任",
            estimate={"estimated_amount": 6000, "estimated_count": 1, "delta_amount": 500},
        )

    def test_request_and_withdraw(self):
        from zengin_service import has_pending_reopen_confirm, withdraw_reopen_request

        with Session(self.engine) as session:
            export = _seed_export(session)
            self._request(session, export)
            session.refresh(export)
            self.assertTrue(has_pending_reopen_confirm(export))
            self.assertEqual(export.reopen_confirm_requested_by, "田中 主任")
            self.assertEqual(export.reopen_confirm_payload["delta_amount"], 500)
            self.assertEqual(export.reopen_confirm_payload["reason_templates"], ["項目誤入力"])
            withdraw_reopen_request(session, export.id)
            session.refresh(export)
            self.assertFalse(has_pending_reopen_confirm(export))
            self.assertIsNone(export.reopen_confirm_payload)

    def test_withdraw_without_request_raises(self):
        from zengin_service import ZenginError, withdraw_reopen_request

        with Session(self.engine) as session:
            export = _seed_export(session)
            with self.assertRaises(ZenginError):
                withdraw_reopen_request(session, export.id)

    def test_approve_cancels_with_stamped_columns(self):
        from models import BillingClaimStatus
        from zengin_service import approve_reopen_and_cancel, has_pending_reopen_confirm

        with Session(self.engine) as session:
            export = _seed_export(session)
            self._request(session, export)
            export = approve_reopen_and_cancel(
                session, export.id, approved_by="園長 佐藤", confirmed_unsubmitted=True,
            )
            self.assertEqual(export.status.value, "canceled")
            self.assertEqual(export.reopen_confirm_by, "園長 佐藤")
            self.assertIsNotNone(export.reopen_confirm_at)
            self.assertEqual(export.canceled_by, "田中 主任")
            self.assertIn("項目誤入力", export.canceled_reason)
            self.assertIn("写真代の訂正", export.canceled_reason)
            claim = session.exec(_claim_select(session, export)).first()
            self.assertEqual(claim.status, BillingClaimStatus.confirmed)
            self.assertIsNone(claim.zengin_export_id)

    def test_double_approval_is_rejected(self):
        from zengin_service import ZenginError, approve_reopen_and_cancel

        with Session(self.engine) as session:
            export = _seed_export(session)
            self._request(session, export)
            approve_reopen_and_cancel(
                session, export.id, approved_by="園長 佐藤", confirmed_unsubmitted=True,
            )
            with self.assertRaises(ZenginError):
                approve_reopen_and_cancel(
                    session, export.id, approved_by="園長 佐藤", confirmed_unsubmitted=True,
                )

    def test_approve_without_pending_raises(self):
        from zengin_service import ZenginError, approve_reopen_and_cancel

        with Session(self.engine) as session:
            export = _seed_export(session)
            with self.assertRaises(ZenginError):
                approve_reopen_and_cancel(
                    session, export.id, approved_by="園長 佐藤", confirmed_unsubmitted=True,
                )

    def test_submitted_export_cannot_request(self):
        from zengin_service import ZenginError, request_reopen_confirm

        with Session(self.engine) as session:
            export = _seed_export(session, submitted=True)
            estimate = {"estimated_amount": 6000, "estimated_count": 1, "delta_amount": 500}
            with self.assertRaises(ZenginError):
                request_reopen_confirm(
                    session, export.id, reason="修正", reason_templates=["打刻漏れ"],
                    confirmed_unsubmitted=True, requested_by="田中", estimate=estimate,
                )

    def test_l1_direct_cancel_by_admin_stamps_approval(self):
        from zengin_service import cancel_zengin_export_for_edit

        with Session(self.engine) as session:
            export = _seed_export(session)
            export = cancel_zengin_export_for_edit(
                session, export.id, reason="写真代の訂正", confirmed_unsubmitted=True,
                canceled_by="園長 佐藤", approved_by="園長 佐藤",
            )
            self.assertEqual(export.reopen_confirm_by, "園長 佐藤")
            self.assertIsNotNone(export.reopen_confirm_at)


def _claim_select(session: Session, export):
    from models import BillingClaim

    return select(BillingClaim).where(BillingClaim.billing_cycle_id == export.billing_cycle_id)


class BillingReopenRouteTests(unittest.TestCase):
    """ルート: L0 直接解除 / L1 非adminは申請 / admin 自己承認 / 権限不足。"""

    def setUp(self):
        import routers.billing as billing_module
        from auth import get_current_staff_user

        self.billing_module = billing_module
        self.engine = _build_engine()
        configure_test_environment()

        self.app = FastAPI()
        self.app.include_router(billing_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[billing_module.get_session] = override_get_session
        self.client = TestClient(self.app, follow_redirects=False)

    def _seed_staff(self, *, admin: bool = False):
        from models import User

        staff_id = DIRECTOR_STAFF_ID if admin else EXPORTER_STAFF_ID
        with Session(self.engine) as session:
            session.add(User(
                id=staff_id,
                email=f"staff-{staff_id.hex[:8]}@example.test",
                display_name="園長" if admin else "主任",
                staff_role="admin" if admin else "can_edit",
                can_export_zengin=True,
            ))
            session.commit()

    def _export(self):
        with Session(self.engine) as session:
            return _seed_export(session)

    def test_l0_direct_cancel_by_exporter(self):
        from models import ZenginExport, ZenginExportStatus

        self._seed_staff()
        export = self._export()
        authenticate_mock_staff(self.client, role=Role.CAN_EDIT, user_id=EXPORTER_STAFF_ID, name="田中 主任")
        response = self.client.post(
            f"/billing/zengin/exports/{export.id}/cancel-ui",
            data={"reason": "打刻漏れの修正", "confirmed_unsubmitted": "true"},
        )
        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            row = session.get(ZenginExport, export.id)
            self.assertEqual(row.status, ZenginExportStatus.canceled)
            self.assertEqual(row.canceled_by, "田中 主任")

    def test_l1_by_exporter_creates_request_not_cancel(self):
        from models import ZenginExport, ZenginExportStatus
        from zengin_service import has_pending_reopen_confirm

        self._seed_staff()
        export = self._export()
        with Session(self.engine) as session:
            _set_line_amounts(session, export, meal_amount=5000, extension_amount=1000)
        authenticate_mock_staff(self.client, role=Role.CAN_EDIT, user_id=EXPORTER_STAFF_ID, name="田中 主任")
        response = self.client.post(
            f"/billing/zengin/exports/{export.id}/cancel-ui",
            data={"reason": "写真代の訂正", "reason_tpl": "項目誤入力", "confirmed_unsubmitted": "true"},
        )
        self.assertEqual(response.status_code, 303)
        from urllib.parse import unquote

        self.assertIn("園長確認", unquote(response.headers["location"]))
        with Session(self.engine) as session:
            row = session.get(ZenginExport, export.id)
            self.assertEqual(row.status, ZenginExportStatus.created)
            self.assertTrue(has_pending_reopen_confirm(row))
            self.assertEqual(row.reopen_confirm_requested_by, "田中 主任")

    def test_l1_by_admin_cancels_directly_with_stamp(self):
        from models import ZenginExport, ZenginExportStatus

        self._seed_staff(admin=True)
        export = self._export()
        with Session(self.engine) as session:
            _set_line_amounts(session, export, meal_amount=5000, extension_amount=1000)
        authenticate_mock_staff(self.client, role=Role.ADMIN, user_id=DIRECTOR_STAFF_ID, name="園長 佐藤")
        response = self.client.post(
            f"/billing/zengin/exports/{export.id}/cancel-ui",
            data={"reason": "免除の変更", "confirmed_unsubmitted": "true"},
        )
        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            row = session.get(ZenginExport, export.id)
            self.assertEqual(row.status, ZenginExportStatus.canceled)
            self.assertEqual(row.reopen_confirm_by, "園長 佐藤")

    def test_approve_route_requires_admin(self):
        self._seed_staff()
        export = self._export()
        authenticate_mock_staff(self.client, role=Role.CAN_EDIT, user_id=EXPORTER_STAFF_ID, name="田中 主任")
        response = self.client.post(
            f"/billing/zengin/exports/{export.id}/reopen-approve-ui",
            data={"confirmed_unsubmitted": "true"},
        )
        self.assertEqual(response.status_code, 403)

    def test_approve_route_without_pending_redirects_with_error(self):
        self._seed_staff(admin=True)
        export = self._export()
        authenticate_mock_staff(self.client, role=Role.ADMIN, user_id=DIRECTOR_STAFF_ID, name="園長 佐藤")
        response = self.client.post(
            f"/billing/zengin/exports/{export.id}/reopen-approve-ui",
            data={"confirmed_unsubmitted": "true"},
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("error=", response.headers["location"])

    def test_approve_route_cancels_pending_request(self):
        from models import ZenginExport, ZenginExportStatus
        from zengin_service import request_reopen_confirm

        self._seed_staff(admin=True)
        export = self._export()
        with Session(self.engine) as session:
            _set_line_amounts(session, export, meal_amount=5000, extension_amount=1000)
            request_reopen_confirm(
                session, export.id, reason="写真代の訂正", reason_templates=["項目誤入力"],
                confirmed_unsubmitted=True, requested_by="田中 主任",
                estimate={"estimated_amount": 6000, "estimated_count": 1, "delta_amount": 500},
            )
        authenticate_mock_staff(self.client, role=Role.ADMIN, user_id=DIRECTOR_STAFF_ID, name="園長 佐藤")
        response = self.client.post(
            f"/billing/zengin/exports/{export.id}/reopen-approve-ui",
            data={"confirmed_unsubmitted": "true"},
        )
        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            row = session.get(ZenginExport, export.id)
            self.assertEqual(row.status, ZenginExportStatus.canceled)
            self.assertEqual(row.reopen_confirm_by, "園長 佐藤")
            self.assertIn("項目誤入力", row.canceled_reason)

    def test_requester_can_withdraw_own_request(self):
        from models import ZenginExport
        from zengin_service import has_pending_reopen_confirm, request_reopen_confirm

        self._seed_staff()
        export = self._export()
        with Session(self.engine) as session:
            _set_line_amounts(session, export, meal_amount=5000, extension_amount=1000)
            request_reopen_confirm(
                session, export.id, reason="写真代の訂正", reason_templates=["項目誤入力"],
                confirmed_unsubmitted=True, requested_by="田中 主任",
                estimate={"estimated_amount": 6000, "estimated_count": 1, "delta_amount": 500},
            )
        authenticate_mock_staff(self.client, role=Role.CAN_EDIT, user_id=EXPORTER_STAFF_ID, name="田中 主任")
        response = self.client.post(f"/billing/zengin/exports/{export.id}/reopen-request-cancel-ui")
        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            row = session.get(ZenginExport, export.id)
            self.assertFalse(has_pending_reopen_confirm(row))

    def test_without_zengin_permission_is_403(self):
        from models import User

        with Session(self.engine) as session:
            session.add(User(
                id=EXPORTER_STAFF_ID,
                email="no-perm@example.test",
                display_name="権限なし",
                staff_role="can_edit",
                can_export_zengin=False,
            ))
            session.commit()
        export = self._export()
        authenticate_mock_staff(self.client, role=Role.CAN_EDIT, user_id=EXPORTER_STAFF_ID, name="権限なし")
        response = self.client.post(
            f"/billing/zengin/exports/{export.id}/cancel-ui",
            data={"reason": "修正", "confirmed_unsubmitted": "true"},
        )
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
