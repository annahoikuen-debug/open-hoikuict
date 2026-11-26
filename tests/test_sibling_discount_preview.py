"""B2（軽量版）検算レポートでの兄弟割引不一致チェック・B5（軽量版）権限リンクテスト."""

from __future__ import annotations

from datetime import date

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from billing_sibling_service import evaluate_family_sibling_ranks
from models import (
    BillingChargeLine,
    BillingChargeSourceType,
    BillingClaim,
    BillingCycle,
    BillingCycleStatus,
    BillingExemption,
    BillingPaymentMethod,
    Child,
    ChildStatus,
    ExemptionType,
    Family,
    FeeItem,
)
from routers.billing import audit_billing_cycle
from staff_permissions import PERMISSION_GUIDANCE, get_permission_guidance


def _make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def _make_child(
    family_id: int,
    last_name: str,
    first_name: str,
    birth_date: date,
) -> Child:
    return Child(
        family_id=family_id,
        last_name=last_name,
        first_name=first_name,
        last_name_kana=last_name,
        first_name_kana=first_name,
        birth_date=birth_date,
        enrollment_date=date(2025, 4, 1),
        status=ChildStatus.enrolled,
    )


def test_evaluate_family_sibling_ranks_birth_order() -> None:
    """1. 生年月日順（年長者順）に第1子・第2子・第3子が正しく判定される."""
    with _make_session() as session:
        fam = Family(family_name="山田")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        c1 = _make_child(fam.id, "山田", "太郎", date(2021, 5, 1))
        c2 = _make_child(fam.id, "山田", "次郎", date(2023, 4, 1))
        session.add(c1)
        session.add(c2)
        session.commit()

        ranks = evaluate_family_sibling_ranks(session, fam.id, "2026-11")
        assert len(ranks) == 2
        assert ranks[0]["child_name"] == "山田 太郎"
        assert ranks[0]["discount_percentage"] == 0
        assert ranks[1]["child_name"] == "山田 次郎"
        assert ranks[1]["discount_percentage"] == 50


def test_audit_detects_sibling_discount_mismatch_and_passes_when_matched() -> None:
    """2 & 3. 自動判定と明細の不一致が検算レポートで警告され、一致時は警告が出ない."""
    with _make_session() as session:
        fam = Family(family_name="佐藤")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        c1 = _make_child(fam.id, "佐藤", "一郎", date(2021, 6, 1))
        c2 = _make_child(fam.id, "佐藤", "二郎", date(2023, 7, 1))
        session.add(c1)
        session.add(c2)
        session.commit()
        session.refresh(c1)
        session.refresh(c2)

        cycle = BillingCycle(
            year_month="2026-11",
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 30),
            withdrawal_date=date(2026, 12, 10),
            due_date=date(2026, 12, 10),
            status=BillingCycleStatus.draft,
        )
        session.add(cycle)
        session.commit()
        session.refresh(cycle)

        claim = BillingClaim(
            billing_cycle_id=cycle.id,
            family_id=fam.id,
            payment_method=BillingPaymentMethod.direct_debit,
            total_amount=8000,
        )
        session.add(claim)
        session.commit()
        session.refresh(claim)

        fee = FeeItem(code="MEAL", name="給食費", category="other", charge_unit="monthly", default_amount=5000)
        session.add(fee)
        session.commit()
        session.refresh(fee)

        # 第2子なのに「多子」適用メモがなく満額請求されている不一致状態
        line_c1 = BillingChargeLine(
            billing_claim_id=claim.id,
            fee_item_id=fee.id,
            child_id=c1.id,
            source_type=BillingChargeSourceType.manual,
            description="給食費",
            amount=5000,
        )
        line_c2 = BillingChargeLine(
            billing_claim_id=claim.id,
            fee_item_id=fee.id,
            child_id=c2.id,
            source_type=BillingChargeSourceType.manual,
            description="給食費",
            amount=3000,
        )
        session.add(line_c1)
        session.add(line_c2)
        session.commit()
        session.refresh(line_c2)

        audit1 = audit_billing_cycle(session, cycle.id)
        assert audit1["sibling_mismatch_count"] == 1
        assert any(w["type"] == "sibling_discount_mismatch" for w in audit1["warnings"])

        # 明細に多子軽減が反映されていれば不一致警告は出ない
        line_c2.description = "給食費 (第2子(多子50%軽減))"
        line_c2.amount = 1500
        claim.total_amount = 6500
        session.add(line_c2)
        session.add(claim)
        session.commit()

        audit2 = audit_billing_cycle(session, cycle.id)
        assert audit2["sibling_mismatch_count"] == 0
        assert not any(w["type"] == "sibling_discount_mismatch" for w in audit2["warnings"])


def test_audit_allows_manual_exemption_override_without_mismatch() -> None:
    """4. BillingExemption による個別減免上書き時は不一致警告を出さない."""
    with _make_session() as session:
        fam = Family(family_name="鈴木")
        session.add(fam)
        session.commit()
        session.refresh(fam)

        c1 = _make_child(fam.id, "鈴木", "姉", date(2021, 4, 1))
        c2 = _make_child(fam.id, "鈴木", "妹", date(2023, 5, 1))
        session.add(c1)
        session.add(c2)
        session.commit()
        session.refresh(c2)

        ex = BillingExemption(
            child_id=c2.id,
            name="自治体特例免除",
            exemption_type=ExemptionType.full,
            valid_from=date(2026, 4, 1),
            is_active=True,
        )
        cycle = BillingCycle(
            year_month="2026-11",
            period_start=date(2026, 11, 1),
            period_end=date(2026, 11, 30),
            withdrawal_date=date(2026, 12, 10),
            due_date=date(2026, 12, 10),
            status=BillingCycleStatus.draft,
        )
        session.add(ex)
        session.add(cycle)
        session.commit()
        session.refresh(cycle)

        claim = BillingClaim(
            billing_cycle_id=cycle.id,
            family_id=fam.id,
            payment_method=BillingPaymentMethod.direct_debit,
            total_amount=0,
        )
        session.add(claim)
        session.commit()
        session.refresh(claim)

        fee = FeeItem(code="MEAL2", name="給食費", category="other", charge_unit="monthly", default_amount=5000)
        session.add(fee)
        session.commit()
        session.refresh(fee)

        line = BillingChargeLine(
            billing_claim_id=claim.id,
            fee_item_id=fee.id,
            child_id=c2.id,
            source_type=BillingChargeSourceType.manual,
            description="給食費 (自治体特例免除)",
            amount=0,
        )
        session.add(line)
        session.commit()

        audit = audit_billing_cycle(session, cycle.id)
        assert audit["sibling_mismatch_count"] == 0


def test_permission_guidance_contains_settings_url() -> None:
    """B5軽量版: PERMISSION_GUIDANCE に権限設定画面リンクが含まれる."""
    for key in PERMISSION_GUIDANCE:
        guidance = get_permission_guidance(key)
        assert guidance["settings_url"] == "/staff/permissions"
    assert get_permission_guidance("unknown_key")["settings_url"] == "/staff/permissions"
