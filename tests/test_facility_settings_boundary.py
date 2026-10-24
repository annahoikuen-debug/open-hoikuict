"""Boundary and segregation-of-duties tests for FacilitySettings vs ShiftFacilitySettings (Step 18)."""

import unittest
from datetime import datetime

from sqlmodel import SQLModel, Session, create_engine, select
from sqlalchemy.pool import StaticPool

from models import FacilitySettings
from shift_schedule.db_models import ShiftFacilitySettings


class FacilitySettingsBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def test_settings_tables_segregation_and_defaults(self):
        with Session(self.engine) as session:
            # 1. 本体 FacilitySettings (Phase 3.2: 延長保育・補食・キオスク運用)
            fac = FacilitySettings(
                id=1,
                final_pickup_time="19:00",
                supplementary_meal_time="18:00",
                supplementary_meal_fee=100,
            )
            session.add(fac)

            # 2. シフト用 ShiftFacilitySettings (Phase 3.1: 開園・閉園・定員・配置基準)
            shift_fac = ShiftFacilitySettings(
                id=1,
                day_open="07:30",
                day_close="19:30",
                capacity=60,
                staffing_standard_key="fukuoka_city",
            )
            session.add(shift_fac)
            session.commit()

            loaded_fac = session.exec(select(FacilitySettings).where(FacilitySettings.id == 1)).one()
            loaded_shift = session.exec(select(ShiftFacilitySettings).where(ShiftFacilitySettings.id == 1)).one()

            # 責務分離の検証:
            # 開園・閉園の正本は ShiftFacilitySettings
            self.assertEqual(loaded_shift.day_open, "07:30")
            self.assertEqual(loaded_shift.day_close, "19:30")

            # 補食・最終ピックアップ時刻の正本は FacilitySettings
            self.assertEqual(loaded_fac.final_pickup_time, "19:00")
            self.assertEqual(loaded_fac.supplementary_meal_time, "18:00")
            self.assertEqual(loaded_fac.supplementary_meal_fee, 100)

            # テーブル名と責務が完全に独立していること
            self.assertNotEqual(FacilitySettings.__tablename__, ShiftFacilitySettings.__tablename__)
