"""サポート問い合わせ用の匿名化診断パック生成サービス。

園児・保護者・職員の個人情報（PII）や認証シークレットを自動マスクした上で、
システム稼働状態・DBファイル容量・WAL状態・テーブル件数・バージョン情報をZIP化する。
"""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text
from sqlmodel import Session

from time_utils import utc_now
from version import __version__ as APP_VERSION

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"0\d{1,4}-\d{1,4}-\d{3,4}|0\d{9,10}")
_SECRET_KEY_NAMES = ("SECRET", "PASSWORD", "TOKEN", "KEY", "PASS", "DSN", "URL")


def sanitize_diagnostic_text(text_value: str) -> str:
    """ログや設定文字列に含まれるメールアドレス・電話番号をマスクする。"""
    masked = _EMAIL_RE.sub("[REDACTED_EMAIL]", text_value)
    masked = _PHONE_RE.sub("[REDACTED_PHONE]", masked)
    return masked


def _safe_env_summary() -> dict[str, str]:
    summary: dict[str, str] = {}
    for key, val in sorted(os.environ.items()):
        if not key.startswith("HOIKUICT_"):
            continue
        if any(tok in key.upper() for tok in _SECRET_KEY_NAMES):
            summary[key] = "[SET]" if val else "[EMPTY]"
        else:
            summary[key] = sanitize_diagnostic_text(val)
    return summary


def _db_metrics(session: Session) -> dict[str, Any]:
    bind = session.get_bind()
    backend = bind.dialect.name if bind is not None else "unknown"
    metrics: dict[str, Any] = {"backend": backend, "tables": {}}

    try:
        inspector = inspect(bind)
        for table_name in sorted(inspector.get_table_names()):
            try:
                count = session.exec(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar_one()
                metrics["tables"][table_name] = int(count)
            except Exception:
                metrics["tables"][table_name] = -1
    except Exception as exc:
        metrics["table_error"] = str(exc)

    if backend == "sqlite" and bind is not None:
        db_path_str = getattr(bind.url, "database", None)
        if db_path_str and db_path_str != ":memory:":
            db_path = Path(db_path_str)
            for suffix, key in (("", "db_bytes"), ("-wal", "wal_bytes"), ("-shm", "shm_bytes")):
                target = Path(f"{db_path}{suffix}")
                metrics[key] = target.stat().st_size if target.exists() else 0
    return metrics


def build_diagnostics_zip(session: Session) -> bytes:
    """PIIを一切含まない匿名化診断パックZIPバイト列を生成する。"""
    payload = {
        "generated_at_utc": utc_now().isoformat(),
        "app_version": APP_VERSION,
        "env_summary": _safe_env_summary(),
        "database": _db_metrics(session),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "diagnostics_summary.json",
            json.dumps(payload, ensure_ascii=False, indent=2),
        )
        zf.writestr(
            "README.txt",
            "open-hoikuict 匿名化診断パック\n"
            "このアーカイブには園児・保護者・職員の氏名、連絡先、口座情報、認証シークレットは含まれません。\n",
        )
    buf.seek(0)
    return buf.getvalue()
