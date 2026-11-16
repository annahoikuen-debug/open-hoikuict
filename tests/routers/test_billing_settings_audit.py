"""Wave C コドモン課題対応（P8-1, P8-2, P8-3, P8-4, P8-5）のテスト。

- P8-1: 料金マスタ (FeeItem) のCRUD操作、全銀口座振替設定 (BillingSetting)
- P8-2: 月途中入退園の実開園平日日数に基づく自動日割り算定
- P8-3: 園児ごとの減免・免除登録 (BillingExemption) と減免計算
- P8-4: 口座振替不能（残高不足等）の翌月サイクル繰越
- P8-5: 請求確定前自動検算レポート (0円請求、繰越、減免期限満了、不一致の検出)
"""
import unittest
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from models import (
    BillingChargeLine,
    BillingChargeSourceType,
    BillingClaim,
    BillingClaimStatus,
    BillingCycle,
    BillingCycleStatus,
    BillingExemption,
    BillingPaymentMethod,
    BillingSetting,
    Child,
    ChildStatus,
    ExemptionType,
    Family,
    FeeItem,
    User,
)
import routers.billing as billing_router_module
from routers.billing import (
    apply_child_exemptions,
    audit_billing_cycle,
    calculate_prorated_meal_fee,
)


class BillingSettingsAndAuditTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            self.admin_id = self._create_admin_user(session)
            session.commit()
        self.current_user = StaffUser(role=Role.ADMIN, name="園長", user_id=self.admin_id)

    def tearDown(self):
        self.engine.dispose()

    def _create_admin_user(self, session):
        admin = User(
            email="billing-admin@example.com",
            display_name="園長",
            staff_role="admin",
            can_export_zengin=True,
        )
        session.add(admin)
        session.flush()
        return admin.id

    def _create_test_client(self):
        app = FastAPI()
        app.include_router(billing_router_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_get_current_staff_user():
            return self.current_user

        app.dependency_overrides[billing_router_module.get_session] = override_get_session
        app.dependency_overrides[billing_router_module.get_current_staff_user] = override_get_current_staff_user
        return TestClient(app)

    # ==========================================
    # P8-1: 料金マスタ CRUD & 全銀設定
    # ==========================================

    def test_fee_item_crud_and_settings_page(self):
        """料金マスタ一覧の表示、新規追加、編集ができること (P8-1)。"""
        client = self._create_test_client()

        # 1. 初期設定画面表示
        resp = client.get("/billing/settings")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("料金マスタ・全銀口座振替・減免設定", resp.text)

        # 2. 料金項目の新規登録
        add_resp = client.post(
            "/billing/settings/fee-items",
            data={
                "code": "test_photo",
                "name": "写真代（遠足）",
                "category": "other",
                "charge_unit": "piece",
                "default_amount": 150,
                "taxable_type": "taxable",
                "display_order": 50,
            },
            follow_redirects=True,
        )
        self.assertEqual(add_resp.status_code, 200)
        self.assertIn("写真代（遠足）", add_resp.text)

        with Session(self.engine) as session:
            item = session.exec(select(FeeItem).where(FeeItem.code == "test_photo")).first()
            self.assertIsNotNone(item)
            self.assertEqual(item.default_amount, 150)
            item_id = item.id

        # 重複コードのエラー
        dup_resp = client.post(
            "/billing/settings/fee-items",
            data={
                "code": "test_photo",
                "name": "写真代重複",
                "category": "other",
                "charge_unit": "piece",
                "default_amount": 200,
                "taxable_type": "taxable",
                "display_order": 50,
            },
        )
        self.assertEqual(dup_resp.status_code, 400)

        # 3. 料金項目の編集
        edit_resp = client.post(
            f"/billing/settings/fee-items/{item_id}/edit",
            data={
                "name": "写真代（運動会）",
                "default_amount": 200,
                "taxable_type": "non_taxable",
                "is_active": "true",
                "display_order": 60,
            },
            follow_redirects=True,
        )
        self.assertEqual(edit_resp.status_code, 200)
        with Session(self.engine) as session:
            updated = session.get(FeeItem, item_id)
            self.assertEqual(updated.name, "写真代（運動会）")
            self.assertEqual(updated.default_amount, 200)

    def test_zengin_setting_update(self):
        """全銀口座振替設定が更新できること (P8-1)。"""
        client = self._create_test_client()

        resp = client.post(
            "/billing/settings/zengin",
            data={
                "facility_name": "ひまわり保育園",
                "collector_code": "9876543210",
                "collector_name_kana": "ﾋﾏﾜﾘﾎｲｸｴﾝ",
                "withdrawal_bank_code": "0005",
                "withdrawal_branch_code": "456",
                "collector_account_type": "1",
                "collector_account_number": "7654321",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("全銀設定を更新しました", resp.text)

        with Session(self.engine) as session:
            setting = session.exec(select(BillingSetting)).first()
            self.assertEqual(setting.facility_name, "ひまわり保育園")
            self.assertEqual(setting.collector_code, "9876543210")
            self.assertEqual(setting.collector_name_kana, "ﾋﾏﾜﾘﾎｲｸｴﾝ")

    # ==========================================
    # P8-2: 月途中入退園の実開園平日日数による自動日割り
    # ==========================================

    def test_calculate_prorated_meal_fee(self):
        """月途中入退園の実開園平日日数に基づく日割り給食費の算定 (P8-2)。"""
        # 2026年11月: 11/1(日) 〜 11/30(月)。
        # 平日数は 21日。
        start_date = date(2026, 11, 1)
        end_date = date(2026, 11, 30)

        # 1. 全期間在園: 満額 5,500円
        fee, enrolled_days, total_days = calculate_prorated_meal_fee(
            full_amount=5500,
            start_date=start_date,
            end_date=end_date,
            enrollment_date=date(2026, 4, 1),
            withdrawal_date=None,
        )
        self.assertEqual(fee, 5500)
        self.assertEqual(enrolled_days, total_days)

        # 2. 途中入園: 2026/11/16 入園
        # 11/16(月) 〜 11/30(月) の平日数は 11日
        fee_in, enrolled_days_in, total_days_in = calculate_prorated_meal_fee(
            full_amount=5500,
            start_date=start_date,
            end_date=end_date,
            enrollment_date=date(2026, 11, 16),
            withdrawal_date=None,
        )
        # 5500 * 11 / 21 = 2880.95... -> 四捨五入で 2881
        expected = int(round(5500 * enrolled_days_in / total_days_in))
        self.assertEqual(fee_in, expected)
        self.assertEqual(enrolled_days_in, 11)
        self.assertEqual(total_days_in, 21)

        # 3. 途中退園: 2026/11/10 退園
        # 11/1 〜 11/10 の平日数は 7日 (11/2, 11/3, 11/4, 11/5, 11/6, 11/9, 11/10)
        fee_out, enrolled_days_out, total_days_out = calculate_prorated_meal_fee(
            full_amount=5500,
            start_date=start_date,
            end_date=end_date,
            enrollment_date=date(2026, 4, 1),
            withdrawal_date=date(2026, 11, 10),
        )
        expected_out = int(round(5500 * 7 / 21))
        self.assertEqual(fee_out, expected_out)
        self.assertEqual(enrolled_days_out, 7)

    # ==========================================
    # P8-3: 園児ごとの減免・免除登録 & 減免計算
    # ==========================================

    def test_exemption_registration_and_calculation(self):
        """減免・免除登録の追加・削除と減免額の算定 (P8-3)。"""
        client = self._create_test_client()

        with Session(self.engine) as session:
            child = Child(
                first_name="結衣",
                last_name="高橋",
                first_name_kana="ユイ",
                last_name_kana="タカハシ",
                birth_date=date(2022, 5, 1),
                enrollment_date=date(2025, 4, 1),
                status=ChildStatus.enrolled,
            )
            session.add(child)
            session.commit()
            child_id = child.id

        # 1. 減免登録 (全額免除)
        resp = client.post(
            "/billing/settings/exemptions",
            data={
                "child_id": child_id,
                "name": "第3子全額免除",
                "exemption_type": "full",
                "valid_from": "2026-04-01",
                "valid_to": "2027-03-31",
                "reason": "多子世帯減免認定",
            },
            follow_redirects=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("第3子全額免除", resp.text)

        with Session(self.engine) as session:
            ex = session.exec(select(BillingExemption).where(BillingExemption.child_id == child_id)).first()
            self.assertIsNotNone(ex)
            self.assertEqual(ex.exemption_type, ExemptionType.full)
            ex_id = ex.id

            # 計算ヘルパーの検証 (全額免除)
            discounted, note = apply_child_exemptions(
                session,
                child_id=child_id,
                fee_item_id=None,
                original_amount=5500,
                target_date=date(2026, 11, 1),
            )
            self.assertEqual(discounted, 0)
            self.assertIn("第3子全額免除", note)

            # 適用期間外の検証
            discounted_out, _ = apply_child_exemptions(
                session,
                child_id=child_id,
                fee_item_id=None,
                original_amount=5500,
                target_date=date(2027, 5, 1),
            )
            self.assertEqual(discounted_out, 5500)

        # 2. 定額減額 (-¥4,500) の検証
        with Session(self.engine) as session:
            # 既存を更新して定額減額に
            ex_obj = session.get(BillingExemption, ex_id)
            ex_obj.exemption_type = ExemptionType.fixed_discount
            ex_obj.discount_amount = 4500
            session.add(ex_obj)
            session.commit()

            discounted_fixed, note_fixed = apply_child_exemptions(
                session,
                child_id=child_id,
                fee_item_id=None,
                original_amount=5500,
                target_date=date(2026, 11, 1),
            )
            self.assertEqual(discounted_fixed, 1000)
            self.assertIn("-¥4,500", note_fixed)

        # 3. 減免登録の削除
        del_resp = client.post(f"/billing/settings/exemptions/{ex_id}/delete", follow_redirects=True)
        self.assertEqual(del_resp.status_code, 200)
        with Session(self.engine) as session:
            deleted_ex = session.get(BillingExemption, ex_id)
            self.assertIsNone(deleted_ex)

    # ==========================================
    # P8-4: 振替不能の翌月繰越
    # ==========================================

    def test_carryover_unpaid_claim(self):
        """振替不能となった未収明細を翌月サイクルに繰り越せること (P8-4)。"""
        client = self._create_test_client()

        with Session(self.engine) as session:
            family = Family(family_name="鈴木家")
            session.add(family)
            session.flush()

            # 10月サイクル (確定済み)
            cycle_10 = BillingCycle(
                year_month="2026-10",
                period_start=date(2026, 10, 1),
                period_end=date(2026, 10, 31),
                withdrawal_date=date(2026, 11, 27),
                status=BillingCycleStatus.confirmed,
            )
            # 11月サイクル (生成済み・未確定)
            cycle_11 = BillingCycle(
                year_month="2026-11",
                period_start=date(2026, 11, 1),
                period_end=date(2026, 11, 30),
                withdrawal_date=date(2026, 12, 27),
                status=BillingCycleStatus.generated,
            )
            session.add(cycle_10)
            session.add(cycle_11)
            session.flush()

            # 10月分の未収請求 (7,300円)
            claim_10 = BillingClaim(
                billing_cycle_id=cycle_10.id,
                family_id=family.id,
                claim_number="CLAIM-2026-10-0001",
                total_amount=7300,
                status=BillingClaimStatus.failed,
                payment_method=BillingPaymentMethod.direct_debit,
            )
            session.add(claim_10)
            session.commit()
            claim_10_id = claim_10.id
            cycle_11_id = cycle_11.id
            family_id = family.id

        # 繰越 API の呼び出し
        resp = client.post(f"/billing/claims/{claim_10_id}/carryover")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["carried_amount"], 7300)
        self.assertEqual(data["next_cycle_year_month"], "2026-11")

        # 翌月サイクルの請求明細に繰越行が追加されていること
        with Session(self.engine) as session:
            claim_11 = session.exec(
                select(BillingClaim).where(
                    BillingClaim.billing_cycle_id == cycle_11_id,
                    BillingClaim.family_id == family_id,
                )
            ).first()
            self.assertIsNotNone(claim_11)
            self.assertEqual(claim_11.total_amount, 7300)

            lines = session.exec(
                select(BillingChargeLine).where(BillingChargeLine.billing_claim_id == claim_11.id)
            ).all()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].source_type, BillingChargeSourceType.manual)
            self.assertIn("2026-10分 振替不能分繰越", lines[0].description)

    # ==========================================
    # P8-5: 確定前自動検算レポート (Audit)
    # ==========================================

    def test_audit_billing_cycle(self):
        """確定前自動検算で不一致エラー、0円警告、繰越情報、減免満了情報が正しく抽出されること (P8-5)。"""
        client = self._create_test_client()

        with Session(self.engine) as session:
            family_a = Family(family_name="田中家")
            family_b = Family(family_name="佐藤家")
            session.add(family_a)
            session.add(family_b)
            session.flush()

            cycle = BillingCycle(
                year_month="2026-11",
                period_start=date(2026, 11, 1),
                period_end=date(2026, 11, 30),
                withdrawal_date=date(2026, 12, 27),
                status=BillingCycleStatus.generated,
            )
            session.add(cycle)
            session.flush()

            # 正常な請求 (5,000円)
            claim_a = BillingClaim(
                billing_cycle_id=cycle.id,
                family_id=family_a.id,
                claim_number="CLAIM-2026-11-0001",
                total_amount=5000,
                status=BillingClaimStatus.draft,
                payment_method=BillingPaymentMethod.direct_debit,
            )
            # 0円請求世帯 (全額免除等)
            claim_b = BillingClaim(
                billing_cycle_id=cycle.id,
                family_id=family_b.id,
                claim_number="CLAIM-2026-11-0002",
                total_amount=0,
                status=BillingClaimStatus.draft,
                payment_method=BillingPaymentMethod.direct_debit,
            )
            session.add(claim_a)
            session.add(claim_b)
            session.flush()

            fee_item = FeeItem(code="meal_test", name="給食費", category="meal", charge_unit="monthly")
            session.add(fee_item)
            session.flush()

            # 明細の作成 (田中家: 5,000円 + 繰越1,000円の記述)
            line_a = BillingChargeLine(
                billing_claim_id=claim_a.id,
                fee_item_id=fee_item.id,
                source_type=BillingChargeSourceType.manual,
                description="給食費 (前月繰越分含む)",
                amount=5000,
            )
            session.add(line_a)

            # 当月で満了する減免の登録
            child_a = Child(
                first_name="太郎",
                last_name="田中",
                first_name_kana="タロウ",
                last_name_kana="タナカ",
                birth_date=date(2022, 1, 1),
                enrollment_date=date(2025, 4, 1),
                status=ChildStatus.enrolled,
            )
            session.add(child_a)
            session.flush()

            exemption_expiring = BillingExemption(
                child_id=child_a.id,
                name="一時減額支援",
                exemption_type=ExemptionType.full,
                valid_from=date(2026, 4, 1),
                valid_to=date(2026, 11, 30),  # 当月満了
                is_active=True,
            )
            session.add(exemption_expiring)
            session.commit()
            cycle_id = cycle.id
            family_a_id = family_a.id

        # 直接関数呼び出しの検証
        with Session(self.engine) as session:
            direct_report = audit_billing_cycle(session, cycle_id)
            self.assertTrue(direct_report["is_valid"])
            self.assertEqual(direct_report["claims_count"], 2)

        # 検算 API 呼び出し
        resp = client.get(f"/billing/cycles/{cycle_id}/audit")
        self.assertEqual(resp.status_code, 200)
        report = resp.json()

        self.assertTrue(report["is_valid"])
        self.assertEqual(report["claims_count"], 2)
        self.assertEqual(report["zero_amount_count"], 1)
        self.assertEqual(report["carryover_count"], 1)
        self.assertEqual(report["exemptions_count"], 1)

        warning_types = [w["type"] for w in report["warnings"]]
        self.assertIn("zero_amount", warning_types)
        self.assertIn("carryover_detected", warning_types)
        self.assertIn("exemption_expiring", warning_types)

        # 明細不一致エラーの検出検証
        with Session(self.engine) as session:
            # 田中家の合計を意図的に 6,000 円に不整合化
            claim_a_obj = session.exec(select(BillingClaim).where(BillingClaim.family_id == family_a_id)).first()
            claim_a_obj.total_amount = 6000
            session.add(claim_a_obj)
            session.commit()

        resp_err = client.get(f"/billing/cycles/{cycle_id}/audit")
        self.assertEqual(resp_err.status_code, 200)
        report_err = resp_err.json()
        self.assertFalse(report_err["is_valid"])
        error_warnings = [w for w in report_err["warnings"] if w.get("level") == "error"]
        self.assertEqual(len(error_warnings), 1)
        self.assertIn("明細合計 (¥5,000) と請求合計 (¥6,000) が一致しません", error_warnings[0]["message"])


if __name__ == "__main__":
    unittest.main()
