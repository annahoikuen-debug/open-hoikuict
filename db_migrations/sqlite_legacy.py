"""SQLite legacy schema migrations extracted from database.py."""

from __future__ import annotations

from typing import Callable

from sqlalchemy import text
from sqlmodel import Session, select



def _db():
    import database
    return database


def _sqlite_migrations() -> list[tuple[str, Callable[[], None]]]:
    return [
        ("001_family_archive", _migrate_family_archive),
        ("002_add_child_columns", _migrate_add_child_columns),
        ("003_add_child_health_profile_columns", _migrate_add_child_health_profile_columns),
        ("004_add_attendance_columns", _migrate_add_attendance_columns),
        ("005_guardian_confirmation_columns", _migrate_guardian_confirmation_columns),
        ("006_pickup_history_columns", _migrate_pickup_history_columns),
        ("007_add_daily_contact_columns", _migrate_add_daily_contact_columns),
        ("008_spec_20260924_columns", _migrate_spec_20260924_columns),
        ("009_observation_sharing_columns", _migrate_observation_sharing_columns),
        ("010_add_parent_account_columns", _migrate_add_parent_account_columns),
        ("011_add_guardian_columns", _migrate_add_guardian_columns),
        ("012_parent_mail_delivery_columns", _migrate_parent_mail_delivery_columns),
        ("013_add_family_columns", _migrate_add_family_columns),
        ("014_add_message_columns", _migrate_add_message_columns),
        ("015_data_transfer_audit", _migrate_data_transfer_audit),
        ("016_add_meeting_note_columns", _migrate_add_meeting_note_columns),
        ("017_notice_columns", _migrate_notice_columns),
        ("018_document_review_columns", _migrate_document_review_columns),
        ("019_add_calendar_columns", _migrate_add_calendar_columns),
        ("020_survey_tables", _migrate_survey_tables),
        ("021_plan_document_child_record_columns", _migrate_plan_document_child_record_columns),
        ("022_monthly_sheet_columns", _migrate_monthly_sheet_columns),
        ("023_plan_document_action_columns", _migrate_plan_document_action_columns),
        ("024_plan_review_notification_columns", _migrate_plan_review_notification_columns),
        ("025_parent_push_delivery_columns", _migrate_parent_push_delivery_columns),
        ("026_billing_fee_labels", _migrate_billing_fee_labels),
        ("027_zengin_workflow", _migrate_zengin_workflow),
        ("028_care_certification_and_extended_care_columns", _migrate_care_certification_and_extended_care_columns),
        ("029_extended_care_billing_transfer", _migrate_extended_care_billing_transfer),
        ("030_family_bootstrap", _migrate_family_bootstrap),
        ("031_sync_health_records_from_legacy", _migrate_sync_health_records_from_legacy),
        ("032_shift_schedule_tables", _migrate_shift_schedule_tables),
        ("033_facility_settings", _migrate_facility_settings),
        ("034_paid_leave_tables", _migrate_paid_leave_tables),
        ("035_document_export_permissions", _migrate_document_export_permissions),
        ("036_document_export_history", _migrate_document_export_history),
        ("037_medication_administrations", _migrate_medication_administrations),
        ("038_shift_contracts_36_and_variable", _migrate_shift_schedule_tables),
        ("039_unavailability_status", _migrate_shift_schedule_tables),
        ("040_pims_attendance_tables", _migrate_pims_attendance_tables),
        ("041_shift_timefold_enhancements", _migrate_shift_timefold_enhancements),
        ("042_parent_push_preference_extra_mute_columns", _migrate_parent_push_preference_extra_mute_columns),
        ("043_message_templates_table", _migrate_message_templates_table),
        ("044_attendance_lock_version", _migrate_attendance_lock_version),
        ("045_parent_medical_responses", _migrate_parent_medical_table),
        ("046_daily_contact_review_columns", _migrate_daily_contact_review_columns),
        ("047_attendance_idempotency_key", _migrate_attendance_idempotency_key),
        ("048_smart_hud_simple_mode_and_nap_checks", _migrate_smart_hud_simple_mode_and_nap_checks),
        ("049_facility_settings_board_qr", _migrate_facility_settings_board_qr),
    ]


def _migrate_facility_settings() -> None:
    from models import FacilitySettings, FacilitySettingsHistory
    with _db().engine.begin() as conn:
        FacilitySettings.metadata.create_all(
            conn, tables=[FacilitySettings.__table__, FacilitySettingsHistory.__table__]
        )
    # 追加カラム（updated_by_* / 履歴テーブル）を冪等に追加
    with _db().engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(facility_settings)")}
        if columns:
            if "updated_by_user_id" not in columns:
                conn.exec_driver_sql(
                    "ALTER TABLE facility_settings ADD COLUMN updated_by_user_id CHAR(32) REFERENCES users(id)"
                )
            if "updated_by_name" not in columns:
                conn.exec_driver_sql("ALTER TABLE facility_settings ADD COLUMN updated_by_name VARCHAR")


def _migrate_paid_leave_tables() -> None:
    from models import StaffPaidLeave, StaffPaidLeaveRequest
    with _db().engine.begin() as conn:
        StaffPaidLeave.metadata.create_all(
            conn,
            tables=[StaffPaidLeave.__table__, StaffPaidLeaveRequest.__table__],
        )


def _migrate_medication_administrations() -> None:
    from models import MedicationAdministration
    with _db().engine.begin() as conn:
        MedicationAdministration.metadata.create_all(
            conn, tables=[MedicationAdministration.__table__],
        )
    # 登園判定の施設別基準（改善案8）＋通知種別ミュート（改善案6 後続）
    with _db().engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(facility_settings)")}
        if columns:
            for name, kind in {
                "fever_return_days": "INTEGER DEFAULT 2 NOT NULL",
                "fever_caution_c": "VARCHAR(4) DEFAULT '37.5'",
                "fever_review_c": "VARCHAR(4) DEFAULT '38.0'",
            }.items():
                if name not in columns:
                    conn.exec_driver_sql(f"ALTER TABLE facility_settings ADD COLUMN {name} {kind}")
        pref_columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(parent_push_preferences)")}
        if pref_columns:
            for name in ("closure_notice_enabled", "emergency_notice_enabled", "punch_correction_notice_enabled"):
                if name not in pref_columns:
                    conn.exec_driver_sql(f"ALTER TABLE parent_push_preferences ADD COLUMN {name} BOOLEAN DEFAULT 1 NOT NULL")


def _migrate_observation_sharing_columns() -> None:
    with _db().engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(child_observation_logs)")}
        if columns:
            for name, kind in {"visibility": "VARCHAR", "shared_staff_ids": "JSON"}.items():
                if name not in columns:
                    conn.exec_driver_sql(f"ALTER TABLE child_observation_logs ADD COLUMN {name} {kind}")


def _migrate_spec_20260924_columns() -> None:
    additions = {
        "daily_contact_replies": {
            "pending_draft": "JSON",
            "reviewed_by_staff_id": "CHAR(32)",
            "reviewed_by_name": "VARCHAR",
            "rejection_reason": "VARCHAR",
            "reviewed_at": "DATETIME",
        },
        "attendance_verification_histories": {
            "reason": "VARCHAR", "previous_status": "VARCHAR", "actor_user_id": "CHAR(32)",
        },
        "facility_settings": {
            "contact_reply_review_required": "BOOLEAN DEFAULT 0",
        },
        "attendance_records": {
            "lock_version": "INTEGER DEFAULT 1",
        },
    }
    with _db().engine.begin() as conn:
        for table, fields in additions.items():
            columns = {row[1] for row in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if not columns:
                continue
            for name, kind in fields.items():
                if name not in columns:
                    conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")


def _migrate_family_archive() -> None:
    # Additive and idempotent; never infer archived state from existing records.
    with _db().engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(families)")}
        if "archived_at" not in columns:
            conn.exec_driver_sql("ALTER TABLE families ADD COLUMN archived_at DATETIME")
        conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_families_archived_at ON families (archived_at)")


def _migrate_add_child_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            cols = _db()._table_columns("children")
            if not cols:
                return
            if "sex" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN sex VARCHAR(16) NOT NULL DEFAULT 'not_set'"))
            if "photo_id" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN photo_id VARCHAR(32)"))
            if "home_address" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN home_address VARCHAR"))
            if "home_phone" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN home_phone VARCHAR"))
            if "older_sibling_id" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN older_sibling_id INTEGER REFERENCES children(id)"))
            if "classroom_id" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN classroom_id INTEGER REFERENCES classrooms(id)"))
            if "registration_verification_name" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN registration_verification_name VARCHAR(200)"))
            if "registration_verification_name_type" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN registration_verification_name_type VARCHAR(16)"))
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("children column", exc)


def _migrate_add_child_health_profile_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            cols = _db()._table_columns("child_health_profiles")
            if not cols:
                return
            boolean_columns = (
                "has_allergy",
                "has_epipen",
                "has_anaphylaxis",
                "has_febrile_seizure",
                "has_nursemaids_elbow",
                "has_medication",
            )
            for column_name in boolean_columns:
                if column_name not in cols:
                    conn.execute(
                        text(
                            f"ALTER TABLE child_health_profiles ADD COLUMN {column_name} "
                            "BOOLEAN DEFAULT 0 NOT NULL"
                        )
                    )
            if "other_management_items" not in cols:
                conn.execute(
                    text("ALTER TABLE child_health_profiles ADD COLUMN other_management_items VARCHAR")
                )

            # Carry forward only legacy values whose meaning is equivalent.
            if "epipen_required" in cols:
                conn.execute(
                    text(
                        "UPDATE child_health_profiles SET has_epipen = 1 "
                        "WHERE epipen_required = 1"
                    )
                )
            allergy_cols = _db()._table_columns("child_allergies")
            if {"child_id", "is_active"}.issubset(allergy_cols):
                conn.execute(
                    text(
                        "UPDATE child_health_profiles SET has_allergy = 1 "
                        "WHERE EXISTS ("
                        "SELECT 1 FROM child_allergies "
                        "WHERE child_allergies.child_id = child_health_profiles.child_id "
                        "AND child_allergies.is_active = 1"
                        ")"
                    )
                )
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("child health profile column", exc)


def _migrate_add_attendance_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            cols = _db()._table_columns("attendance_records")
            if not cols:
                return
            if "planned_pickup_time" not in cols:
                conn.execute(text("ALTER TABLE attendance_records ADD COLUMN planned_pickup_time VARCHAR"))
            if "pickup_person" not in cols:
                conn.execute(text("ALTER TABLE attendance_records ADD COLUMN pickup_person VARCHAR"))
            if "snack_required" not in cols:
                conn.execute(text("ALTER TABLE attendance_records ADD COLUMN snack_required BOOLEAN DEFAULT 0 NOT NULL"))
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("attendance column", exc)


def _migrate_guardian_confirmation_columns() -> None:
    columns = _db()._table_columns("attendance_records")
    if not columns:
        return
    with _db().engine.begin() as conn:
        if "pickup_snack_confirmed" not in columns:
            conn.execute(text("ALTER TABLE attendance_records ADD COLUMN pickup_snack_confirmed BOOLEAN NOT NULL DEFAULT 0"))
            # Existing false values meant 'not needed'; retain that interpretation.
            conn.execute(text("UPDATE attendance_records SET pickup_snack_confirmed = 1"))
        if "actual_pickup_person" not in columns:
            conn.execute(text("ALTER TABLE attendance_records ADD COLUMN actual_pickup_person VARCHAR"))


def _migrate_pickup_history_columns() -> None:
    columns = _db()._table_columns("attendance_pickup_history")
    if not columns:
        return
    definitions = {
        "previous_snack_required": "BOOLEAN",
        "new_snack_required": "BOOLEAN",
        "changed_by_parent_account_id": "INTEGER REFERENCES parent_accounts(id)",
        "source": "VARCHAR NOT NULL DEFAULT 'staff'",
    }
    with _db().engine.begin() as conn:
        for name, definition in definitions.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE attendance_pickup_history ADD COLUMN {name} {definition}"))


def _migrate_add_daily_contact_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            cols = _db()._table_columns("daily_contact_entries")
            if not cols:
                return
            if "contact_type" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN contact_type VARCHAR DEFAULT 'present'"))
            if "absence_temperature" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN absence_temperature VARCHAR"))
            if "absence_symptoms" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN absence_symptoms VARCHAR"))
            if "absence_diagnosis" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN absence_diagnosis VARCHAR"))
            if "absence_note" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN absence_note VARCHAR"))
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("daily contact column", exc)


def _migrate_add_parent_account_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            cols = _db()._table_columns("parent_accounts")
            if not cols:
                return
            if "home_address" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN home_address VARCHAR"))
            if "workplace" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN workplace VARCHAR"))
            if "workplace_address" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN workplace_address VARCHAR"))
            if "workplace_phone" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN workplace_phone VARCHAR"))
            if "registration_verification_name" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN registration_verification_name VARCHAR(200)"))
            if "registration_verification_name_type" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN registration_verification_name_type VARCHAR(16)"))
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("parent account column", exc)


def _migrate_add_guardian_columns() -> None:
    try:
        columns = _db()._table_columns("guardians")
        if columns:
            with _db().engine.begin() as conn:
                if "photo_id" not in columns:
                    conn.execute(text("ALTER TABLE guardians ADD COLUMN photo_id VARCHAR(32)"))
                if "parent_account_id" not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE guardians ADD COLUMN parent_account_id "
                            "INTEGER REFERENCES parent_accounts(id)"
                        )
                    )
                if "email" not in columns:
                    conn.execute(text("ALTER TABLE guardians ADD COLUMN email VARCHAR"))
    except Exception as exc:
        _db()._log_migration_skip("guardian column", exc)


def _migrate_parent_mail_delivery_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            cols = _db()._table_columns("parent_mail_deliveries")
            if not cols:
                return
            if "processing_started_at" not in cols:
                conn.execute(text("ALTER TABLE parent_mail_deliveries ADD COLUMN processing_started_at DATETIME"))
            if "lease_expires_at" not in cols:
                conn.execute(text("ALTER TABLE parent_mail_deliveries ADD COLUMN lease_expires_at DATETIME"))
            if "next_retry_at" not in cols:
                conn.execute(text("ALTER TABLE parent_mail_deliveries ADD COLUMN next_retry_at DATETIME"))
            if "action_token_hash" not in cols:
                conn.execute(text("ALTER TABLE parent_mail_deliveries ADD COLUMN action_token_hash VARCHAR(64) REFERENCES credential_action_tokens(token_hash)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_parent_mail_deliveries_action_token_hash ON parent_mail_deliveries (action_token_hash)"))
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("parent mail delivery column", exc)


def _migrate_add_family_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            child_cols = _db()._table_columns("children")
            if child_cols and "family_id" not in child_cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN family_id INTEGER REFERENCES families(id)"))

            parent_cols = _db()._table_columns("parent_accounts")
            if parent_cols and "family_id" not in parent_cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN family_id INTEGER REFERENCES families(id)"))
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("family column", exc)


def _migrate_data_transfer_audit() -> None:
    with _db().engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(data_transfer_logs)")}
        if columns and "change_metadata" not in columns:
            connection.exec_driver_sql("ALTER TABLE data_transfer_logs ADD COLUMN change_metadata JSON NOT NULL DEFAULT '[]'")
        if columns and "actor_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE data_transfer_logs ADD COLUMN actor_id TEXT")


def _migrate_add_message_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            message_cols = _db()._table_columns("messages")
            if message_cols:
                if "parent_message_id" not in message_cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN parent_message_id INTEGER REFERENCES messages(id)"))
                if "deleted_at" not in message_cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN deleted_at DATETIME"))
                if "deleted_by" not in message_cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN deleted_by VARCHAR"))
                if "author_user_id" not in message_cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN author_user_id CHAR(32) REFERENCES users(id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_messages_author_user_id ON messages(author_user_id)"))
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("message column", exc)


def _migrate_add_meeting_note_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            columns = _db()._table_columns("meeting_notes")
            if columns and "search_text" not in columns:
                conn.execute(text("ALTER TABLE meeting_notes ADD COLUMN search_text VARCHAR"))
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("meeting note column", exc)


def _migrate_notice_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            columns = _db()._table_columns("notices")
            if columns and "body_html" not in columns:
                conn.execute(text("ALTER TABLE notices ADD COLUMN body_html VARCHAR"))
            if columns and "lock_version" not in columns:
                conn.execute(text("ALTER TABLE notices ADD COLUMN lock_version INTEGER DEFAULT 1"))
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("notice column", exc)


def _migrate_document_review_columns() -> None:
    with _db().engine.begin() as conn:
        columns = _db()._table_columns("document_review_requests")
        if columns and "return_acknowledged_at" not in columns:
            conn.execute(text(
                "ALTER TABLE document_review_requests "
                "ADD COLUMN return_acknowledged_at DATETIME"
            ))


def _migrate_add_calendar_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            calendar_cols = _db()._table_columns("calendars")
            if calendar_cols and "calendar_type" not in calendar_cols:
                conn.execute(text("ALTER TABLE calendars ADD COLUMN calendar_type VARCHAR DEFAULT 'staff_personal'"))
            user_cols = _db()._table_columns("users")
            if user_cols and "is_calendar_admin" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN is_calendar_admin BOOLEAN DEFAULT 0"))
            if user_cols and "staff_role" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN staff_role VARCHAR DEFAULT 'can_edit'"))
            if user_cols and "staff_sort_order" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN staff_sort_order INTEGER DEFAULT 100"))
            if user_cols and "can_manage_child_records" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN can_manage_child_records BOOLEAN DEFAULT 0"))
            if user_cols and "can_manage_billing_accounts" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users ADD COLUMN can_manage_billing_accounts "
                        "BOOLEAN DEFAULT 0 NOT NULL"
                    )
                )
                conn.execute(
                    text(
                        "UPDATE users SET can_manage_billing_accounts = 1 "
                        "WHERE email IN ('office@example.com', 'office@demo.open-hoikuict.example')"
                    )
                )
            if user_cols and "provisioning_source" not in user_cols:
                conn.execute(text("ALTER TABLE users ADD COLUMN provisioning_source VARCHAR DEFAULT 'manual'"))
                user_cols.append("provisioning_source")
            if user_cols and "provisioning_source" in user_cols:
                conn.execute(
                    text(
                        """
                        UPDATE users
                        SET provisioning_source = 'local_sample'
                        WHERE email IN (
                            'principal@example.com',
                            'chief@example.com',
                            'nurse@example.com',
                            'nutritionist@example.com',
                            'office@example.com',
                            'hiyoko@example.com',
                            'hiyoko-b@example.com',
                            'takenoko@example.com',
                            'risu-b@example.com',
                            'kinoko@example.com',
                            'usagi-b@example.com',
                            'panda-a@example.com',
                            'panda-b@example.com',
                            'kirin-a@example.com',
                            'kirin-b@example.com',
                            'zou-a@example.com',
                            'zou-b@example.com',
                            'part@example.com',
                            'arbeit@example.com'
                        )
                          AND (
                            provisioning_source IS NULL
                            OR provisioning_source = ''
                            OR provisioning_source = 'manual'
                          )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        UPDATE users
                        SET provisioning_source = 'web_demo'
                        WHERE email LIKE '%@demo.open-hoikuict.example'
                          AND (
                            provisioning_source IS NULL
                            OR provisioning_source = ''
                            OR provisioning_source = 'manual'
                          )
                        """
                    )
                )
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("calendar column", exc)


def _migrate_survey_tables() -> None:
    # New survey tables are created by SQLModel.metadata.create_all().
    # Keep this hook explicit for future additive indexes or backfills.
    return


def _migrate_monthly_sheet_columns() -> None:
    # Additive migration: existing monthly/individual plans remain untouched.
    with _db().engine.begin() as conn:
        columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(plan_documents)")}
        if not columns:
            return
        for name, kind in (("monthly_sheet", "JSON"), ("monthly_sheet_key", "VARCHAR")):
            if name not in columns:
                conn.exec_driver_sql(f"ALTER TABLE plan_documents ADD COLUMN {name} {kind}")
        conn.exec_driver_sql(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_monthly_sheet_key "
            "ON plan_documents(monthly_sheet_key) WHERE monthly_sheet_key IS NOT NULL"
        )


def _migrate_plan_document_child_record_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            columns = _db()._table_columns("plan_documents")
            if not columns:
                return
            additions = {
                "period_start": "VARCHAR",
                "period_end": "VARCHAR",
                "record_cycle_key": "VARCHAR",
                "setting_version_id": "INTEGER REFERENCES child_record_setting_versions(id)",
            }
            for column_name, column_type in additions.items():
                if column_name not in columns:
                    conn.execute(
                        text(
                            f"ALTER TABLE plan_documents ADD COLUMN {column_name} {column_type}"
                        )
                    )
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_plan_document_child_cycle "
                    "ON plan_documents(document_type, child_id, record_cycle_key) "
                    "WHERE record_cycle_key IS NOT NULL"
                )
            )
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("plan document child record columns", exc)


def _migrate_plan_document_action_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            columns = _db()._table_columns("plan_document_actions")
            if not columns:
                return
            if "actor_name" not in columns:
                conn.execute(
                    text(
                        "ALTER TABLE plan_document_actions "
                        "ADD COLUMN actor_name VARCHAR"
                    )
                )
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("plan document action columns", exc)


def _migrate_plan_review_notification_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            columns = _db()._table_columns("plan_review_notifications")
            if not columns:
                return
            additions = {
                "notification_kind": "VARCHAR NOT NULL DEFAULT 'review_request'",
                "decision_status": "VARCHAR",
                "decided_by_name": "VARCHAR",
                "decision_comment": "VARCHAR",
            }
            for column_name, column_type in additions.items():
                if column_name not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE plan_review_notifications "
                            f"ADD COLUMN {column_name} {column_type}"
                        )
                    )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_plan_review_notifications_notification_kind "
                    "ON plan_review_notifications(notification_kind)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_plan_review_notifications_decision_status "
                    "ON plan_review_notifications(decision_status)"
                )
            )
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("plan review notification columns", exc)


def _migrate_parent_push_delivery_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            columns = _db()._table_columns("parent_notification_deliveries")
            if not columns:
                return
            additions = {
                "expires_at": "DATETIME",
                "targets_resolved_at": "DATETIME",
                "planning_lease_expires_at": "DATETIME",
                "completed_at": "DATETIME",
                "accepted_at": "DATETIME",
                "shown_at": "DATETIME",
                "clicked_at": "DATETIME",
            }
            for column_name, column_type in additions.items():
                if column_name not in columns:
                    conn.execute(
                        text(
                            "ALTER TABLE parent_notification_deliveries "
                            f"ADD COLUMN {column_name} {column_type}"
                        )
                    )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_parent_notification_deliveries_targets_resolved_at "
                    "ON parent_notification_deliveries(targets_resolved_at)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_parent_notification_deliveries_planning_lease_expires_at "
                    "ON parent_notification_deliveries(planning_lease_expires_at)"
                )
            )
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("parent push delivery columns", exc)


def _migrate_parent_push_preference_extra_mute_columns() -> None:
    try:
        with _db().engine.connect() as conn:
            columns = _db()._table_columns("parent_push_preferences")
            if not columns:
                return
            additions = {
                "notice_published_enabled": "BOOLEAN NOT NULL DEFAULT 1",
                "survey_published_enabled": "BOOLEAN NOT NULL DEFAULT 1",
                "fever_notification_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            }
            for column_name, column_def in additions.items():
                if column_name not in columns:
                    conn.execute(
                        text(
                            f"ALTER TABLE parent_push_preferences "
                            f"ADD COLUMN {column_name} {column_def}"
                        )
                    )
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("parent push preference extra mute columns", exc)


def _migrate_attendance_idempotency_key() -> None:
    try:
        with _db().engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(attendance_records)")}
            if columns and "idempotency_key" not in columns:
                conn.exec_driver_sql("ALTER TABLE attendance_records ADD COLUMN idempotency_key VARCHAR(128)")
                conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_attendance_records_idempotency_key ON attendance_records (idempotency_key)")
    except Exception as exc:
        _db()._log_migration_skip("attendance_records idempotency_key column", exc)


def _migrate_attendance_lock_version() -> None:
    try:
        with _db().engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(attendance_records)")}
            if columns and "lock_version" not in columns:
                conn.exec_driver_sql("ALTER TABLE attendance_records ADD COLUMN lock_version INTEGER DEFAULT 1")
    except Exception as exc:
        _db()._log_migration_skip("attendance_records lock_version column", exc)


def _migrate_message_templates_table() -> None:
    try:
        from models import MessageTemplate
        with _db().engine.begin() as conn:
            MessageTemplate.metadata.create_all(conn, tables=[MessageTemplate.__table__])
    except Exception as exc:
        _db()._log_migration_skip("message templates table", exc)


def _migrate_billing_fee_labels() -> None:
    try:
        with _db().engine.connect() as conn:
            fee_cols = _db()._table_columns("fee_items")
            line_cols = _db()._table_columns("billing_charge_lines")
            if not fee_cols:
                return

            conn.execute(
                text(
                    """
                    UPDATE fee_items
                    SET name = '延長保育料（月額）'
                    WHERE code = 'monthly_childcare'
                      AND name IN ('保育料', '保育料（月額）')
                    """
                )
            )
            if line_cols:
                conn.execute(
                    text(
                        """
                        UPDATE billing_charge_lines
                        SET description = '延長保育料（月額）'
                        WHERE fee_item_id IN (
                            SELECT id FROM fee_items WHERE code = 'monthly_childcare'
                        )
                          AND description IN ('保育料', '保育料（月額）')
                        """
                    )
                )
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("billing fee label", exc)


def _migrate_zengin_workflow() -> None:
    with _db().engine.begin() as conn:
        profile_cols = _db()._table_columns("family_billing_profiles")
        export_cols = _db()._table_columns("zengin_exports")
        if export_cols:
            for name, sql_type in (("canceled_by", "VARCHAR"), ("canceled_at", "DATETIME")):
                if name not in export_cols:
                    conn.execute(text(f"ALTER TABLE zengin_exports ADD COLUMN {name} {sql_type}"))
        if profile_cols and "new_code_consumed_by_export_id" not in profile_cols:
            conn.execute(
                text(
                    "ALTER TABLE family_billing_profiles "
                    "ADD COLUMN new_code_consumed_by_export_id INTEGER "
                    "REFERENCES zengin_exports(id)"
                )
            )
        if profile_cols:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_family_billing_profiles_new_code_consumed_by_export_id "
                    "ON family_billing_profiles (new_code_consumed_by_export_id)"
                )
            )
        if export_cols and "submitted_at" not in export_cols:
            conn.execute(text("ALTER TABLE zengin_exports ADD COLUMN submitted_at DATETIME"))
            if "downloaded_at" in export_cols:
                conn.execute(
                    text(
                        "UPDATE zengin_exports SET submitted_at = downloaded_at "
                        "WHERE submitted_at IS NULL"
                    )
                )
        if export_cols:
            conn.execute(
                text(
                    "UPDATE zengin_exports SET status = 'submitted' "
                    "WHERE status = 'downloaded'"
                )
            )
            conn.execute(
                text(
                    "UPDATE zengin_exports SET status = 'superseded' "
                    "WHERE status = 'reissued'"
                )
            )


def _migrate_family_bootstrap() -> None:
    """One-time bootstrap: create family records from legacy data."""
    try:
        from models import Family
        from family_support import bootstrap_family_data

        with Session(_db().engine) as session:
            if session.exec(select(Family.id).limit(1)).first() is not None:
                return
            bootstrap_family_data(session)
            session.commit()
    except Exception as exc:
        _db()._log_migration_skip("family bootstrap", exc)


def _migrate_sync_health_records_from_legacy() -> None:
    """One-time sync: migrate legacy extra_data to health records."""
    try:
        from child_health_service import sync_health_records_from_legacy_extra_data
        from models import Child

        with Session(_db().engine) as session:
            children = session.exec(select(Child)).all()
            for child in children:
                sync_health_records_from_legacy_extra_data(session, child)
            session.commit()
    except Exception as exc:
        _db()._log_migration_skip("sync health records from legacy", exc)


def _migrate_extended_care_billing_transfer() -> None:
    with _db().engine.begin() as conn:
        charge_cols = _db()._table_columns("extended_care_charges")
        line_cols = _db()._table_columns("billing_charge_lines")

        if charge_cols:
            additions = {
                "billing_charge_line_id": (
                    "INTEGER REFERENCES billing_charge_lines(id)"
                ),
                "transferred_amount": "INTEGER",
                "transferred_at": "DATETIME",
                "transferred_by_user_id": "CHAR(32) REFERENCES users(id)",
                "transferred_by_name": "VARCHAR(100)",
            }
            for column_name, column_sql in additions.items():
                if column_name not in charge_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE extended_care_charges "
                            f"ADD COLUMN {column_name} {column_sql}"
                        )
                    )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_extended_care_charges_billing_charge_line_id "
                    "ON extended_care_charges (billing_charge_line_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_extended_care_charges_transferred_by_user_id "
                    "ON extended_care_charges (transferred_by_user_id)"
                )
            )

        if line_cols and "source_reference" not in line_cols:
            conn.execute(
                text(
                    "ALTER TABLE billing_charge_lines "
                    "ADD COLUMN source_reference VARCHAR(120)"
                )
            )
        if line_cols:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ux_billing_charge_lines_source_reference "
                    "ON billing_charge_lines (source_reference) "
                    "WHERE source_reference IS NOT NULL"
                )
            )


def _migrate_care_certification_and_extended_care_columns() -> None:
    with _db().engine.begin() as conn:
        rule_cols = _db()._table_columns("extended_care_fee_rules")
        charge_cols = _db()._table_columns("extended_care_charges")

        rule_additions = {
            "care_time_category": "VARCHAR(32)",
            "normal_start_time": "VARCHAR",
            "normal_end_time": "VARCHAR",
            "morning_enabled": "BOOLEAN DEFAULT 0 NOT NULL",
            "morning_grace_minutes": "INTEGER DEFAULT 0 NOT NULL",
            "morning_rounding_minutes": "INTEGER DEFAULT 15 NOT NULL",
            "morning_unit_price": "INTEGER DEFAULT 0 NOT NULL",
            "evening_enabled": "BOOLEAN DEFAULT 1 NOT NULL",
            "evening_grace_minutes": "INTEGER",
            "evening_rounding_minutes": "INTEGER",
            "evening_unit_price": "INTEGER",
        }
        for column_name, column_sql in rule_additions.items():
            if rule_cols and column_name not in rule_cols:
                conn.execute(text(f"ALTER TABLE extended_care_fee_rules ADD COLUMN {column_name} {column_sql}"))

        charge_additions = {
            "certification_id": "INTEGER REFERENCES child_care_certifications(id)",
            "care_time_category_snapshot": "VARCHAR(32)",
            "calculation_version": "VARCHAR(32) DEFAULT 'legacy_v1' NOT NULL",
            "actual_check_in_at": "DATETIME",
            "normal_start_at": "DATETIME",
            "normal_end_at": "DATETIME",
            "morning_extended_minutes": "INTEGER DEFAULT 0 NOT NULL",
            "morning_billable_units": "INTEGER DEFAULT 0 NOT NULL",
            "morning_amount": "INTEGER DEFAULT 0 NOT NULL",
            "evening_extended_minutes": "INTEGER DEFAULT 0 NOT NULL",
            "evening_billable_units": "INTEGER DEFAULT 0 NOT NULL",
            "evening_amount": "INTEGER DEFAULT 0 NOT NULL",
        }
        for column_name, column_sql in charge_additions.items():
            if charge_cols and column_name not in charge_cols:
                conn.execute(text(f"ALTER TABLE extended_care_charges ADD COLUMN {column_name} {column_sql}"))

        if rule_cols:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_extended_care_fee_rules_care_time_category "
                    "ON extended_care_fee_rules (care_time_category)"
                )
            )
        if charge_cols:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_extended_care_charges_certification_id "
                    "ON extended_care_charges (certification_id)"
                )
            )
    with _db().engine.begin() as conn:
        charge_cols = _db()._table_columns("extended_care_charges")
        line_cols = _db()._table_columns("billing_charge_lines")

        if charge_cols:
            additions = {
                "billing_charge_line_id": (
                    "INTEGER REFERENCES billing_charge_lines(id)"
                ),
                "transferred_amount": "INTEGER",
                "transferred_at": "DATETIME",
                "transferred_by_user_id": "CHAR(32) REFERENCES users(id)",
                "transferred_by_name": "VARCHAR(100)",
            }
            for column_name, column_sql in additions.items():
                if column_name not in charge_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE extended_care_charges "
                            f"ADD COLUMN {column_name} {column_sql}"
                        )
                    )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_extended_care_charges_billing_charge_line_id "
                    "ON extended_care_charges (billing_charge_line_id)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS "
                    "ix_extended_care_charges_transferred_by_user_id "
                    "ON extended_care_charges (transferred_by_user_id)"
                )
            )

        if line_cols and "source_reference" not in line_cols:
            conn.execute(
                text(
                    "ALTER TABLE billing_charge_lines "
                    "ADD COLUMN source_reference VARCHAR(120)"
                )
            )
        if line_cols:
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ux_billing_charge_lines_source_reference "
                    "ON billing_charge_lines (source_reference) "
                    "WHERE source_reference IS NOT NULL"
                )
            )
    with _db().engine.begin() as conn:
        rule_cols = _db()._table_columns("extended_care_fee_rules")
        charge_cols = _db()._table_columns("extended_care_charges")

        rule_additions = {
            "care_time_category": "VARCHAR(32)",
            "normal_start_time": "VARCHAR",
            "normal_end_time": "VARCHAR",
            "morning_enabled": "BOOLEAN DEFAULT 0 NOT NULL",
            "morning_grace_minutes": "INTEGER DEFAULT 0 NOT NULL",
            "morning_rounding_minutes": "INTEGER DEFAULT 15 NOT NULL",
            "morning_unit_price": "INTEGER DEFAULT 0 NOT NULL",
            "evening_enabled": "BOOLEAN DEFAULT 1 NOT NULL",
            "evening_grace_minutes": "INTEGER",
            "evening_rounding_minutes": "INTEGER",
            "evening_unit_price": "INTEGER",
        }
        for column_name, column_sql in rule_additions.items():
            if rule_cols and column_name not in rule_cols:
                conn.execute(text(f"ALTER TABLE extended_care_fee_rules ADD COLUMN {column_name} {column_sql}"))

        charge_additions = {
            "certification_id": "INTEGER REFERENCES child_care_certifications(id)",
            "care_time_category_snapshot": "VARCHAR(32)",
            "calculation_version": "VARCHAR(32) DEFAULT 'legacy_v1' NOT NULL",
            "actual_check_in_at": "DATETIME",
            "normal_start_at": "DATETIME",
            "normal_end_at": "DATETIME",
            "morning_extended_minutes": "INTEGER DEFAULT 0 NOT NULL",
            "morning_billable_units": "INTEGER DEFAULT 0 NOT NULL",
            "morning_amount": "INTEGER DEFAULT 0 NOT NULL",
            "evening_extended_minutes": "INTEGER DEFAULT 0 NOT NULL",
            "evening_billable_units": "INTEGER DEFAULT 0 NOT NULL",
            "evening_amount": "INTEGER DEFAULT 0 NOT NULL",
        }
        for column_name, column_sql in charge_additions.items():
            if charge_cols and column_name not in charge_cols:
                conn.execute(text(f"ALTER TABLE extended_care_charges ADD COLUMN {column_name} {column_sql}"))

        if rule_cols:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_extended_care_fee_rules_care_time_category "
                    "ON extended_care_fee_rules (care_time_category)"
                )
            )
        if charge_cols:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_extended_care_charges_certification_id "
                    "ON extended_care_charges (certification_id)"
                )
            )


def _migrate_shift_schedule_tables() -> None:
    """Add columns needed by the shift schedule feature to existing tables."""
    try:
        with _db().engine.connect() as conn:
            # attendance_records: 登園予定時刻（シフト生成用の上書き列）
            att_cols = _db()._table_columns("attendance_records")
            if att_cols and "planned_check_in_time" not in att_cols:
                conn.execute(
                    text(
                        "ALTER TABLE attendance_records "
                        "ADD COLUMN planned_check_in_time VARCHAR(5)"
                    )
                )
            # users: シフト管理権限フラグ
            user_cols = _db()._table_columns("users")
            if user_cols and "can_manage_shifts" not in user_cols:
                conn.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN can_manage_shifts BOOLEAN DEFAULT 0 NOT NULL"
                    )
                )
            # shift_plan_cells: is_pinned フラグの追加と既存データの移行
            cell_cols = _db()._table_columns("shift_plan_cells")
            if cell_cols and "is_pinned" not in cell_cols:
                conn.execute(
                    text(
                        "ALTER TABLE shift_plan_cells "
                        "ADD COLUMN is_pinned BOOLEAN DEFAULT 0 NOT NULL"
                    )
                )
                # U1推奨案: 既存の cell_state='pinned' は is_pinned=1 かつ cell_state='WORK' に移行
                conn.execute(
                    text(
                        "UPDATE shift_plan_cells "
                        "SET is_pinned = 1, cell_state = 'WORK' "
                        "WHERE cell_state = 'pinned'"
                    )
                )
            # staff_contracts: 36協定・変形労働制フラグ
            contract_cols = _db()._table_columns("staff_contracts")
            if contract_cols:
                if "has_36_agreement" not in contract_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE staff_contracts "
                            "ADD COLUMN has_36_agreement BOOLEAN DEFAULT 1 NOT NULL"
                        )
                    )
                if "variable_working_hours" not in contract_cols:
                    conn.execute(
                        text(
                            "ALTER TABLE staff_contracts "
                            "ADD COLUMN variable_working_hours BOOLEAN DEFAULT 0 NOT NULL"
                        )
                    )
            # staff_shift_unavailability: status 列
            unavail_cols = _db()._table_columns("staff_shift_unavailability")
            if unavail_cols and "status" not in unavail_cols:
                conn.execute(
                    text(
                        "ALTER TABLE staff_shift_unavailability "
                        "ADD COLUMN status VARCHAR(16) DEFAULT 'approved' NOT NULL"
                    )
                )
            # shift_solve_jobs: priority 列
            job_cols = _db()._table_columns("shift_solve_jobs")
            if job_cols and "priority" not in job_cols:
                conn.execute(
                    text(
                        "ALTER TABLE shift_solve_jobs "
                        "ADD COLUMN priority INTEGER DEFAULT 2 NOT NULL"
                    )
                )
            conn.commit()
    except Exception as exc:
        _db()._log_migration_skip("shift schedule tables", exc)


def _migrate_shift_timefold_enhancements() -> None:
    """Add priority column to shift_solve_jobs and ensure timefold tables exist."""
    try:
        from shift_schedule.db_models import (
            ShiftFacilityConstraintWeights,
            ShiftPlanProposals,
            ShiftSuggestionActions,
        )
        with _db().engine.begin() as conn:
            job_cols = _db()._table_columns("shift_solve_jobs")
            if job_cols and "priority" not in job_cols:
                conn.execute(
                    text(
                        "ALTER TABLE shift_solve_jobs "
                        "ADD COLUMN priority INTEGER DEFAULT 2 NOT NULL"
                    )
                )
            ShiftFacilityConstraintWeights.metadata.create_all(
                conn, tables=[
                    ShiftFacilityConstraintWeights.__table__,
                    ShiftPlanProposals.__table__,
                    ShiftSuggestionActions.__table__,
                ]
            )
    except Exception as exc:
        _db()._log_migration_skip("shift timefold enhancements", exc)


def _migrate_document_export_permissions() -> None:
    """Add document export permission columns to users table."""
    try:
        user_cols = _db()._table_columns("users")
        if user_cols and "can_export_documents" not in user_cols:
            conn = _db().engine.connect()
            try:
                conn.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN can_export_documents BOOLEAN DEFAULT 0 NOT NULL"
                    )
                )
                conn.execute(
                    text(
                        "ALTER TABLE users "
                        "ADD COLUMN can_export_zengin BOOLEAN DEFAULT 0 NOT NULL"
                    )
                )
                conn.commit()
            finally:
                conn.close()
    except Exception as exc:
        _db()._log_migration_skip("document export permissions", exc)


def _migrate_document_export_history() -> None:
    """Create document_export_logs table for export history management."""
    try:
        with _db().engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS document_export_logs ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "export_type VARCHAR NOT NULL, "
                    "export_format VARCHAR NOT NULL, "
                    "target_month VARCHAR, "
                    "exported_by_user_id UUID, "
                    "exported_by_name VARCHAR, "
                    "record_count INTEGER, "
                    "file_size_bytes INTEGER, "
                    "status VARCHAR DEFAULT 'success', "
                    "error_message VARCHAR, "
                    "created_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_document_export_logs_export_type "
                    "ON document_export_logs(export_type)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_document_export_logs_export_format "
                    "ON document_export_logs(export_format)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_document_export_logs_target_month "
                    "ON document_export_logs(target_month)"
                )
            )
    except Exception as exc:
        _db()._log_migration_skip("document export history", exc)


def _migrate_pims_attendance_tables() -> None:
    """Create punch_children and punch_logs tables for PIMS attendance system."""
    try:
        from models.pims import PunchChild, PunchLog
        with _db().engine.begin() as conn:
            PunchChild.metadata.create_all(
                conn, tables=[PunchChild.__table__, PunchLog.__table__]
            )
    except Exception as exc:
        _db()._log_migration_skip("pims attendance tables", exc)


def _migrate_parent_medical_table() -> None:
    """Create parent_medical_responses table."""
    try:
        from models import ParentMedicalResponse
        with _db().engine.begin() as conn:
            ParentMedicalResponse.metadata.create_all(
                conn, tables=[ParentMedicalResponse.__table__]
            )
    except Exception as exc:
        _db()._log_migration_skip("parent medical responses table", exc)


def _migrate_daily_contact_review_columns() -> None:
    """連絡帳ダブルチェック承認フロー用カラムを追加する。"""
    try:
        additions = {
            "pending_draft": "JSON",
            "reviewed_by_staff_id": "CHAR(32)",
            "reviewed_by_name": "VARCHAR",
            "rejection_reason": "VARCHAR",
            "reviewed_at": "DATETIME",
        }
        with _db().engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(daily_contact_replies)")}
            if columns:
                for name, kind in additions.items():
                    if name not in columns:
                        conn.exec_driver_sql(f"ALTER TABLE daily_contact_replies ADD COLUMN {name} {kind}")
    except Exception as exc:
        _db()._log_migration_skip("daily contact review columns", exc)


def _migrate_smart_hud_simple_mode_and_nap_checks() -> None:
    """スマートHUD・かんたんモード設定列および午睡チェックテーブルを作成する。"""
    try:
        from models import NapCheckRecord, NapClassroomEnvironment

        additions = {
            "attendance_smart_hud_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "staff_simple_mode_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "simple_mode_custom_tiles": "VARCHAR",
            "nap_check_smart_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "nap_check_interval_minutes": "INTEGER NOT NULL DEFAULT 5",
            "board_qr_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "board_qr_version": "INTEGER NOT NULL DEFAULT 1",
        }
        with _db().engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(facility_settings)")}
            if columns:
                for name, ddl in additions.items():
                    if name not in columns:
                        conn.exec_driver_sql(f"ALTER TABLE facility_settings ADD COLUMN {name} {ddl}")
            NapCheckRecord.metadata.create_all(
                conn,
                tables=[NapCheckRecord.__table__, NapClassroomEnvironment.__table__],
            )
    except Exception as exc:
        _db()._log_migration_skip("smart hud / simple mode / nap checks", exc)


def _migrate_facility_settings_board_qr() -> None:
    """048 実行済みDB向けに board_qr_enabled / board_qr_version 列を冪等に追加する。"""
    try:
        additions = {
            "board_qr_enabled": "BOOLEAN NOT NULL DEFAULT 1",
            "board_qr_version": "INTEGER NOT NULL DEFAULT 1",
        }
        with _db().engine.begin() as conn:
            columns = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(facility_settings)")}
            if columns:
                for name, ddl in additions.items():
                    if name not in columns:
                        conn.exec_driver_sql(f"ALTER TABLE facility_settings ADD COLUMN {name} {ddl}")
    except Exception as exc:
        _db()._log_migration_skip("facility_settings board_qr", exc)
