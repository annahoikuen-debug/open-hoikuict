"""構造化監査ログ基盤。

ISO 27001 / 個人情報保護法ガイドラインに準拢し、誰が・いつ・どのリソースに・何をしたか
を記録する追記型構造化ログモジュールを提供する。

アプリケーションログとは別のロガー（`hoikuict.audit`）を使用し、ログレベルは INFO、
出力は JSON Lines 形式で `logs/audit.jsonl` または標準出力へ追記する。
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# 個人情報マスク対象のフィールド名（大小文字を無視して照合）
_PII_FIELD_NAMES = frozenset(
    {
        "password",
        "pass",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "access_key",
        "secret_key",
        "bank_account",
        "bankaccount",
        "口座番号",
        "カード番号",
        "card_number",
        "credit_card",
        "creditcard",
        "クレジットカード",
    }
)

# 社会保障番号・マイナンバー・電話番号などの数値パターンを部分マスク
_MASK_PATTERNS = [
    (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), "****-****-****-****"),  # クレジットカード形式
    (re.compile(r"\b\d{4}[- ]?\d{2}[- ]?\d{4}[- ]?\d{2}\b"), "****-**-****-**"),  # マイナンバー形式
    (re.compile(r"\b\d{3}[- ]?\d{4}[- ]?\d{4}\b"), "***-****-****"),  # 電話番号形式
]


@dataclass(frozen=True)
class AuditEvent:
    """監査ログイベント。不変なデータ構造として定義する。"""

    actor_user_id: str | int | None
    actor_role: str | None
    target_resource: str
    resource_id: str | int | None
    action: str
    ip_address: str | None
    timestamp: str
    detail: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """辞書形式に変換する（JSONシリアライズ用）。"""
        return asdict(self)


def _is_pii_field_name(key: str) -> bool:
    """辞書のキーが個人情報フィールド名に該当するか判定する。"""
    lowered = key.lower()
    return any(field_name in lowered for field_name in _PII_FIELD_NAMES)


def _mask_value(value: Any) -> Any:
    """個人情報を含む値をマスク化する。

    パスワード、銀行口座番号、クレジットカード番号などの生平文を
    部分的にマスクして出力する。

    注意: フィールド名によるマスクは _mask_detail 側で行うため、
    ここでは値そのもののパターンマスクのみを行う。
    """
    if value is None:
        return None

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value

    if isinstance(value, str):
        # 空文字はそのまま
        if not value:
            return value

        # 数値パターンによる部分マスク（クレジットカード、マイナンバー、電話番号など）
        masked = value
        for pattern, replacement in _MASK_PATTERNS:
            masked = pattern.sub(replacement, masked)
        return masked

    if isinstance(value, dict):
        return {key: _mask_value(val) for key, val in value.items()}

    if isinstance(value, list):
        return [_mask_value(item) for item in value]

    return value


def _mask_detail(detail: dict[str, Any]) -> dict[str, Any]:
    """detail辞書内の個人情報をマスク化する。

    フィールド名が個人情報系（password, bank_account等）の場合は値を
    マスクし、それ以外は値のパターンに基づくマスクを適用する。
    """
    if not isinstance(detail, dict):
        return detail

    result: dict[str, Any] = {}
    for key, val in detail.items():
        if _is_pii_field_name(key):
            # フィールド名がPII系の場合は値をマスク
            if isinstance(val, str):
                if len(val) <= 4:
                    result[key] = "*" * len(val)
                else:
                    result[key] = val[0] + "*" * (len(val) - 1)
            else:
                result[key] = "***"
        else:
            result[key] = _mask_value(val)
    return result


def _now_iso() -> str:
    """現在時刻をISO 8601形式（UTC）で取得する。"""
    return datetime.now(timezone.utc).isoformat()


class AuditLogger:
    """構造化監査ログ出力クラス。

    JSON Lines 形式で1行1イベントをログファイルまたは標準出力へ追記する。
    ロガーは `hoikuict.audit` という専用名を使用し、アプリケーションログと
    完全に分離される。
    """

    def __init__(
        self,
        name: str = "hoikuict.audit",
        log_file: str | None = None,
        level: int = logging.INFO,
    ) -> None:
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level)
        self._logger.propagate = False  # アプリケーションログへの伝播を防ぐ

        # 既存ハンドラをクリアして重複出力を防ぐ
        self._logger.handlers.clear()

        if log_file:
            # ログディレクトリが存在しない場合は作成
            log_dir = os.path.dirname(log_file)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir, exist_ok=True)
            handler: logging.Handler = logging.FileHandler(log_file, encoding="utf-8")
        else:
            handler = logging.StreamHandler()

        handler.setLevel(level)
        formatter = logging.Formatter("%(message)s")
        handler.setFormatter(formatter)
        self._logger.addHandler(handler)

    def record(
        self,
        *,
        actor_user_id: str | int | None,
        actor_role: str | None,
        target_resource: str,
        resource_id: str | int | None,
        action: str,
        ip_address: str | None = None,
        detail: dict[str, Any] | None = None,
        timestamp: str | None = None,
    ) -> AuditEvent:
        """監査イベントを記録する。

        引数で指定されたイベント内容をJSON Lines形式で出力し、不変な
        AuditEventインスタンスを返す。

        Args:
            actor_user_id: アクター（実行者）のユーザーID
            actor_role: アクターのロール
            target_resource: 対象リソース名（例: child_health, child_records）
            resource_id: 対象リソースID
            action: アクション種別（VIEW / EXPORT / UPDATE / DELETE / VIEW_DENIED 等）
            ip_address: クライアントIPアドレス
            detail: 補足情報（個人情報は自動マスクされる）
            timestamp: タイムスタンプ（未指定時は現在時刻）

        Returns:
            記録された AuditEvent インスタンス
        """
        event = AuditEvent(
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            target_resource=target_resource,
            resource_id=resource_id,
            action=action,
            ip_address=ip_address,
            timestamp=timestamp or _now_iso(),
            detail=_mask_detail(detail or {}),
        )
        self._logger.info(json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")))
        return event


# デフォルト監査ログインスタンス。
# 環境変数 HOIKUICT_AUDIT_LOG_FILE が設定されていればファイル出力、そうでなければ標準出力。
_DEFAULT_LOG_FILE = os.getenv("HOIKUICT_AUDIT_LOG_FILE")
audit_logger = AuditLogger(log_file=_DEFAULT_LOG_FILE)


def record_audit_event(
    *,
    actor_user_id: str | int | None,
    actor_role: str | None,
    target_resource: str,
    resource_id: str | int | None,
    action: str,
    ip_address: str | None = None,
    detail: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> AuditEvent:
    """監査イベントを記録するモジュールレベル関数。

    これはデフォルトの `audit_logger` インスタンスへイベントを委譲する。
    テストやDIで差し替え可能にするため、モジュール関数として提供する。

    Returns:
        記録された AuditEvent インスタンス
    """
    return audit_logger.record(
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        target_resource=target_resource,
        resource_id=resource_id,
        action=action,
        ip_address=ip_address,
        detail=detail,
        timestamp=timestamp,
    )
