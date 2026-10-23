"""Contract and feature tests for child record custom fields (Steps 6-11)."""

import unittest
from datetime import date
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from child_records.models import ChildRecordSettingVersion
from child_records.router import progress_router, router, settings_router
from child_records.settings import (
    default_config,
    new_custom_field_key,
    save_child_record_settings_version,
    update_custom_field_definitions,
)
import child_records.router as child_records_router
from models import Child, ChildStatus, Classroom


class ChildRecordCustomFieldTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.include_router(settings_router)
        self.app.include_router(progress_router)
        self.current_user = StaffUser(role=Role.ADMIN, name="園長", user_id=uuid4())

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_current_user():
            return self.current_user

        self.app.dependency_overrides[child_records_router.get_session] = override_get_session
        self.app.dependency_overrides[
            child_records_router.get_current_staff_user
        ] = override_current_user
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(classroom)
            session.flush()
            self.classroom_id = classroom.id
            child = Child(
                last_name="田中",
                first_name="花",
                last_name_kana="タナカ",
                first_name_kana="ハナ",
                birth_date=date(2024, 5, 1),
                enrollment_date=date(2025, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
            )
            session.add(child)
            session.commit()
            session.refresh(child)
            self.child_id = child.id

    def _settings_form_data(self, extra=None):
        data = {
            "preset_key": "standard",
            "progress_record_view_scope": "all_staff",
            "effective_from": "2026-04-01",
            "interval_age_0": "3",
            "interval_age_1": "3",
            "interval_age_2": "3",
            "interval_age_3": "3",
            "interval_age_4": "3",
            "interval_final_year": "3",
            "enabled_fields": ["observed_on", "child_state", "sensitivity"],
            "required_fields": ["observed_on", "child_state"],
        }
        if extra:
            data.update(extra)
        return data

    def test_new_custom_field_key_returns_prefixed_uuid4(self):
        key = new_custom_field_key()
        self.assertTrue(key.startswith("cf_"))
        raw_uuid = key.replace("cf_", "")
        parsed = UUID(raw_uuid)
        self.assertEqual(parsed.version, 4)

    def test_update_preserves_existing_keys_when_label_renamed(self):
        existing = [
            {"key": "cf_abc", "label": "アレルギー特記事項", "field_type": "text"}
        ]
        incoming = [
            {"key": "cf_abc", "label": "アレルギー・配慮事項", "field_type": "text"}
        ]
        updated = update_custom_field_definitions(existing, incoming)
        self.assertEqual(len(updated), 1)
        self.assertEqual(updated[0]["key"], "cf_abc")
        self.assertEqual(updated[0]["label"], "アレルギー・配慮事項")

    def test_setting_version_increments_on_save(self):
        config = default_config("standard")
        with Session(self.engine) as session:
            v1 = save_child_record_settings_version(
                session, config, str(self.current_user.user_id)
            )
            self.assertEqual(v1.version_no, 1)
            v2 = save_child_record_settings_version(
                session, config, str(self.current_user.user_id)
            )
            self.assertEqual(v2.version_no, 2)

    def test_settings_save_concurrent_update_returns_409(self):
        data = self._settings_form_data()
        r1 = self.client.post("/settings/child-records", data=data, follow_redirects=False)
        self.assertEqual(r1.status_code, 303)
        with Session(self.engine) as session:
            setting = session.exec(select(ChildRecordSettingVersion)).one()
            expected_version = setting.lock_version
        # 保存後の版番号を指定すれば更新は成功する。
        r2 = self.client.post(
            "/settings/child-records",
            data={**data, "expected_version": str(expected_version)},
            follow_redirects=False,
        )
        self.assertEqual(r2.status_code, 303)
        # 古い版番号を指定すると 409 となる。
        r3 = self.client.post(
            "/settings/child-records",
            data={**data, "expected_version": str(expected_version)},
            follow_redirects=False,
        )
        self.assertEqual(r3.status_code, 409)

    def test_settings_ui_contains_custom_fields_dom(self):
        response = self.client.get("/settings/child-records")
        self.assertEqual(response.status_code, 200)
        self.assertIn("custom_fields", response.text)

    def test_progress_record_saves_and_displays_custom_field_values(self):
        # 園独自項目を1件保存する。
        settings_data = self._settings_form_data(
            {"custom_field_labels": "アレルギー記入\n行事への関わり"}
        )
        r = self.client.post(
            "/settings/child-records", data=settings_data, follow_redirects=False
        )
        self.assertEqual(r.status_code, 303)
        with Session(self.engine) as session:
            setting = session.exec(select(ChildRecordSettingVersion)).one()
            custom_fields = [
                item
                for item in setting.config["record_types"]["observation_log"]["fields"]
                if item.get("custom")
            ]
            self.assertEqual(len(custom_fields), 2)
            custom_key = custom_fields[0]["key"]
            self.assertTrue(custom_key.startswith("cf_"))

        period_start = "2026-07-01"
        period_end = "2026-09-30"
        form = self.client.get(
            f"/children/{self.child_id}/progress-records/new?"
            f"period_start={period_start}&period_end={period_end}"
        )
        self.assertEqual(form.status_code, 200)
        self.assertIn(f'name="cf_{custom_key.removeprefix("cf_")}"', form.text)

        created = self.client.post(
            f"/children/{self.child_id}/records",
            data={
                "observed_on": "2026-07-02",
                "child_state": "積み木を高く積んだ。",
                "visibility": "shared",
                "sensitivity": "normal",
                "categories": ["興味・遊び"],
                f"cf_{custom_key.removeprefix('cf_')}": "卵アレルギーあり",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)

        timeline = self.client.get(f"/children/{self.child_id}/records")
        self.assertEqual(timeline.status_code, 200)
        self.assertIn("卵アレルギーあり", timeline.text)
