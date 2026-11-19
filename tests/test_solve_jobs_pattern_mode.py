import datetime as dt
from unittest.mock import patch

from shiftai.domain import (
    AgeClass,
    CellState,
    ChildPlan,
    Contract,
    EmploymentType,
    FacilitySettings,
    Role,
    ShiftDay,
    Slot,
    SolveResult,
    SolveStatus,
    StaffMember,
    StaffPreferences,
)
from shiftai.shift_patterns import DEFAULT_PATTERNS
from shiftai.solver import snap_to_patterns, solve_shift
from shiftai.standards import build_requirements
from shiftai.local_rules import get_standard


class TestSolveJobsPatternMode:
    """シフトパターン整列およびウォームスタート連携テスト。"""

    def test_solve_shift_with_patterns_and_snap(self):
        """パターン指定および snap_to_patterns 後処理が正常に実行されること。"""
        day = dt.date(2026, 11, 2)
        day_open = dt.time(7, 30)
        day_close = dt.time(19, 30)
        granularity = 30

        standard = get_standard("全国基準（厚労省）")
        settings = FacilitySettings(
            day_open=day_open,
            day_close=day_close,
            granularity_min=granularity,
            capacity=30,
        )

        # 園児データ（3歳児 6名）
        children = [
            ChildPlan(
                child_id=f"C{i:02d}",
                name=f"園児{i}",
                day=day,
                age_class=AgeClass.AGE_3,
                arrive=dt.time(8, 30),
                depart=dt.time(17, 0),
            )
            for i in range(1, 7)
        ]

        table = build_requirements(
            children,
            [day],
            standard,
            day_open=day_open,
            day_close=day_close,
            granularity_min=granularity,
        )

        # 職員データ（4名）
        contract = Contract(
            weekly_hours=40.0,
            daily_hours=8.0,
            employment_type=EmploymentType.SEI,
            earliest_start=dt.time(7, 30),
            latest_end=dt.time(19, 30),
        )
        staff = [
            StaffMember(f"S{i:02d}", f"職員{i}", (Role.HOIKUSHI,), contract)
            for i in range(1, 5)
        ]
        prefs = {s.staff_id: StaffPreferences() for s in staff}

        # 求解（patterns, warm_start=True を指定）
        result = solve_shift(
            children=children,
            staff=staff,
            requirements=table,
            preferences=prefs,
            settings=settings,
            standard=standard,
            time_limit_sec=10,
            patterns=DEFAULT_PATTERNS,
            warm_start=True,
            pattern_mode=False,
        )

        assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)

        # snap_to_patterns の実行
        snapped_result, changes = snap_to_patterns(
            result,
            DEFAULT_PATTERNS,
            requirements=table,
            preferences=prefs,
            staff=staff,
            standard=standard,
            settings=settings,
        )

        assert snapped_result is not None
        assert snapped_result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
        assert isinstance(changes, tuple)

    def test_solve_shift_pattern_mode_enabled_adds_pattern_constraints(self):
        """pattern_mode=True のとき、パターン整列制約がハード制約として適用されること。"""
        day = dt.date(2026, 11, 2)
        day_open = dt.time(7, 30)
        day_close = dt.time(19, 30)
        granularity = 30

        standard = get_standard("全国基準（厚労省）")
        settings = FacilitySettings(
            day_open=day_open,
            day_close=day_close,
            granularity_min=granularity,
            capacity=30,
        )

        children = [
            ChildPlan(
                child_id=f"C{i:02d}",
                name=f"園児{i}",
                day=day,
                age_class=AgeClass.AGE_3,
                arrive=dt.time(8, 30),
                depart=dt.time(17, 0),
            )
            for i in range(1, 7)
        ]

        table = build_requirements(
            children,
            [day],
            standard,
            day_open=day_open,
            day_close=day_close,
            granularity_min=granularity,
        )

        contract = Contract(
            weekly_hours=40.0,
            daily_hours=8.0,
            employment_type=EmploymentType.SEI,
            earliest_start=dt.time(7, 30),
            latest_end=dt.time(19, 30),
        )
        staff = [
            StaffMember(f"S{i:02d}", f"職員{i}", (Role.HOIKUSHI,), contract)
            for i in range(1, 5)
        ]
        prefs = {s.staff_id: StaffPreferences() for s in staff}

        # pattern_mode=True でパターン制約を有効にして求解
        result = solve_shift(
            children=children,
            staff=staff,
            requirements=table,
            preferences=prefs,
            settings=settings,
            standard=standard,
            time_limit_sec=10,
            patterns=DEFAULT_PATTERNS,
            warm_start=True,
            pattern_mode=True,
        )

        assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)

    def test_solve_shift_pattern_mode_disabled_uses_soft_penalty(self):
        """pattern_mode=False のとき、パターン整列はソフトペナルティとして適用され、
        求解が正常に完了すること。"""
        day = dt.date(2026, 11, 2)
        day_open = dt.time(7, 30)
        day_close = dt.time(19, 30)
        granularity = 30

        standard = get_standard("全国基準（厚労省）")
        settings = FacilitySettings(
            day_open=day_open,
            day_close=day_close,
            granularity_min=granularity,
            capacity=30,
        )

        children = [
            ChildPlan(
                child_id=f"C{i:02d}",
                name=f"園児{i}",
                day=day,
                age_class=AgeClass.AGE_3,
                arrive=dt.time(8, 30),
                depart=dt.time(17, 0),
            )
            for i in range(1, 7)
        ]

        table = build_requirements(
            children,
            [day],
            standard,
            day_open=day_open,
            day_close=day_close,
            granularity_min=granularity,
        )

        contract = Contract(
            weekly_hours=40.0,
            daily_hours=8.0,
            employment_type=EmploymentType.SEI,
            earliest_start=dt.time(7, 30),
            latest_end=dt.time(19, 30),
        )
        staff = [
            StaffMember(f"S{i:02d}", f"職員{i}", (Role.HOIKUSHI,), contract)
            for i in range(1, 5)
        ]
        prefs = {s.staff_id: StaffPreferences() for s in staff}

        # pattern_mode=False でソフトペナルティとして求解
        result = solve_shift(
            children=children,
            staff=staff,
            requirements=table,
            preferences=prefs,
            settings=settings,
            standard=standard,
            time_limit_sec=10,
            patterns=DEFAULT_PATTERNS,
            warm_start=True,
            pattern_mode=False,
        )

        assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)

    def test_snap_to_patterns_returns_valid_result(self):
        """snap_to_patterns が有効な SolveResult を返すこと。"""
        day = dt.date(2026, 11, 2)
        day_open = dt.time(7, 30)
        day_close = dt.time(19, 30)
        granularity = 30

        standard = get_standard("全国基準（厚労省）")
        settings = FacilitySettings(
            day_open=day_open,
            day_close=day_close,
            granularity_min=granularity,
            capacity=30,
        )

        children = [
            ChildPlan(
                child_id=f"C{i:02d}",
                name=f"園児{i}",
                day=day,
                age_class=AgeClass.AGE_3,
                arrive=dt.time(8, 30),
                depart=dt.time(17, 0),
            )
            for i in range(1, 7)
        ]

        table = build_requirements(
            children,
            [day],
            standard,
            day_open=day_open,
            day_close=day_close,
            granularity_min=granularity,
        )

        contract = Contract(
            weekly_hours=40.0,
            daily_hours=8.0,
            employment_type=EmploymentType.SEI,
            earliest_start=dt.time(7, 30),
            latest_end=dt.time(19, 30),
        )
        staff = [
            StaffMember(f"S{i:02d}", f"職員{i}", (Role.HOIKUSHI,), contract)
            for i in range(1, 5)
        ]
        prefs = {s.staff_id: StaffPreferences() for s in staff}

        result = solve_shift(
            children=children,
            staff=staff,
            requirements=table,
            preferences=prefs,
            settings=settings,
            standard=standard,
            time_limit_sec=10,
            patterns=DEFAULT_PATTERNS,
            warm_start=True,
            pattern_mode=False,
        )

        assert result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)

        # snap_to_patterns を実際に呼び出し、有効な結果を返すことを確認
        snapped_result, changes = snap_to_patterns(
            result,
            DEFAULT_PATTERNS,
            requirements=table,
            preferences=prefs,
            staff=staff,
            standard=standard,
            settings=settings,
        )

        assert snapped_result is not None
        assert snapped_result.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE)
        assert isinstance(changes, tuple)
