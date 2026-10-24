"""児童観察記録・要録エクスポートの監査ログ記録テスト。

- 職員が児童観察記録をエクスポートした際に、action="EXPORT" が記録されること
- 詳細（detail）に child_count と filename が含まれること
- モジュールレベル関数 record_audit_event() が child_records エクスポートイベントを記録できること
"""

from __future__ import annotations

import json
import os
import tempfile

from audit_logger import AuditEvent, AuditLogger, record_audit_event


def test_child_records_export_audit_event() -> None:
    """職員が児童観察記録をエクスポートした際に監査ログが記録されること。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "audit.jsonl")
        logger = AuditLogger(name="hoikuict.audit.test.child_records_export", log_file=log_path)

        try:
            event = logger.record(
                actor_user_id="staff-123",
                actor_role="staff",
                target_resource="child_records",
                resource_id="child-456",
                action="EXPORT",
                ip_address="192.168.1.10",
                detail={
                    "child_id": 456,
                    "format": "csv",
                    "filename": "児童A_observation_2026-10-24.csv",
                    "child_count": 42,
                    "section": "export_child_records",
                },
            )

            with open(log_path, encoding="utf-8") as f:
                line = f.readline()
            record = json.loads(line)

            assert isinstance(event, AuditEvent)
            assert event.action == "EXPORT"
            assert event.target_resource == "child_records"
            assert event.resource_id == "child-456"
            assert event.actor_user_id == "staff-123"
            assert event.actor_role == "staff"
            assert event.detail["child_count"] == 42
            assert event.detail["filename"] == "児童A_observation_2026-10-24.csv"
            assert record["action"] == "EXPORT"
            assert record["target_resource"] == "child_records"
            assert record["detail"]["child_count"] == 42
            assert record["detail"]["filename"] == "児童A_observation_2026-10-24.csv"
        finally:
            for handler in logger._logger.handlers:
                handler.close()
            logger._logger.handlers.clear()


def test_record_audit_event_module_level_for_child_records_export() -> None:
    """モジュールレベル関数 record_audit_event() が child_records エクスポートイベントを記録できること。"""
    event = record_audit_event(
        actor_user_id="staff-456",
        actor_role="staff",
        target_resource="child_records",
        resource_id="child-789",
        action="EXPORT",
        ip_address="10.0.0.5",
        detail={
            "child_id": 789,
            "format": "pdf",
            "filename": "児童B_progress_2026-10-24.pdf",
            "child_count": 15,
            "section": "export_child_records",
        },
    )

    assert isinstance(event, AuditEvent)
    assert event.action == "EXPORT"
    assert event.target_resource == "child_records"
    assert event.resource_id == "child-789"
    assert event.actor_user_id == "staff-456"
    assert event.detail["child_count"] == 15
    assert event.detail["filename"] == "児童B_progress_2026-10-24.pdf"
