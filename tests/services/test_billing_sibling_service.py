from __future__ import annotations

from datetime import date
from sqlmodel import Session, SQLModel, create_engine

import child_records.models  # noqa: F401
from billing_sibling_service import (
    calculate_sibling_discount_for_child,
    evaluate_family_sibling_ranks,
)
from models import Child, ChildStatus, Classroom, Family
from routers.billing import apply_child_exemptions


def test_billing_sibling_service_and_exemption_integration():
    engine = create_engine("sqlite:///:memory:", echo=False)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        # クラス・家族の作成
        classroom = Classroom(name="つき組", capacity=25)
        session.add(classroom)
        family = Family(family_name="佐藤家")
        session.add(family)
        session.commit()
        session.refresh(classroom)
        session.refresh(family)

        # 3人兄弟の登録
        # 長男（2020年4月生、2026年3月31日卒園）
        child1 = Child(
            first_name="一郎",
            last_name="佐藤",
            first_name_kana="イチロウ",
            last_name_kana="サトウ",
            status=ChildStatus.enrolled,
            birth_date=date(2020, 4, 1),
            enrollment_date=date(2021, 4, 1),
            withdrawal_date=date(2026, 3, 31),
            classroom_id=classroom.id,
            family_id=family.id,
        )
        # 次男（2022年8月生）
        child2 = Child(
            first_name="二郎",
            last_name="佐藤",
            first_name_kana="ジロウ",
            last_name_kana="サトウ",
            status=ChildStatus.enrolled,
            birth_date=date(2022, 8, 15),
            enrollment_date=date(2023, 4, 1),
            classroom_id=classroom.id,
            family_id=family.id,
        )
        # 三男（2024年2月生）
        child3 = Child(
            first_name="三郎",
            last_name="佐藤",
            first_name_kana="サブロウ",
            last_name_kana="サトウ",
            status=ChildStatus.enrolled,
            birth_date=date(2024, 2, 1),
            enrollment_date=date(2024, 4, 1),
            classroom_id=classroom.id,
            family_id=family.id,
        )
        # 別世帯の単身園児
        solo_child = Child(
            first_name="花子",
            last_name="田中",
            first_name_kana="ハナコ",
            last_name_kana="タナカ",
            status=ChildStatus.enrolled,
            birth_date=date(2023, 1, 10),
            enrollment_date=date(2023, 4, 1),
            classroom_id=classroom.id,
        )
        session.add_all([child1, child2, child3, solo_child])
        session.commit()
        session.refresh(child1)
        session.refresh(child2)
        session.refresh(child3)
        session.refresh(solo_child)

        # 1. 2026年3月（長男在園中: 3人同時在園）
        ranks_mar = evaluate_family_sibling_ranks(session, family.id, "2026-03")
        assert len(ranks_mar) == 3
        # 長男: 第1子
        assert ranks_mar[0]["child_id"] == child1.id
        assert ranks_mar[0]["rank"] == 1
        assert ranks_mar[0]["discount_percentage"] == 0
        # 次男: 第2子 (50%軽減)
        assert ranks_mar[1]["child_id"] == child2.id
        assert ranks_mar[1]["rank"] == 2
        assert ranks_mar[1]["discount_percentage"] == 50
        # 三男: 第3子 (100%全額免除)
        assert ranks_mar[2]["child_id"] == child3.id
        assert ranks_mar[2]["rank"] == 3
        assert ranks_mar[2]["discount_percentage"] == 100

        # calculate_sibling_discount_for_child の検証 (2026-03)
        s_eval2 = calculate_sibling_discount_for_child(session, child2.id, "2026-03")
        assert s_eval2["rank"] == 2
        assert s_eval2["discount_percentage"] == 50

        s_eval3 = calculate_sibling_discount_for_child(session, child3.id, "2026-03")
        assert s_eval3["rank"] == 3
        assert s_eval3["discount_percentage"] == 100

        # 2. 2026年4月（長男退園後: 2人在園）-> 繰り上がり検証
        ranks_apr = evaluate_family_sibling_ranks(session, family.id, "2026-04")
        assert len(ranks_apr) == 2
        # 次男が第1子に繰り上がり (0%)
        assert ranks_apr[0]["child_id"] == child2.id
        assert ranks_apr[0]["rank"] == 1
        assert ranks_apr[0]["discount_percentage"] == 0
        # 三男が第2子に繰り上がり (50%)
        assert ranks_apr[1]["child_id"] == child3.id
        assert ranks_apr[1]["rank"] == 2
        assert ranks_apr[1]["discount_percentage"] == 50

        # 3. 単身在園児の検証
        solo_eval = calculate_sibling_discount_for_child(session, solo_child.id, "2026-03")
        assert solo_eval["discount_percentage"] == 0

        # 4. apply_child_exemptions との結合動作検証
        # 2026年3月: 次男（第2子）の保育料 30,000円 -> 50%軽減で 15,000円
        amount2, note2 = apply_child_exemptions(
            session=session,
            child_id=child2.id,
            fee_item_id=None,
            original_amount=30000,
            target_date=date(2026, 3, 1),
        )
        assert amount2 == 15000
        assert "第2子(多子50%軽減)" in note2

        # 2026年3月: 三男（第3子）の保育料 30,000円 -> 100%免除で 0円
        amount3, note3 = apply_child_exemptions(
            session=session,
            child_id=child3.id,
            fee_item_id=None,
            original_amount=30000,
            target_date=date(2026, 3, 1),
        )
        assert amount3 == 0
        assert "第3子(多子無償化)" in note3
