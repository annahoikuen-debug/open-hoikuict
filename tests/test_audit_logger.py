"""audit_logger.py のリグレッション防止テスト。

- record_audit_event() 呼び出しで正しいJSON形式でイベントが出力されること
- 個人情報の生平文（パスワードや銀行口座番号全体）がマスクされていること
- JSON Lines 形式（1行1オブジェクト）であること
"""

from __future__ import annotations

import json
import logging
import os
import tempfile

from audit_logger import (
    AuditEvent,
    AuditLogger,
    _mask_detail,
    _mask_value,
    audit_logger,
    record_audit_event,
)


def _create_test_logger(tmpdir: str, name: str) -> tuple[AuditLogger, str]:
    """テスト用の監査ロガーとログファイルパスを作成する。

    ロガーのハンドラを呼び出し元でクローズ可能にするため、
    タプルで返す。
    """
    log_path = os.path.join(tmpdir, "audit.jsonl")
    logger = AuditLogger(name=name, log_file=log_path)
    return logger, log_path


def _read_log_lines(log_path: str) -> list[dict]:
    """ログファイルからJSON Linesを読み込む。"""
    with open(log_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _close_logger(logger: AuditLogger) -> None:
    """ロガーのハンドラをクローズしてファイルハンドルを解放する。"""
    for handler in logger._logger.handlers:
        handler.close()
    logger._logger.handlers.clear()


def test_record_audit_event_outputs_valid_json() -> None:
    """record_audit_event() が正しいJSON形式でイベントを出力すること。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger, log_path = _create_test_logger(tmpdir, "hoikuict.audit.test1")

        try:
            event = logger.record(
                actor_user_id="user-123",
                actor_role="staff",
                target_resource="child_health",
                resource_id="child-456",
                action="VIEW",
                ip_address="192.168.1.10",
                detail={"child_name": "田中太郎", "viewed_field": "allergy"},
            )

            records = _read_log_lines(log_path)

            assert len(records) == 1
            record = records[0]

            assert record["actor_user_id"] == "user-123"
            assert record["actor_role"] == "staff"
            assert record["target_resource"] == "child_health"
            assert record["resource_id"] == "child-456"
            assert record["action"] == "VIEW"
            assert record["ip_address"] == "192.168.1.10"
            assert "timestamp" in record
            assert record["detail"]["child_name"] == "田中太郎"
            assert record["detail"]["viewed_field"] == "allergy"
            assert event.actor_user_id == "user-123"
        finally:
            _close_logger(logger)


def test_record_audit_event_returns_audit_event() -> None:
    """record_audit_event() が AuditEvent インスタンスを返すこと。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger, log_path = _create_test_logger(tmpdir, "hoikuict.audit.test2")

        try:
            result = logger.record(
                actor_user_id="user-123",
                actor_role="staff",
                target_resource="child_health",
                resource_id="child-456",
                action="VIEW",
            )

            assert isinstance(result, AuditEvent)
            assert result.actor_user_id == "user-123"
            assert result.action == "VIEW"
        finally:
            _close_logger(logger)


def test_password_is_masked() -> None:
    """フィールド名ベースでパスワード値がマスクされること。"""
    masked = _mask_detail({"password": "super-secret-password-12345"})
    assert masked["password"] == "s**************************"

    # 短いパスワードは全マスク
    masked_short = _mask_detail({"pass": "abcd"})
    assert masked_short["pass"] == "****"


def test_bank_account_number_is_masked() -> None:
    """フィールド名ベースで銀行口座番号がマスクされること。"""
    masked = _mask_detail({"bank_account": "123456789012345"})
    assert masked["bank_account"] == "1**************"

    # 日本語の口座番号フィールド名もマスク対象
    masked_jp = _mask_detail({"口座番号": "123456789012345"})
    assert masked_jp["口座番号"] == "1**************"


def test_mask_value_pattern_only() -> None:
    """_mask_value はフィールド名ではなく値のパターンのみでマスクすること。"""
    # 値がクレジットカードパターンにマッチする場合はマスクされる
    masked = _mask_value("1234 5678 9012 3456")
    assert masked == "****-****-****-****"

    # 値が電話番号パターンにマッチする場合はマスクされる
    masked_phone = _mask_value("090-1234-5678")
    assert masked_phone == "***-****-****"

    # 値そのものがPIIフィールド名を含む文字列でも、フィールド名ベースマスクは行われない
    # （フィールド名ベースマスクは _mask_detail の責務）
    masked_plain = _mask_value("password123")
    assert masked_plain == "password123"


def test_credit_card_pattern_is_masked() -> None:
    """クレジットカード番号パターンが部分マスクされること。"""
    masked = _mask_value({"card_number": "1234 5678 9012 3456"})
    assert masked["card_number"] == "****-****-****-****"


def test_phone_number_pattern_is_masked() -> None:
    """電話番号パターンが部分マスクされること。"""
    masked = _mask_value({"phone": "090-1234-5678"})
    assert masked["phone"] == "***-****-****"


def test_non_pii_values_are_preserved() -> None:
    """個人情報でない値はそのまま保持されること。"""
    masked = _mask_value({"child_name": "田中太郎", "age": 5, "allergy": "卵"})
    assert masked["child_name"] == "田中太郎"
    assert masked["age"] == 5
    assert masked["allergy"] == "卵"


def test_detail_is_masked_in_recorded_event() -> None:
    """記録されたイベントのdetail内で個人情報がマスクされること。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger, log_path = _create_test_logger(tmpdir, "hoikuict.audit.test3")

        try:
            logger.record(
                actor_user_id="user-123",
                actor_role="staff",
                target_resource="child_health",
                resource_id="child-456",
                action="UPDATE",
                detail={"password": "secret123", "child_name": "田中"},
            )

            records = _read_log_lines(log_path)

            assert records[0]["detail"]["password"] == "s********"
            assert records[0]["detail"]["child_name"] == "田中"
        finally:
            _close_logger(logger)


def test_json_lines_format_one_event_per_line() -> None:
    """JSON Lines 形式で1行に1イベントが出力されること。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger, log_path = _create_test_logger(tmpdir, "hoikuict.audit.test4")

        try:
            logger.record(
                actor_user_id="user-1",
                actor_role="staff",
                target_resource="child_health",
                resource_id="child-1",
                action="VIEW",
            )
            logger.record(
                actor_user_id="user-2",
                actor_role="staff",
                target_resource="child_records",
                resource_id="child-2",
                action="EXPORT",
            )

            records = _read_log_lines(log_path)

            assert len(records) == 2
            for record in records:
                assert "timestamp" in record
                assert "action" in record
        finally:
            _close_logger(logger)


def test_audit_logger_is_separate_from_application_log() -> None:
    """audit_logger が `hoikuict.audit` という専用ロガー名を使用し、
    アプリケーションログと伝播しないこと。"""
    assert audit_logger._logger.name == "hoikuict.audit"
    assert audit_logger._logger.propagate is False
    assert audit_logger._logger.level == logging.INFO


def test_record_audit_event_module_level() -> None:
    """モジュールレベル関数 record_audit_event() が動作すること。"""
    # デフォルトの audit_logger は stdout に出力するため、
    # 例外が発生しないことのみを確認
    event = record_audit_event(
        actor_user_id="user-123",
        actor_role="staff",
        target_resource="child_health",
        resource_id="child-456",
        action="VIEW",
        ip_address="10.0.0.1",
    )
    assert isinstance(event, AuditEvent)
    assert event.action == "VIEW"


def test_timestamp_is_iso8601_utc() -> None:
    """タイムスタンプがISO 8601 UTC形式であること。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger, log_path = _create_test_logger(tmpdir, "hoikuict.audit.test5")

        try:
            fixed_time = "2024-01-15T10:30:00+00:00"
            event = logger.record(
                actor_user_id="user-1",
                actor_role="staff",
                target_resource="child_health",
                resource_id="child-1",
                action="VIEW",
                timestamp=fixed_time,
            )

            assert event.timestamp == fixed_time

            records = _read_log_lines(log_path)
            assert records[0]["timestamp"] == fixed_time
        finally:
            _close_logger(logger)


def test_all_action_types_recorded() -> None:
    """VIEW / EXPORT / UPDATE / DELETE / VIEW_DENIED などのアクション種別が記録できること。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        logger, log_path = _create_test_logger(tmpdir, "hoikuict.audit.test6")

        try:
            for action in ["VIEW", "EXPORT", "UPDATE", "DELETE", "VIEW_DENIED"]:
                logger.record(
                    actor_user_id="user-1",
                    actor_role="staff",
                    target_resource="child_health",
                    resource_id="child-1",
                    action=action,
                )

            records = _read_log_lines(log_path)

            assert len(records) == 5
            for i, action in enumerate(["VIEW", "EXPORT", "UPDATE", "DELETE", "VIEW_DENIED"]):
                assert records[i]["action"] == action
        finally:
            _close_logger(logger)
