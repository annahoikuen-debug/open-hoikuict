"""医療同意引き継ぎ（フェーズA W3）のテスト。

- parent_medical_service.diff_from_baseline の単体テスト
- routers/parent_medical.py のゼロ差分自動承認フロー統合テスト
- facility_settings_service.medical_consent_auto_approve のトグルテスト
"""
from __future__ import annotations

import unittest
from datetime import date
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from fastapi import FastAPI
from fastapi.testclient import TestClient

from models import (
    Child,
    ChildStatus,
    Family,
    ParentAccount,
    ParentChildLink,
    ParentMedicalResponse,
)
from parent_medical_service import (
    current_values,
    diff_from_baseline,
    latest_answer,
    latest_consent,
    revision as compute_revision,
)
from facility_settings_service import medical_consent_auto_approve
import routers.parent_medical as parent_medical_module
from routers.parent_portal import mock_login_router
from testing_helpers import configure_test_environment


def _build_engine():
    import models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


class DiffFromBaselineTests(unittest.TestCase):
    """diff_from_baseline の単体テスト。"""

    def test_diff_from_baseline_with_changes(self):
        new = {"blood_type": "A型", "primary_doctor_name": "田中医院", "hospital_name": "市立病院"}
        last = {"blood_type": "B型", "primary_doctor_name": "田中医院", "hospital_name": "市立病院"}
        self.assertEqual(
            diff_from_baseline(new, last),
            {"blood_type": "A型"},
        )

    def test_diff_from_baseline_no_changes(self):
        new = {"blood_type": "A型", "primary_doctor_name": "田中医院"}
        last = {"blood_type": "A型", "primary_doctor_name": "田中医院"}
        self.assertEqual(diff_from_baseline(new, last), {})

    def test_diff_from_baseline_none_last_approved(self):
        new = {"blood_type": "A型", "primary_doctor_name": "田中医院", "hospital_name": ""}
        self.assertEqual(
            diff_from_baseline(new, None),
            {"blood_type": "A型", "primary_doctor_name": "田中医院"},
        )

    def test_diff_from_baseline_empty_string_is_different_from_baseline(self):
        new = {"blood_type": "", "primary_doctor_name": "田中医院"}
        last = {"blood_type": "B型", "primary_doctor_name": "田中医院"}
        self.assertEqual(diff_from_baseline(new, last), {"blood_type": ""})

    def test_diff_from_baseline_new_field_not_in_last(self):
        new = {"blood_type": "A型", "primary_doctor_name": "田中医院"}
        last = {"blood_type": "A型"}
        self.assertEqual(diff_from_baseline(new, last), {"primary_doctor_name": "田中医院"})

    def test_diff_from_baseline_none_value_treated_as_different(self):
        new = {"blood_type": None, "primary_doctor_name": "田中医院"}
        last = {"blood_type": "B型", "primary_doctor_name": "田中医院"}
        self.assertEqual(diff_from_baseline(new, last), {"blood_type": None})

    def test_diff_from_baseline_all_fields_changed(self):
        new = {"blood_type": "A型", "primary_doctor_name": "田中医院", "hospital_name": "市立病院"}
        last = {"blood_type": "B型", "primary_doctor_name": "佐藤医院", "hospital_name": "私立病院"}
        self.assertEqual(
            diff_from_baseline(new, last),
            {"blood_type": "A型", "primary_doctor_name": "田中医院", "hospital_name": "市立病院"},
        )

    def test_diff_from_baseline_whitespace_only_is_different(self):
        new = {"blood_type": "  ", "primary_doctor_name": "田中医院"}
        last = {"blood_type": "B型", "primary_doctor_name": "田中医院"}
        self.assertEqual(diff_from_baseline(new, last), {"blood_type": "  "})

    def test_diff_from_baseline_empty_new_and_none_last(self):
        new = {"blood_type": "", "primary_doctor_name": ""}
        self.assertEqual(diff_from_baseline(new, None), {})


class FacilitySettingsAutoApproveTests(unittest.TestCase):
    """facility_settings_service.medical_consent_auto_approve のテスト。"""

    def setUp(self):
        self.engine = _build_engine()

    def test_medical_consent_auto_approve_default_false(self):
        with Session(self.engine) as session:
            self.assertFalse(medical_consent_auto_approve(session))

    def test_medical_consent_auto_approve_enabled(self):
        from models import FacilitySettings

        with Session(self.engine) as session:
            session.add(FacilitySettings(id=1, medical_consent_auto_approve=True))
            session.commit()
        with Session(self.engine) as session:
            self.assertTrue(medical_consent_auto_approve(session))


class FacilitySettingsServiceExtraTests(unittest.TestCase):
    """facility_settings_service の追加単体テスト。"""

    def setUp(self):
        self.engine = _build_engine()
        from models import FacilitySettings, FacilitySettingsHistory
        self.FacilitySettings = FacilitySettings
        self.FacilitySettingsHistory = FacilitySettingsHistory

    def test_record_change_history_only_changed_fields(self):
        from facility_settings_service import record_change_history

        settings = self.FacilitySettings(
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
            rows = session.exec(select(self.FacilitySettingsHistory)).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].field_name, "final_pickup_time")
            self.assertEqual(rows[0].old_value, "19:00")
            self.assertEqual(rows[0].new_value, "19:30")
            self.assertEqual(rows[0].changed_by_name, "園長")

    def test_record_change_history_no_changes_records_nothing(self):
        from facility_settings_service import record_change_history

        settings = self.FacilitySettings(
            id=1, final_pickup_time="19:00",
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
            rows = session.exec(select(self.FacilitySettingsHistory)).all()
            self.assertEqual(len(rows), 0)

    def test_dinner_reminder_time_default(self):
        from facility_settings_service import dinner_reminder_time

        with Session(self.engine) as session:
            self.assertEqual(dinner_reminder_time(session), "19:00")


class ParentMedicalServiceUnitTests(unittest.TestCase):
    """parent_medical_service の単体テスト。"""

    def setUp(self):
        self.engine = _build_engine()

    def test_revision_deterministic(self):
        from parent_medical_service import revision

        values = {"blood_type": "A型"}
        latest = None
        consent = None
        r1 = revision(1, 1, values, latest, consent)
        r2 = revision(1, 1, values, latest, consent)
        self.assertEqual(r1, r2)
        self.assertEqual(len(r1), 64)  # SHA-256 hex digest

    def test_revision_changes_with_values(self):
        from parent_medical_service import revision

        r1 = revision(1, 1, {"blood_type": "A型"}, None, None)
        r2 = revision(1, 1, {"blood_type": "B型"}, None, None)
        self.assertNotEqual(r1, r2)

    def test_staff_medical_context_returns_choices_and_statuses(self):
        from parent_medical_service import staff_medical_context

        with Session(self.engine) as session:
            ctx = staff_medical_context(session, 999)
            self.assertIn("choices", ctx)
            self.assertIn("statuses", ctx)
            self.assertIn("unanswered", ctx)
            self.assertEqual(ctx["unanswered"], "未回答（事前承諾なし）")


class FormAnswersTests(unittest.TestCase):
    """parent_medical_service.form_answers のバリデーションテスト。"""

    def test_form_answers_normal(self):
        from parent_medical_service import form_answers

        class FakeForm:
            def get(self, key, default=None):
                return {
                    "blood_type": "A型",
                    "primary_doctor_name": "田中医院",
                    "primary_doctor_phone": "03-1234-5678",
                    "primary_doctor_address": "東京都",
                    "hospital_name": "市立病院",
                    "hospital_phone": "03-9876-5432",
                    "xray_answer": "agree",
                }.get(key, default)

        baseline = {key: "" for key in ["blood_type", "primary_doctor_name", "primary_doctor_phone",
                                         "primary_doctor_address", "hospital_name", "hospital_phone"]}
        answers, xray = form_answers(FakeForm(), baseline)
        self.assertEqual(answers["blood_type"], "A型")
        self.assertEqual(xray, "agree")

    def test_form_answers_invalid_blood_type(self):
        from parent_medical_service import form_answers

        class FakeForm:
            def get(self, key, default=None):
                return {"blood_type": "XY型", "primary_doctor_name": "", "primary_doctor_phone": "",
                         "primary_doctor_address": "", "hospital_name": "", "hospital_phone": "",
                         "xray_answer": None}.get(key, default)

        baseline = {key: "" for key in ["blood_type", "primary_doctor_name", "primary_doctor_phone",
                                         "primary_doctor_address", "hospital_name", "hospital_phone"]}
        with self.assertRaises(ValueError):
            form_answers(FakeForm(), baseline)

    def test_form_answers_hospital_phone_without_name(self):
        from parent_medical_service import form_answers

        class FakeForm:
            def get(self, key, default=None):
                return {"blood_type": "", "primary_doctor_name": "", "primary_doctor_phone": "",
                         "primary_doctor_address": "", "hospital_name": "", "hospital_phone": "03-0000-0000",
                         "xray_answer": None}.get(key, default)

        baseline = {key: "" for key in ["blood_type", "primary_doctor_name", "primary_doctor_phone",
                                         "primary_doctor_address", "hospital_name", "hospital_phone"]}
        with self.assertRaises(ValueError):
            form_answers(FakeForm(), baseline)


class MedicalConsentAutoApproveIntegrationTests(unittest.TestCase):
    """medical_form エンドポイントのゼロ差分自動承認統合テスト。"""

    def setUp(self):
        configure_test_environment()
        self.engine = _build_engine()
        self.app = FastAPI()
        self.app.include_router(parent_medical_module.router)
        self.app.include_router(mock_login_router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[parent_medical_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            self.family = Family(family_name="山田")
            session.add(self.family)
            session.flush()

            self.parent = ParentAccount(
                family_id=self.family.id,
                email="parent@example.com",
                display_name="山田保護者",
            )
            session.add(self.parent)
            session.flush()

            self.child = Child(
                family_id=self.family.id,
                last_name="山田",
                first_name="太郎",
                last_name_kana="ヤマダ",
                first_name_kana="タロウ",
                status=ChildStatus.enrolled,
                birth_date=date(2021, 5, 10),
                enrollment_date=date(2024, 4, 1),
            )
            session.add(self.child)
            session.flush()

            session.add(
                ParentChildLink(
                    parent_account_id=self.parent.id, child_id=self.child.id
                )
            )
            session.commit()

            self.child_id = self.child.id
            self.parent_id = self.parent.id

    def _login(self):
        self.client.post(
            "/parent-portal/login",
            data={"parent_account_id": str(self.parent_id)},
        )

    def _get_latest_consent(self):
        with Session(self.engine) as session:
            return session.exec(
                select(ParentMedicalResponse).where(
                    ParentMedicalResponse.child_id == self.child_id,
                ).order_by(ParentMedicalResponse.submitted_at.desc())
            ).first()

    def _post_medical(self, *, toggle_on: bool, answers: dict[str, str], xray: str = "agree"):
        """medical_form に POST し、回答を作成する。"""
        from models import FacilitySettings

        with Session(self.engine) as session:
            if toggle_on:
                session.add(FacilitySettings(id=1, medical_consent_auto_approve=True))
                session.commit()

            # revision をサーバー側と同じロジックで計算する
            baseline = current_values(session, self.child_id)
            latest = latest_answer(session, self.child_id, self.parent_id)
            consent = latest_consent(session, self.child_id)
            rev = compute_revision(self.child_id, self.parent_id, baseline, latest, consent)

        self._login()
        form_data = {
            "action": "send",
            "revision": rev,
            "xray_answer": xray,
            **answers,
        }
        response = self.client.post(
            f"/parent-portal/children/{self.child_id}/medical",
            data=form_data,
            follow_redirects=False,
        )
        return response

    def test_zero_diff_toggle_on_auto_approved(self):
        """ゼロ差分 + トグルON → auto_approved=True, status=approved。"""
        # まず通常回答を作成（差分ありで保留状態）
        self._post_medical(
            toggle_on=False,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
        )

        with Session(self.engine) as session:
            consent = session.exec(
                select(ParentMedicalResponse).where(
                    ParentMedicalResponse.child_id == self.child_id,
                ).order_by(ParentMedicalResponse.submitted_at.desc())
            ).first()
            self.assertEqual(consent.status, "pending")
            self.assertFalse(consent.auto_approved)

        # 同じ内容で再送信（ゼロ差分、トグルON）
        response = self._post_medical(
            toggle_on=True,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            consents = session.exec(
                select(ParentMedicalResponse).where(
                    ParentMedicalResponse.child_id == self.child_id,
                ).order_by(ParentMedicalResponse.submitted_at.desc())
            ).all()
            latest = consents[0]
            self.assertEqual(latest.status, "approved")
            self.assertTrue(latest.auto_approved)
            self.assertEqual(latest.reviewed_by, "システム（自動承認）")

    def test_nonzero_diff_toggle_on_not_auto_approved(self):
        """差分あり + トグルON → status=pending（自動承認されない）。"""
        # まず通常回答を作成
        self._post_medical(
            toggle_on=False,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
        )

        # 異なる内容で再送信（差分あり、トグルON）
        response = self._post_medical(
            toggle_on=True,
            answers={
                "blood_type": "B型",  # 変更あり
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            consents = session.exec(
                select(ParentMedicalResponse).where(
                    ParentMedicalResponse.child_id == self.child_id,
                ).order_by(ParentMedicalResponse.submitted_at.desc())
            ).all()
            latest = consents[0]
            self.assertEqual(latest.status, "pending")
            self.assertFalse(latest.auto_approved)

    def test_zero_diff_toggle_off_not_auto_approved(self):
        """ゼロ差分 + トグルOFF → status=pending（自動承認されない）。"""
        # まず通常回答を作成
        self._post_medical(
            toggle_on=False,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
        )

        # 同じ内容で再送信（ゼロ差分、トグルOFF）
        response = self._post_medical(
            toggle_on=False,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            consents = session.exec(
                select(ParentMedicalResponse).where(
                    ParentMedicalResponse.child_id == self.child_id,
                ).order_by(ParentMedicalResponse.submitted_at.desc())
            ).all()
            latest = consents[0]
            self.assertEqual(latest.status, "pending")
            self.assertFalse(latest.auto_approved)


class MedicalConsentAutoApproveEdgeTests(unittest.TestCase):
    """medical_form エンドポイントのエッジケース統合テスト。"""

    def setUp(self):
        configure_test_environment()
        self.engine = _build_engine()
        self.app = FastAPI()
        self.app.include_router(parent_medical_module.router)
        self.app.include_router(mock_login_router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[parent_medical_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            self.family = Family(family_name="山田")
            session.add(self.family)
            session.flush()

            self.parent = ParentAccount(
                family_id=self.family.id,
                email="parent@example.com",
                display_name="山田保護者",
            )
            session.add(self.parent)
            session.flush()

            self.child = Child(
                family_id=self.family.id,
                last_name="山田",
                first_name="太郎",
                last_name_kana="ヤマダ",
                first_name_kana="タロウ",
                status=ChildStatus.enrolled,
                birth_date=date(2021, 5, 10),
                enrollment_date=date(2024, 4, 1),
            )
            session.add(self.child)
            session.flush()

            session.add(
                ParentChildLink(
                    parent_account_id=self.parent.id, child_id=self.child.id
                )
            )
            session.commit()

            self.child_id = self.child.id
            self.parent_id = self.parent.id

    def _login(self):
        self.client.post(
            "/parent-portal/login",
            data={"parent_account_id": str(self.parent_id)},
        )

    def _post_medical(self, *, toggle_on: bool, answers: dict[str, str], xray: str = "agree"):
        from models import FacilitySettings

        with Session(self.engine) as session:
            if toggle_on:
                session.add(FacilitySettings(id=1, medical_consent_auto_approve=True))
                session.commit()

            baseline = current_values(session, self.child_id)
            latest = latest_answer(session, self.child_id, self.parent_id)
            consent = latest_consent(session, self.child_id)
            rev = compute_revision(self.child_id, self.parent_id, baseline, latest, consent)

        self._login()
        form_data = {
            "action": "send",
            "revision": rev,
            "xray_answer": xray,
            **answers,
        }
        response = self.client.post(
            f"/parent-portal/children/{self.child_id}/medical",
            data=form_data,
            follow_redirects=False,
        )
        return response

    def test_zero_diff_xray_contact_auto_approved(self):
        """ゼロ差分 + トグルON + xray=contact でも auto_approved。"""
        self._post_medical(
            toggle_on=False,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
            xray="agree",
        )

        response = self._post_medical(
            toggle_on=True,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
            xray="contact",
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            latest = session.exec(
                select(ParentMedicalResponse).where(
                    ParentMedicalResponse.child_id == self.child_id,
                ).order_by(ParentMedicalResponse.submitted_at.desc())
            ).first()
            self.assertEqual(latest.status, "approved")
            self.assertTrue(latest.auto_approved)
            self.assertEqual(latest.xray_answer, "contact")

    def test_zero_diff_clear_hospital_is_a_change_not_auto_approved(self):
        """病院名クリアは最後の承認済み回答からの変更 → pending（自動承認されない）。"""
        self._post_medical(
            toggle_on=False,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
        )

        response = self._post_medical(
            toggle_on=True,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "",
                "hospital_phone": "",
                "clear_hospital": "yes",
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            latest = session.exec(
                select(ParentMedicalResponse).where(
                    ParentMedicalResponse.child_id == self.child_id,
                ).order_by(ParentMedicalResponse.submitted_at.desc())
            ).first()
            self.assertEqual(latest.status, "pending")
            self.assertFalse(latest.auto_approved)
            self.assertEqual(latest.answers["hospital_name"], "")

    def test_first_submission_no_last_approved_not_auto_approved(self):
        """初回承認済み回答なし + ゼロ差分 → status=pending（last_approvedがNoneなので差分ありとみなす）。"""
        # 既存の承認済み回答がない状態でトグルON
        response = self._post_medical(
            toggle_on=True,
            answers={
                "blood_type": "A型",
                "primary_doctor_name": "田中医院",
                "primary_doctor_phone": "03-1234-5678",
                "primary_doctor_address": "東京都",
                "hospital_name": "市立病院",
                "hospital_phone": "03-9876-5432",
            },
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            consents = session.exec(
                select(ParentMedicalResponse).where(
                    ParentMedicalResponse.child_id == self.child_id,
                ).order_by(ParentMedicalResponse.submitted_at.desc())
            ).all()
            latest = consents[0]
            self.assertEqual(latest.status, "pending")
            self.assertFalse(latest.auto_approved)


if __name__ == "__main__":
    unittest.main()
