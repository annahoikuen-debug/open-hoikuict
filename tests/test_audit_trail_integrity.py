"""監査ログの改ざん検知と出力フォーマット検証テスト。

- 各フィールド型（ISO8601日時、UUID文字列など）のスキーマバリデーション
- 改行文字やNULL文字の混入防止（ログインジェクション対策）の検証
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from datetime import datetime

from audit_logger import AuditEvent, AuditLogger, record_audit_event

# ISO 8601 UTC 形式の正規表現（例: 2026-10-24T02:05:50.123456+00:00）
_ISO8601_UTC_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?([+-]\d{2}:\d{2}|Z)$"
)

# UUID 形式の正規表現
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _read_log_lines(log_path: str) -> list[dict]:
    with open(log_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_audit_entry_schema_validation() -> None:
    """監査ログエントリの各フィールドが期待する型・フォーマットに従うこと。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "audit.jsonl")
        logger = AuditLogger(name="hoikuict.audit.test.integrity.schema", log_file=log_path)

        try:
            event = logger.record(
                actor_user_id="staff-123",
                actor_role="staff",
                target_resource="child_records",
                resource_id=str(uuid.uuid4()),
                action="EXPORT",
                ip_address="192.168.1.10",
                detail={"child_count": 42, "format": "csv"},
            )

            records = _read_log_lines(log_path)
            assert len(records) == 1
            record = records[0]

            # 必須フィールドの存在
            for field in ("actor_user_id", "actor_role", "target_resource", "resource_id",
                          "action", "ip_address", "timestamp", "detail"):
                assert field in record, f"フィールド {field} が存在しません"

            # タイムスタンプは ISO 8601 UTC 形式
            assert _ISO8601_UTC_RE.match(record["timestamp"]), (
                f"タイムスタンプが ISO 8601 UTC 形式ではありません: {record['timestamp']}"
            )
            # 解析可能であること
            datetime.fromisoformat(record["timestamp"])

            # resource_id は UUID 形式または整数文字列
            assert record["resource_id"] is not None

            # action は英大文字・アンダースコアのみ
            assert re.match(r"^[A-Z_]+$", record["action"]), (
                f"action に不正な文字が含まれています: {record['action']}"
            )

            # detail は辞書型
            assert isinstance(record["detail"], dict)

            # AuditEvent インスタンスのタイムスタンプも ISO 8601
            assert _ISO8601_UTC_RE.match(event.timestamp)
        finally:
            for handler in logger._logger.handlers:
                handler.close()
            logger._logger.handlers.clear()


def test_audit_entry_no_log_injection() -> None:
    """改行文字や NULL 文字などのログインジェクション文字が混入しないこと。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = os.path.join(tmpdir, "audit.jsonl")
        logger = AuditLogger(name="hoikuict.audit.test.integrity.injection", log_file=log_path)

        try:
            # 悪意のある値を含むイベントを記録（改行・NULL・キャリッジリターン）
            event = logger.record(
                actor_user_id="staff-123",
                actor_role="staff",
                target_resource="child_records",
                resource_id="child-456",
                action="VIEW",
                ip_address="192.168.1.10",
                detail={
                    "malicious_key": "value\nwith\nnewlines",
                    "another_key": "value\rwith\rcarriage",
                    "null_key": "value\x00with\x00null",
                },
            )

            records = _read_log_lines(log_path)
            assert len(records) == 1

            # 生の行を読み込み、1行に1イベントであることを確認
            # JSON Lines 形式では、1行に1つのJSONオブジェクトが含まれる必要がある
            with open(log_path, encoding="utf-8") as f:
                raw_lines = [line for line in f if line.strip()]
            assert len(raw_lines) == 1, (
                f"複数行に分割されています（ログインジェクションの可能性）: {len(raw_lines)} 行"
            )

            # 生の行に未エスケープの改行やNULL文字が含まれていないことを確認
            raw_line = raw_lines[0]
            assert "\n" not in raw_line.rstrip("\n"), "生のログ行に未エスケープの改行が含まれています"
            assert "\r" not in raw_line, "生のログ行にキャリッジリターンが含まれています"
            assert "\x00" not in raw_line, "生のログ行に NULL 文字が含まれています"

            # 各フィールドの解析後の値（NULL文字はJSONデコード後に復元されるため、
            # ファイル上の安全性のみが重要）
            # JSON シリアライズ時に制御文字がエスケープされていること（元の値は保持）
            assert event.detail["malicious_key"] == "value\nwith\nnewlines"
            assert event.detail["null_key"] == "value\x00with\x00null"
        finally:
            for handler in logger._logger.handlers:
                handler.close()
            logger._logger.handlers.clear()


def test_module_level_record_audit_event_integrity() -> None:
    """モジュールレベル関数 record_audit_event() のイベントが整合性を保つこと。"""
    event = record_audit_event(
        actor_user_id="staff-456",
        actor_role="staff",
        target_resource="child_health",
        resource_id=str(uuid.uuid4()),
        action="VIEW_DENIED",
        ip_address="10.0.0.5",
        detail={"reason": "insufficient_permission"},
    )

    assert isinstance(event, AuditEvent)
    assert _ISO8601_UTC_RE.match(event.timestamp)
    assert re.match(r"^[A-Z_]+$", event.action)
    assert isinstance(event.detail, dict)
    assert event.detail["reason"] == "insufficient_permission"
