from datetime import date
from shiftai.domain import AgeClass
from shift_schedule.bridge import age_class_on


class TestAgeClassFiscal:
    """保育年度（4月1日基準）に基づく年齢区分判定テスト。"""

    def test_birthday_during_fiscal_year_does_not_change_age_class(self):
        """年度途中で誕生日を迎えても、年度内のAgeClassは変化しない。"""
        # 2022年5月15日生まれの子（2026年度は4歳になるが、4月1日時点では3歳なので3歳児クラス）
        birth = date(2022, 5, 15)

        # 2026年4月（誕生日以前）
        assert age_class_on(date(2026, 4, 1), birth) == AgeClass.AGE_3
        assert age_class_on(date(2026, 5, 14), birth) == AgeClass.AGE_3

        # 2026年5月15日（誕生日当日）
        assert age_class_on(date(2026, 5, 15), birth) == AgeClass.AGE_3

        # 2026年12月（誕生日以降）
        assert age_class_on(date(2026, 12, 25), birth) == AgeClass.AGE_3

        # 2027年3月31日（年度末）
        assert age_class_on(date(2027, 3, 31), birth) == AgeClass.AGE_3

        # 2027年4月1日（新年度開始時）に4歳児クラスへ進級
        assert age_class_on(date(2027, 4, 1), birth) == AgeClass.AGE_4

    def test_april_first_and_second_boundary(self):
        """4月1日生まれ（早生まれ扱い・前学年）と4月2日生まれ（新学年）の境界値。"""
        # 2026年度（2026/4/1〜2027/3/31）における判定
        target = date(2026, 6, 1)

        # 2023年4月1日生まれ: 2026年4月1日時点で3歳（3歳児クラス）
        child_apr1 = date(2023, 4, 1)
        assert age_class_on(target, child_apr1) == AgeClass.AGE_3

        # 2023年4月2日生まれ: 2026年4月1日時点では2歳（2歳児クラス）
        child_apr2 = date(2023, 4, 2)
        assert age_class_on(target, child_apr2) == AgeClass.AGE_2

        # 2022年4月1日生まれ: 2026年4月1日時点で4歳（4歳児クラス）
        assert age_class_on(target, date(2022, 4, 1)) == AgeClass.AGE_4
        # 2022年4月2日生まれ: 2026年4月1日時点で3歳（3歳児クラス）
        assert age_class_on(target, date(2022, 4, 2)) == AgeClass.AGE_3

    def test_early_born_january_to_march(self):
        """早生まれ（1月〜3月生まれ）の児童の学年判定。"""
        target = date(2026, 10, 1)
        # 2023年3月31日生まれ: 2026年4月1日時点で3歳（3歳児クラス）
        assert age_class_on(target, date(2023, 3, 31)) == AgeClass.AGE_3

        # 2024年2月20日生まれ: 2026年4月1日時点で2歳（2歳児クラス）
        assert age_class_on(target, date(2024, 2, 20)) == AgeClass.AGE_2

    def test_infant_under_one_year(self):
        """0歳児の判定。"""
        # 2025年8月生まれ: 2026年度は0歳児クラス（4/1時点で0歳）
        assert age_class_on(date(2026, 4, 1), date(2025, 8, 1)) == AgeClass.INFANT
        assert age_class_on(date(2027, 3, 31), date(2025, 8, 1)) == AgeClass.INFANT

        # 2026年5月生まれ（今年度途中生まれ）: 0歳児クラス
        assert age_class_on(date(2026, 10, 1), date(2026, 5, 1)) == AgeClass.INFANT

    def test_fallback_for_none_birth_date(self):
        """生年月日不明の場合はフォールバックする。"""
        assert age_class_on(date(2026, 10, 1), None) == AgeClass.INFANT
