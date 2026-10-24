"""児童健康情報・アレルギー閲覧/出力の監査ログ記録テスト。

- 職員がカルテを開いた際に、該当職員IDと児童IDが紐づいた監査ログが1行記録されること
- 権限エラー（403）で閲覧拒否された場合も action="VIEW_DENIED" が記録されること
"""

from __future__ import annotations

import json
import os
import tempfile

from audit_logger import AuditEvent, AuditLogger, record_audit_event


def test_health_summary_view_audit_event() -> None:
    """職員が児童健康カルテを開いた際に監査ログが記録されること。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "audit.jsonl")
        logger = AuditLogger(name="hoikuict.audit.test.health_view", log_file=log_path)

        try:
            # 健康カルテ閲覧イベントを記録
            event = logger.record(
                actor_user_id="staff-123",
                actor_role="staff",
                target_resource="child_health",
                resource_id="child-456",
                action="VIEW",
                ip_address="192.168.1.10",
                detail={"child_id": 456, "viewed_section": "summary"},
            )

            # ログファイルを読み込む
            with open(log_path, encoding="utf-8") as f:
                line = f.readline()
            record = json.loads(line)

            assert isinstance(event, AuditEvent)
            assert event.action == "VIEW"
            assert event.target_resource == "child_health"
            assert event.resource_id == "child-456"
            assert event.actor_user_id == "staff-123"
            assert event.actor_role == "staff"
            assert event.detail["child_id"] == 456
            assert record["action"] == "VIEW"
            assert record["target_resource"] == "child_health"
        finally:
            for handler in logger._logger.handlers:
                handler.close()
            logger._logger.handlers.clear()


def test_health_view_denied_audit_event() -> None:
    """権限エラー（403）で閲覧拒否された場合も action="VIEW_DENIED" が記録されること。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "audit.jsonl")
        logger = AuditLogger(name="hoikuict.audit.test.health_denied", log_file=log_path)

        try:
            # 閲覧拒否イベントを記録
            event = logger.record(
                actor_user_id="staff-123",
                actor_role="staff",
                target_resource="child_health",
                resource_id="child-999",
                action="VIEW_DENIED",
                ip_address="192.168.1.10",
                detail={"reason": "insufficient_permission", "child_id": 999},
            )

            with open(log_path, encoding="utf-8") as f:
                line = f.readline()
            record = json.loads(line)

            assert event.action == "VIEW_DENIED"
            assert record["action"] == "VIEW_DENIED"
            assert record["target_resource"] == "child_health"
            assert record["resource_id"] == "child-999"
            assert record["detail"]["reason"] == "insufficient_permission"
        finally:
            for handler in logger._logger.handlers:
                handler.close()
            logger._logger.handlers.clear()


def test_record_audit_event_module_level_for_child_health() -> None:
    """モジュールレベル関数 record_audit_event() が child_health イベントを記録できること。"""
    event = record_audit_event(
        actor_user_id="staff-456",
        actor_role="staff",
        target_resource="child_health",
        resource_id="child-789",
        action="VIEW",
        ip_address="10.0.0.5",
        detail={"child_id": 789},
    )

    assert isinstance(event, AuditEvent)
    assert event.action == "VIEW"
    assert event.target_resource == "child_health"
    assert event.resource_id == "child-789"
    assert event.actor_user_id == "staff-456"


def test_allergy_view_audit_event() -> None:
    """アレルギー情報閲覧も監査ログに記録されること。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "audit.jsonl")
        logger = AuditLogger(name="hoikuict.audit.test.allergy_view", log_file=log_path)

        try:
            event = logger.record(
                actor_user_id="staff-123",
                actor_role="staff",
                target_resource="child_health",
                resource_id="child-456",
                action="VIEW",
                ip_address="192.168.1.10",
                detail={"child_id": 456, "section": "allergies"},
            )

            with open(log_path, encoding="utf-8") as f:
                line = f.readline()
            record = json.loads(line)

            assert event.action == "VIEW"
            assert event.detail["section"] == "allergies"
            assert record["detail"]["section"] == "allergies"
        finally:
            for handler in logger._logger.handlers:
                handler.close()
            logger._logger.handlers.clear()
