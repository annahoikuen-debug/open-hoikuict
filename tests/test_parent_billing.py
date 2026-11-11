"""Unit and integration tests for Parent Billing & Extended Care Portal (改善案3)."""
from datetime import date, datetime, timezone
import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from facility_settings_service import get_facility_settings, is_parent_billing_enabled
from models import (
    AttendanceRecord,
    BillingChargeLine,
    BillingChargeSourceType,
    BillingClaim,
    BillingClaimStatus,
    BillingCycle,
    BillingCycleStatus,
    BillingPaymentMethod,
    Child,
    ChildStatus,
    ExtendedCareCharge,
    ExtendedCareChargeStatus,
    ExtendedCareFeeRule,
    Family,
    FamilyBillingProfile,
    FeeItem,
    ParentAccount,
    ParentAccountStatus,
)
from parent_billing_service import (
    get_parent_billing_claims_list,
    get_parent_claim_detail,
    get_parent_realtime_extended_care_summary,
)


@pytest.fixture(name="db_session")
def fixture_db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_facility_settings_parent_billing_toggle(db_session: Session):
    """施設設定の保護者ポータル請求機能トグル (デフォルトOFF/有効化) を検証"""
    # 1. デフォルト状態では無効
    assert is_parent_billing_enabled(db_session) is False

    # 2. 有効化
    settings = get_facility_settings(db_session)
    settings.parent_billing_portal_enabled = True
    db_session.add(settings)
    db_session.commit()

    assert is_parent_billing_enabled(db_session) is True

    # 3. 無効化
    settings.parent_billing_portal_enabled = False
    db_session.add(settings)
    db_session.commit()

    assert is_parent_billing_enabled(db_session) is False


def test_realtime_extended_care_summary(db_session: Session):
    """当月リアルタイム延長保育速報の集計検証（自家庭のみ・他家庭除外）"""
    # 家族1 & 園児2名
    family1 = Family(family_name="山田家")
    db_session.add(family1)
    db_session.commit()
    db_session.refresh(family1)

    child1 = Child(
        last_name="山田",
        first_name="太郎",
        last_name_kana="ヤマダ",
        first_name_kana="タロウ",
        birth_date=date(2021, 5, 1),
        enrollment_date=date(2024, 4, 1),
        status=ChildStatus.enrolled,
        family_id=family1.id,
    )
    child2 = Child(
        last_name="山田",
        first_name="花子",
        last_name_kana="ヤマダ",
        first_name_kana="ハナコ",
        birth_date=date(2023, 7, 10),
        enrollment_date=date(2024, 4, 1),
        status=ChildStatus.enrolled,
        family_id=family1.id,
    )
    db_session.add(child1)
    db_session.add(child2)

    # 別家族2 & 園児1名（集計に混入しないことの確認）
    family2 = Family(family_name="佐藤家")
    db_session.add(family2)
    db_session.commit()
    db_session.refresh(family2)

    child_other = Child(
        last_name="佐藤",
        first_name="次郎",
        last_name_kana="サトウ",
        first_name_kana="ジロウ",
        birth_date=date(2022, 1, 15),
        enrollment_date=date(2024, 4, 1),
        status=ChildStatus.enrolled,
        family_id=family2.id,
    )
    db_session.add(child_other)
    db_session.commit()
    db_session.refresh(child1)
    db_session.refresh(child2)
    db_session.refresh(child_other)

    rule = ExtendedCareFeeRule(
        name="標準延長ルール",
        effective_from=date(2024, 4, 1),
        unit_price=400,
        rounding_minutes=30,
        start_time="18:00",
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    # 家族1・太郎の打刻 & 延長料金 (2026年11月)
    att1 = AttendanceRecord(
        child_id=child1.id,
        attendance_date=date(2026, 11, 4),
        check_out_at=datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc),
        pickup_snack_confirmed=True,
    )
    db_session.add(att1)
    db_session.commit()
    db_session.refresh(att1)

    charge1 = ExtendedCareCharge(
        attendance_record_id=att1.id,
        child_id=child1.id,
        target_date=date(2026, 11, 4),
        rule_id=rule.id,
        charge_start_at=datetime(2026, 11, 4, 18, 0, tzinfo=timezone.utc),
        actual_check_out_at=datetime(2026, 11, 4, 18, 30, tzinfo=timezone.utc),
        extended_minutes=30,
        final_amount=400,
        status=ExtendedCareChargeStatus.confirmed,
    )
    db_session.add(charge1)

    # 家族1・花子の打刻 & 延長料金 (2026年11月)
    att2 = AttendanceRecord(
        child_id=child2.id,
        attendance_date=date(2026, 11, 9),
        check_out_at=datetime(2026, 11, 9, 18, 45, tzinfo=timezone.utc),
    )
    db_session.add(att2)
    db_session.commit()
    db_session.refresh(att2)

    charge2 = ExtendedCareCharge(
        attendance_record_id=att2.id,
        child_id=child2.id,
        target_date=date(2026, 11, 9),
        rule_id=rule.id,
        charge_start_at=datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc),
        actual_check_out_at=datetime(2026, 11, 9, 18, 45, tzinfo=timezone.utc),
        extended_minutes=45,
        final_amount=800,
        status=ExtendedCareChargeStatus.draft,
    )
    db_session.add(charge2)

    # 別家族・佐藤の延長料金 (混入チェック用)
    att_other = AttendanceRecord(
        child_id=child_other.id,
        attendance_date=date(2026, 11, 9),
        check_out_at=datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc),
    )
    db_session.add(att_other)
    db_session.commit()
    db_session.refresh(att_other)

    charge_other = ExtendedCareCharge(
        attendance_record_id=att_other.id,
        child_id=child_other.id,
        target_date=date(2026, 11, 9),
        rule_id=rule.id,
        charge_start_at=datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc),
        actual_check_out_at=datetime(2026, 11, 9, 19, 0, tzinfo=timezone.utc),
        extended_minutes=60,
        final_amount=1200,
        status=ExtendedCareChargeStatus.confirmed,
    )
    db_session.add(charge_other)
    db_session.commit()

    # 集計実行
    summary = get_parent_realtime_extended_care_summary(
        db_session,
        family_id=family1.id,
        year_month="2026-11",
    )

    # 検証: 山田家の2件のみ集計され、佐藤家の1200円は含まれないこと
    assert summary["year_month"] == "2026-11"
    assert summary["total_extended_minutes"] == 75  # 30 + 45
    assert summary["total_estimated_amount"] == 1200  # 400 + 800
    assert len(summary["charges"]) == 2

    # 日付降順 (11/09 -> 11/04)
    item0 = summary["charges"][0]
    assert item0["child_name"] == "山田 花子"
    assert item0["extended_minutes"] == 45
    assert item0["amount"] == 800

    item1 = summary["charges"][1]
    assert item1["child_name"] == "山田 太郎"
    assert item1["extended_minutes"] == 30
    assert item1["amount"] == 400
    assert item1["has_snack"] is True


def test_billing_claims_list_and_detail_security(db_session: Session):
    """月次請求書一覧および明細取得のセキュリティ（下書き非公開・IDOR防御・園児別内訳）"""
    family1 = Family(family_name="山田家")
    family2 = Family(family_name="鈴木家")
    db_session.add(family1)
    db_session.add(family2)
    db_session.commit()
    db_session.refresh(family1)
    db_session.refresh(family2)

    child1 = Child(
        last_name="山田",
        first_name="太郎",
        last_name_kana="ヤマダ",
        first_name_kana="タロウ",
        birth_date=date(2021, 5, 1),
        enrollment_date=date(2024, 4, 1),
        status=ChildStatus.enrolled,
        family_id=family1.id,
    )
    child2 = Child(
        last_name="山田",
        first_name="花子",
        last_name_kana="ヤマダ",
        first_name_kana="ハナコ",
        birth_date=date(2023, 7, 10),
        enrollment_date=date(2024, 4, 1),
        status=ChildStatus.enrolled,
        family_id=family1.id,
    )
    db_session.add(child1)
    db_session.add(child2)
    db_session.commit()
    db_session.refresh(child1)
    db_session.refresh(child2)

    profile = FamilyBillingProfile(
        family_id=family1.id,
        payment_method=BillingPaymentMethod.direct_debit,
        bank_name_kana="ミツイスミトモ",
        branch_name_kana="シブヤ",
        account_type="普通",
        account_number="1234567",
        account_holder_kana="ヤマダ タロウ",
        customer_number="CUST-001",
    )
    db_session.add(profile)

    fee_item_ext = FeeItem(code="EXT", name="延長保育料", category="extension", charge_unit="month")
    fee_item_meal = FeeItem(code="MEAL", name="給食費", category="meal", charge_unit="month")
    db_session.add(fee_item_ext)
    db_session.add(fee_item_meal)
    db_session.commit()
    db_session.refresh(fee_item_ext)
    db_session.refresh(fee_item_meal)

    # 1. 確定済みサイクル (2026年10月度)
    cycle_confirmed = BillingCycle(
        year_month="2026-10",
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        withdrawal_date=date(2026, 11, 26),
        status=BillingCycleStatus.confirmed,
    )
    db_session.add(cycle_confirmed)
    db_session.commit()
    db_session.refresh(cycle_confirmed)

    claim_confirmed = BillingClaim(
        billing_cycle_id=cycle_confirmed.id,
        family_id=family1.id,
        payment_method=BillingPaymentMethod.direct_debit,
        total_amount=5500,
        status=BillingClaimStatus.confirmed,
    )
    db_session.add(claim_confirmed)
    db_session.commit()
    db_session.refresh(claim_confirmed)

    # 明細行: 太郎 (給食費 4,500円), 花子 (延長保育料 1,000円)
    line1 = BillingChargeLine(
        billing_claim_id=claim_confirmed.id,
        fee_item_id=fee_item_meal.id,
        child_id=child1.id,
        source_type=BillingChargeSourceType.meal_auto,
        description="給食・副食費 (10月分)",
        amount=4500,
        unit_price=4500,
        quantity=1,
    )
    line2 = BillingChargeLine(
        billing_claim_id=claim_confirmed.id,
        fee_item_id=fee_item_ext.id,
        child_id=child2.id,
        source_type=BillingChargeSourceType.extension_auto,
        description="延長保育料 (10月実績)",
        amount=1000,
        unit_price=1000,
        quantity=1,
    )
    db_session.add(line1)
    db_session.add(line2)

    # 2. ドラフト中サイクル (2026年11月度) - 下書きなので保護者には見えないはず
    cycle_draft = BillingCycle(
        year_month="2026-11",
        period_start=date(2026, 11, 1),
        period_end=date(2026, 11, 30),
        withdrawal_date=date(2026, 12, 26),
        status=BillingCycleStatus.draft,
    )
    db_session.add(cycle_draft)
    db_session.commit()
    db_session.refresh(cycle_draft)

    claim_draft = BillingClaim(
        billing_cycle_id=cycle_draft.id,
        family_id=family1.id,
        payment_method=BillingPaymentMethod.direct_debit,
        total_amount=6000,
        status=BillingClaimStatus.draft,
    )
    db_session.add(claim_draft)

    # 3. 鈴木家の確定請求 (family2) - 山田家からIDORアクセスされないことの確認用
    claim_suzuki = BillingClaim(
        billing_cycle_id=cycle_confirmed.id,
        family_id=family2.id,
        payment_method=BillingPaymentMethod.direct_debit,
        total_amount=9900,
        status=BillingClaimStatus.confirmed,
    )
    db_session.add(claim_suzuki)
    db_session.commit()
    db_session.refresh(claim_draft)
    db_session.refresh(claim_suzuki)

    # 検証1: 月次請求一覧（確定分のみ取得され、ドラフトの11月分や鈴木家の分は含まれない）
    claims_list = get_parent_billing_claims_list(db_session, family_id=family1.id)
    assert len(claims_list) == 1
    assert claims_list[0]["id"] == claim_confirmed.id
    assert claims_list[0]["year_month"] == "2026-10"
    assert claims_list[0]["total_amount"] == 5500
    assert claims_list[0]["status_label"] == "確定"

    # 検証2: 請求詳細取得（正常系・園児別内訳と口座マスキング）
    detail = get_parent_claim_detail(db_session, family_id=family1.id, claim_id=claim_confirmed.id)
    assert detail is not None
    assert detail["claim_id"] == claim_confirmed.id
    assert detail["total_amount"] == 5500
    assert detail["formatted_total_amount"] == "5,500"
    assert detail["account_info"]["account_number_masked"] == "***4567"
    assert len(detail["child_sections"]) == 2

    # 太郎セクション: 4500円
    taro_section = next(s for s in detail["child_sections"] if s["child_name"] == "山田 太郎")
    assert taro_section["subtotal"] == 4500
    assert len(taro_section["lines"]) == 1
    assert taro_section["lines"][0]["description"] == "給食・副食費 (10月分)"

    # 花子セクション: 1000円
    hanako_section = next(s for s in detail["child_sections"] if s["child_name"] == "山田 花子")
    assert hanako_section["subtotal"] == 1000
    assert len(hanako_section["lines"]) == 1

    # 検証3: IDOR防御 - 山田家(family1)が鈴木家の claim_id を要求しても None
    detail_idor = get_parent_claim_detail(db_session, family_id=family1.id, claim_id=claim_suzuki.id)
    assert detail_idor is None

    # 検証4: ドラフト保護 - 山田家が自分自身のドラフト請求 claim_draft を要求しても None
    detail_draft = get_parent_claim_detail(db_session, family_id=family1.id, claim_id=claim_draft.id)
    assert detail_draft is None


def test_parent_billing_portal_endpoints_integration(db_session: Session):
    """保護者ポータルの請求エンドポイント結合テスト（OFF時404、ON時表示、IDOR防御）"""
    import os
    from fastapi.testclient import TestClient
    from main import app
    from database import get_session
    from auth import MOCK_PARENT_ACCOUNT_COOKIE
    from csrf import generate_csrf_token, CSRF_COOKIE_NAME

    # 1. 家族・保護者・園児のセットアップ
    family = Family(family_name="山田家")
    db_session.add(family)
    db_session.commit()
    db_session.refresh(family)

    parent = ParentAccount(
        family_id=family.id,
        email="yamada_parent@example.com",
        display_name="山田保護者",
        status=ParentAccountStatus.active,
    )
    db_session.add(parent)
    db_session.commit()
    db_session.refresh(parent)

    child = Child(
        last_name="山田",
        first_name="太郎",
        last_name_kana="ヤマダ",
        first_name_kana="タロウ",
        birth_date=date(2021, 5, 1),
        enrollment_date=date(2024, 4, 1),
        status=ChildStatus.enrolled,
        family_id=family.id,
    )
    db_session.add(child)
    db_session.commit()
    db_session.refresh(child)

    # 請求データのセットアップ
    cycle = BillingCycle(
        year_month="2026-10",
        period_start=date(2026, 10, 1),
        period_end=date(2026, 10, 31),
        withdrawal_date=date(2026, 11, 26),
        status=BillingCycleStatus.confirmed,
    )
    db_session.add(cycle)
    db_session.commit()
    db_session.refresh(cycle)

    claim = BillingClaim(
        billing_cycle_id=cycle.id,
        family_id=family.id,
        payment_method=BillingPaymentMethod.direct_debit,
        total_amount=3000,
        status=BillingClaimStatus.confirmed,
    )
    db_session.add(claim)

    fee_item = FeeItem(code="TEST_FEE", name="教材費", category="other", charge_unit="month")
    db_session.add(fee_item)
    db_session.commit()
    db_session.refresh(claim)
    db_session.refresh(fee_item)

    line = BillingChargeLine(
        billing_claim_id=claim.id,
        fee_item_id=fee_item.id,
        child_id=child.id,
        source_type=BillingChargeSourceType.manual,
        description="園外保育・遠足教材代",
        amount=3000,
        unit_price=3000,
        quantity=1,
    )
    db_session.add(line)

    # 別家庭の請求 (IDOR用)
    family_other = Family(family_name="高橋家")
    db_session.add(family_other)
    db_session.commit()
    db_session.refresh(family_other)

    claim_other = BillingClaim(
        billing_cycle_id=cycle.id,
        family_id=family_other.id,
        payment_method=BillingPaymentMethod.direct_debit,
        total_amount=8800,
        status=BillingClaimStatus.confirmed,
    )
    db_session.add(claim_other)
    db_session.commit()
    db_session.refresh(claim_other)

    # 依存性注入オーバーライド
    old_mock_env = os.environ.get("HOIKUICT_ENABLE_MOCK_AUTH")
    os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = "1"

    def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session

    try:
        csrf_token = generate_csrf_token()
        client = TestClient(
            app,
            cookies={
                MOCK_PARENT_ACCOUNT_COOKIE: str(parent.id),
                CSRF_COOKIE_NAME: csrf_token,
            },
        )

        # 【ケース1: 施設設定 OFF (デフォルト)】
        # 1-1. ホーム画面で「ご利用明細」リンクが出現しないこと
        res_home = client.get("/parent-portal/")
        assert res_home.status_code == 200
        assert "ご利用明細" not in res_home.text

        # 1-2. 直接 /parent-portal/billing にアクセスしても 404
        res_billing_off = client.get("/parent-portal/billing")
        assert res_billing_off.status_code == 404

        # 1-3. 直接 /parent-portal/billing/claims/{id} にアクセスしても 404
        res_claim_off = client.get(f"/parent-portal/billing/claims/{claim.id}")
        assert res_claim_off.status_code == 404

        # 【ケース2: 施設設定を ON に変更】
        settings = get_facility_settings(db_session)
        settings.parent_billing_portal_enabled = True
        db_session.add(settings)
        db_session.commit()

        # 2-1. ホーム画面に「💴 ご利用明細」ボタンが出現すること
        res_home_on = client.get("/parent-portal/")
        assert res_home_on.status_code == 200
        assert "ご利用明細" in res_home_on.text
        assert "/parent-portal/billing" in res_home_on.text

        # 2-2. /parent-portal/billing に正常アクセスできること
        res_billing_on = client.get("/parent-portal/billing")
        assert res_billing_on.status_code == 200
        assert "ご利用明細・請求" in res_billing_on.text
        assert "当月 延長保育速報" in res_billing_on.text
        assert "確定請求書・口座振替明細" in res_billing_on.text

        # 2-3. 自家庭の請求詳細 (/parent-portal/billing/claims/{id}) が閲覧できること (印刷対応)
        res_claim_on = client.get(f"/parent-portal/billing/claims/{claim.id}")
        assert res_claim_on.status_code == 200
        assert "ご請求内訳明細" in res_claim_on.text
        assert "山田 太郎" in res_claim_on.text
        assert "園外保育・遠足教材代" in res_claim_on.text
        assert "印刷する (A4)" in res_claim_on.text

        # 2-4. 他家庭の請求詳細にアクセスした場合 (IDOR防御) -> 404
        res_idor = client.get(f"/parent-portal/billing/claims/{claim_other.id}")
        assert res_idor.status_code == 404

    finally:
        app.dependency_overrides.pop(get_session, None)
        if old_mock_env is None:
            os.environ.pop("HOIKUICT_ENABLE_MOCK_AUTH", None)
        else:
            os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = old_mock_env


def test_staff_facility_settings_toggle_update(db_session: Session):
    """職員管理画面から施設設定（請求表示トグル）を更新・履歴保存できることの検証"""
    from uuid import uuid4
    from fastapi.testclient import TestClient
    from main import app
    from database import get_session
    from auth import Role, StaffUser, get_current_staff_user
    from csrf import generate_csrf_token, CSRF_COOKIE_NAME
    from models import FacilitySettingsHistory

    admin_user = StaffUser(role=Role.ADMIN, name="園長テスト", user_id=uuid4())

    def _override_session():
        yield db_session

    def _override_user():
        return admin_user

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_staff_user] = _override_user

    try:
        csrf_token = generate_csrf_token()
        client = TestClient(
            app,
            cookies={CSRF_COOKIE_NAME: csrf_token},
        )

        # 1. 施設設定画面 GET
        res_get = client.get("/settings/facility")
        assert res_get.status_code == 200
        assert "保護者ポータル 請求・延長保育料の表示" in res_get.text

        # 2. POST で 有効化 (parent_billing_portal_enabled="1")
        res_post_on = client.post(
            "/settings/facility",
            data={
                "csrf_token": csrf_token,
                "final_pickup_time": "19:00",
                "supplementary_meal_time": "18:00",
                "supplementary_meal_fee": 100,
                "fever_return_days": 2,
                "fever_caution_c": "37.5",
                "fever_review_c": "38.0",
                "parent_billing_portal_enabled": "1",
            },
            headers={"X-CSRF-Token": csrf_token},
            follow_redirects=False,
        )
        assert res_post_on.status_code == 303
        assert is_parent_billing_enabled(db_session) is True

        # 履歴記録の検証
        history_entry = db_session.exec(
            select(FacilitySettingsHistory).where(FacilitySettingsHistory.field_name == "parent_billing_portal_enabled")
        ).first()
        assert history_entry is not None
        assert history_entry.old_value == "False"
        assert history_entry.new_value == "True"
        assert history_entry.changed_by_name == "園長テスト"

        # 3. POST で 無効化 (parent_billing_portal_enabled を送信しない)
        res_post_off = client.post(
            "/settings/facility",
            data={
                "csrf_token": csrf_token,
                "final_pickup_time": "19:00",
                "supplementary_meal_time": "18:00",
                "supplementary_meal_fee": 100,
                "fever_return_days": 2,
                "fever_caution_c": "37.5",
                "fever_review_c": "38.0",
            },
            headers={"X-CSRF-Token": csrf_token},
            follow_redirects=False,
        )
        assert res_post_off.status_code == 303
        assert is_parent_billing_enabled(db_session) is False

    finally:
        app.dependency_overrides.pop(get_session, None)
        app.dependency_overrides.pop(get_current_staff_user, None)

