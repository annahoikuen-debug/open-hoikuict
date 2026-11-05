"""Tests for facility_settings_service helpers and change history."""
import unittest

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models import FacilitySettings, FacilitySettingsHistory


class FacilitySettingsServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine, tables=[
            FacilitySettings.__table__, FacilitySettingsHistory.__table__,
        ])

    def test_get_facility_settings_returns_defaults_without_commit(self):
        from facility_settings_service import get_facility_settings

        with Session(self.engine) as session:
            settings = get_facility_settings(session)
            self.assertEqual(settings.final_pickup_time, "19:00")
            self.assertEqual(settings.supplementary_meal_time, "18:00")
            self.assertEqual(settings.supplementary_meal_fee, 100)
            # 参照ヘルパは commit しない
            self.assertEqual(
                session.exec(select(FacilitySettings)).all(), [],
            )

    def test_latest_pickup_time_and_snack_helpers(self):
        from facility_settings_service import (
            latest_pickup_time, snack_fee, snack_threshold_time,
        )

        with Session(self.engine) as session:
            self.assertEqual(latest_pickup_time(session), "19:00")
            self.assertEqual(snack_threshold_time(session), "18:00")
            self.assertEqual(snack_fee(session), 100)

            session.add(FacilitySettings(
                id=1, final_pickup_time="18:30",
                supplementary_meal_time="17:45", supplementary_meal_fee=200,
            ))
            session.commit()

        with Session(self.engine) as session:
            self.assertEqual(latest_pickup_time(session), "18:30")
            self.assertEqual(snack_threshold_time(session), "17:45")
            self.assertEqual(snack_fee(session), 200)

    def test_auto_snack_required_boundary_and_invalid(self):
        from facility_settings_service import auto_snack_required

        with Session(self.engine) as session:
            session.add(FacilitySettings(id=1, supplementary_meal_time="18:00"))
            session.commit()

        with Session(self.engine) as session:
            self.assertFalse(auto_snack_required(session, "17:59"))
            self.assertTrue(auto_snack_required(session, "18:00"))
            self.assertTrue(auto_snack_required(session, "18:30"))
            self.assertFalse(auto_snack_required(session, ""))
            self.assertFalse(auto_snack_required(session, "invalid"))

    def test_record_change_history_only_changed_fields(self):
        from facility_settings_service import record_change_history

        settings = FacilitySettings(
            id=1, final_pickup_time="19:30",
            supplementary_meal_time="18:00", supplementary_meal_fee=100,
        )
        previous = dict(
            final_pickup_time="19:00",
            supplementary_meal_time="18:00",
            supplementary_meal_fee="100",
        )
        with Session(self.engine) as session:
            record_change_history(session, settings, previous, actor_name="園長")
            session.commit()

        with Session(self.engine) as session:
            rows = session.exec(select(FacilitySettingsHistory)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].field_name, "final_pickup_time")
            self.assertEqual(rows[0].old_value, "19:00")
            self.assertEqual(rows[0].new_value, "19:30")
            self.assertEqual(rows[0].changed_by_name, "園長")

    def test_record_change_history_fee_is_recorded_as_string(self):
        from facility_settings_service import record_change_history

        settings = FacilitySettings(
            id=1, final_pickup_time="19:00",
            supplementary_meal_time="18:00", supplementary_meal_fee=150,
        )
        previous = dict(
            final_pickup_time="19:00",
            supplementary_meal_time="18:00",
            supplementary_meal_fee="100",
        )
        with Session(self.engine) as session:
            record_change_history(session, settings, previous, actor_name="主任")
            session.commit()

        with Session(self.engine) as session:
            rows = session.exec(select(FacilitySettingsHistory)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].field_name, "supplementary_meal_fee")
            self.assertEqual(rows[0].new_value, "150")


if __name__ == "__main__":
    unittest.main()
