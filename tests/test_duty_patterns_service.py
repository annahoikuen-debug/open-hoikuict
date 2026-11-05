import datetime as dt
from sqlmodel import Session, SQLModel, create_engine
import models  # noqa: F401 - registers core tables including children and users
from shift_schedule.db_models import ShiftDutyPatterns, ShiftFacilitySettings, StaffContracts
from shift_schedule.services.duty_patterns import (
    get_active_duty_patterns,
    match_staff_patterns,
)
from shift_schedule.services.solve_inputs import resolve_slot_to_time_window


class TestDutyPatternsService:
    def test_get_active_duty_patterns_default_initialization(self):
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)
        with Session(engine) as session:
            facility = ShiftFacilitySettings(id=1, day_open="07:00", day_close="20:00")
            session.add(facility)
            session.commit()

            patterns = get_active_duty_patterns(session, setting_id=1)
            assert len(patterns) == 3
            assert patterns[0].name == "早番"
            assert patterns[0].start_time == "07:00"
            assert patterns[2].name == "遅番"
            assert patterns[2].end_time == "20:00"

    def test_resolve_slot_to_time_window_custom_patterns(self):
        patterns = [
            ShiftDutyPatterns(name="延長パート", symbol="延", start_time="15:00", end_time="19:30"),
            ShiftDutyPatterns(name="短時間", symbol="短", start_time="09:00", end_time="14:00"),
        ]
        assert resolve_slot_to_time_window("延", duty_patterns=patterns) == ["15:00-19:30"]
        assert resolve_slot_to_time_window("短時間", duty_patterns=patterns) == ["09:00-14:00"]
        assert resolve_slot_to_time_window("08:30-17:30", duty_patterns=patterns) == ["08:30-17:30"]

    def test_match_staff_patterns(self):
        contract = StaffContracts(
            staff_user_id="U01",
            employment_type="part_time",
            earliest_start="08:30",
            latest_end="17:00",
            effective_from=dt.date(2026, 1, 1),
        )
        patterns = [
            ShiftDutyPatterns(name="早番", symbol="早", start_time="07:30", end_time="16:30"),
            ShiftDutyPatterns(name="中番", symbol="中", start_time="09:00", end_time="16:00"),
            ShiftDutyPatterns(name="遅番", symbol="遅", start_time="10:30", end_time="19:30"),
        ]
        matched = match_staff_patterns(contract, patterns)
        assert len(matched) == 1
        assert matched[0].name == "中番"
