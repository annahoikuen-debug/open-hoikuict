import datetime as dt
from sqlmodel import SQLModel, create_engine
import models  # noqa: F401
from shiftai.domain import Contract, EmploymentType, FacilitySettings, Role, StaffMember
from shiftai.shift_patterns import ShiftPattern
from shiftai.standards import build_requirements
from shift_schedule.db_models import StaffContracts
from shift_schedule.services.monthly_engine import MonthlySolveContext, _solve_stage1_daily_patterns


class TestMonthlyHierarchicalEngine:
    def test_stage1_respects_consecutive_days_and_prior_history(self):
        """前月末の連勤履歴が当月の連勤上限に正しく反映されること。"""
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        days = [dt.date(2026, 11, i) for i in range(1, 11)]
        contract_obj = Contract(
            employment_type=EmploymentType.SEI,
            weekly_hours=40.0,
            daily_hours=8.0,
            earliest_start=dt.time(7, 30),
            latest_end=dt.time(19, 30),
        )
        staff = [
            StaffMember(staff_id="S01", name="職員1", roles=[Role.HOIKUSHI], contract=contract_obj),
            StaffMember(staff_id="S02", name="職員2", roles=[Role.HOIKUSHI], contract=contract_obj),
            StaffMember(staff_id="S03", name="職員3", roles=[Role.HOIKUSHI], contract=contract_obj),
        ]
        patterns = [
            ShiftPattern(key="NORMAL", label="日勤", start=dt.time(8, 30), end=dt.time(17, 30), symbol="日"),
        ]
        contracts = {
            "S01": StaffContracts(staff_user_id="S01", max_consecutive_days=5, effective_from=dt.date(2026, 1, 1)),
        }
        # S01 は前月末にすでに 4連勤 している状態（連勤上限5日なら、月初11/1に勤務した場合11/2は必ずOFFになる）
        prior_streaks = {"S01": 4, "S02": 0, "S03": 0}

        facility_settings = FacilitySettings(
            day_open=dt.time(7, 30),
            day_close=dt.time(19, 30),
            granularity_min=30,
            capacity=30,
        )
        requirements = build_requirements(
            [],
            days,
            standard=None,
            day_open=dt.time(7, 30),
            day_close=dt.time(19, 30),
            granularity_min=30,
        )

        ctx = MonthlySolveContext(
            target_month="2026-11",
            all_days=days,
            staff=staff,
            contracts=contracts,
            preferences={},
            patterns=patterns,
            requirements=requirements,
            facility_settings=facility_settings,
            fixed_assignments={},
            prior_duty_history=prior_streaks,
            monthly_holiday_target=2,
        )

        stage1_res = _solve_stage1_daily_patterns(ctx, time_limit_sec=10)
        s01_nov1 = stage1_res.get(("S01", dt.date(2026, 11, 1)))
        s01_nov2 = stage1_res.get(("S01", dt.date(2026, 11, 2)))
        if s01_nov1 != "OFF":
            assert s01_nov2 == "OFF", "前月末4連勤のため、月初1日出勤後は必ず休日が入る必要があります"
