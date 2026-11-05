"""与薬記録・登園可能判定サービス（改善案8）のテスト。"""
from __future__ import annotations

import unittest
from datetime import date
from uuid import uuid4

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models import Child, Family, MedicationAdministration


def _build_engine():
    import models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _create_child(session: Session) -> Child:
    family = Family(family_name="てすと")
    session.add(family)
    session.flush()
    child = Child(
        family_id=family.id, last_name="てすと", first_name="ゆうと",
        last_name_kana="テスト", first_name_kana="ユウト",
        birth_date=date(2022, 4, 1), enrollment_date=date(2024, 4, 1),
    )
    session.add(child)
    session.flush()
    return child


class MedicationServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = _build_engine()
        with Session(self.engine) as session:
            self.child = _create_child(session)
            session.commit()
            self.child_id = self.child.id

    def _request(self, session, **kwargs):
        from medication_service import request_medication

        return request_medication(
            session, child_id=self.child_id, target_date=date(2026, 11, 5),
            medication_name=kwargs.pop("medication_name", "解熱剤"),
            administration_time=kwargs.pop("administration_time", "15:00"),
            **kwargs,
        )

    def test_request_and_administer_and_confirm(self):
        from medication_service import administer_medication, confirm_medication

        staff_a, staff_b = uuid4(), uuid4()
        with Session(self.engine) as session:
            record = self._request(session)
            session.commit()
            record_id = record.id

        with Session(self.engine) as session:
            administer_medication(session, medication_id=record_id,
                                  staff_name="田中", staff_user_id=staff_a)
            session.commit()

        with Session(self.engine) as session:
            confirm_medication(session, medication_id=record_id,
                               staff_name="佐藤", staff_user_id=staff_b)
            session.commit()

        with Session(self.engine) as session:
            record = session.get(MedicationAdministration, record_id)
            self.assertEqual(record.status, "administered")
            self.assertEqual(record.administered_by_name, "田中")
            self.assertEqual(record.confirmed_by_name, "佐藤")

    def test_administer_cannot_confirm_by_same_staff(self):
        from medication_service import administer_medication

        staff_a = uuid4()
        with Session(self.engine) as session:
            record = self._request(session)
            record_id = record.id
            administer_medication(session, medication_id=record_id,
                                  staff_name="田中", staff_user_id=staff_a)
            session.commit()
            from fastapi import HTTPException
            from medication_service import confirm_medication as confirm

            with self.assertRaises(HTTPException):
                confirm(session, medication_id=record_id,
                        staff_name="田中", staff_user_id=staff_a)

    def test_duplicate_request_rejected(self):
        with Session(self.engine) as session:
            self._request(session)
            session.commit()

        with Session(self.engine) as session:
            from fastapi import HTTPException

            with self.assertRaises(HTTPException):
                self._request(session, administration_time="15:00")

    def test_invalid_time_rejected(self):
        with Session(self.engine) as session:
            from fastapi import HTTPException

            with self.assertRaises(HTTPException):
                self._request(session, administration_time="25:00")

    def test_void_keeps_record(self):
        from medication_service import void_medication

        with Session(self.engine) as session:
            record = self._request(session)
            session.commit()
            record_id = record.id

        with Session(self.engine) as session:
            void_medication(session, medication_id=record_id,
                            staff_name="園長", reason="保護者が取り下げ")
            session.commit()

        with Session(self.engine) as session:
            record = session.get(MedicationAdministration, record_id)
            self.assertEqual(record.status, "void")
            self.assertEqual(record.void_reason, "保護者が取り下げ")


class EligibilityServiceTests(unittest.TestCase):
    def test_high_fever_blocks(self):
        from attendance_eligibility_service import judge_attendance

        result = judge_attendance(target_date=date(2026, 11, 5), temperature_c=38.6)
        self.assertFalse(result.allowed)
        self.assertEqual(result.level, "review")

    def test_caution_fever(self):
        from attendance_eligibility_service import judge_attendance

        result = judge_attendance(target_date=date(2026, 11, 5), temperature_c=37.6)
        self.assertFalse(result.allowed)
        self.assertEqual(result.level, "caution")

    def test_fever_return_after_two_days(self):
        from attendance_eligibility_service import judge_attendance

        # 解熱から1日: まだ登園目安に満たない
        result = judge_attendance(
            target_date=date(2026, 11, 6), fever_free_since=date(2026, 11, 5))
        self.assertFalse(result.allowed)
        # 解熱から2日: 目安を満たす
        result = judge_attendance(
            target_date=date(2026, 11, 7), fever_free_since=date(2026, 11, 5))
        self.assertTrue(result.allowed)
        self.assertEqual(result.level, "ok")

    def test_influenza_blocked_until_fever_free_window(self):
        from attendance_eligibility_service import judge_attendance

        # インフルエンザ: 解熱翌日は不許可
        result = judge_attendance(
            target_date=date(2026, 11, 6), diagnosis="インフルエンザA型",
            fever_free_since=date(2026, 11, 5),
        )
        self.assertFalse(result.allowed)
        # 発熱判定（review）と感染症判定（blocked）の両方で不許可。統合レベルは
        # より厳しい方が採用されるが、ここでは review が相当する。
        self.assertIn(result.level, {"review", "blocked"})
        self.assertFalse(result.allowed)

    def test_unknown_diagnosis_is_caution_not_block(self):
        from attendance_eligibility_service import judge_attendance

        result = judge_attendance(target_date=date(2026, 11, 5), diagnosis="手足口病")
        self.assertTrue(result.allowed)
        self.assertEqual(result.level, "caution")

    def test_no_conditions_is_ok(self):
        from attendance_eligibility_service import judge_attendance

        result = judge_attendance(target_date=date(2026, 11, 5))
        self.assertTrue(result.allowed)
        self.assertEqual(result.level, "ok")


class EligibilityFacilitySettingsTests(unittest.TestCase):
    """施設別基準（FacilitySettings）で判定が変わることの確認（改善案8）。"""

    def test_custom_return_days(self):
        from attendance_eligibility_service import judge_attendance

        # 園の基準が「解熱後1日」の場合、解熱翌日でも登園可
        result = judge_attendance(
            target_date=date(2026, 11, 6), fever_free_since=date(2026, 11, 5),
            return_days=1,
        )
        self.assertTrue(result.allowed)

    def test_custom_thresholds(self):
        from attendance_eligibility_service import judge_attendance

        # 園の要検討しきい値が39.0の場合、38.5°C は caution 止まり
        result = judge_attendance(
            target_date=date(2026, 11, 5), temperature_c=38.5,
            caution_c=37.5, review_c=39.0,
        )
        self.assertFalse(result.allowed)
        self.assertEqual(result.level, "caution")


class MedicationRouterTests(unittest.TestCase):
    """与薬ルーター（/children/{id}/health/medications）のテスト。"""

    def setUp(self):
        self.engine = _build_engine()
        with Session(self.engine) as session:
            self.child = _create_child(session)
            session.commit()
            self.child_id = self.child.id

    def test_medication_flow_via_service_and_router_helpers(self):
        # サービス層の状態遷移がルーターの期待（requested→administered→confirmed）と整合すること
        from medication_service import administer_medication, confirm_medication, request_medication
        from fastapi import HTTPException

        staff_a, staff_b = uuid4(), uuid4()
        with Session(self.engine) as session:
            record = request_medication(
                session, child_id=self.child_id, target_date=date(2026, 11, 5),
                medication_name="抗菌薬", administration_time="12:00", dosage="5ml",
            )
            session.commit()
            record_id = record.id

            administer_medication(session, medication_id=record_id, staff_name="田中", staff_user_id=staff_a)
            session.commit()

            # 実施者の自己確認は403
            with self.assertRaises(HTTPException) as ctx:
                confirm_medication(session, medication_id=record_id, staff_name="田中", staff_user_id=staff_a)
            self.assertEqual(ctx.exception.status_code, 403)

            confirm_medication(session, medication_id=record_id, staff_name="佐藤", staff_user_id=staff_b)
            session.commit()

        with Session(self.engine) as session:
            record = session.get(MedicationAdministration, record_id)
            self.assertEqual(record.status, "administered")
            self.assertIsNotNone(record.confirmed_at)


if __name__ == "__main__":
    unittest.main()
