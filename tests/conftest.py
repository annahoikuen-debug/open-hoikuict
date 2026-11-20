"""Global test configuration and fixtures."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
import pytest

# pytest-xdist のワーカーごとに独立した SQLite DB ファイルを割り当て
_worker_id = os.getenv("PYTEST_XDIST_WORKER", "master")
_test_db_dir = Path(tempfile.gettempdir()) / "hoikuict_pytest"
_test_db_dir.mkdir(parents=True, exist_ok=True)
_test_db_path = _test_db_dir / f"hoikuict_test_{_worker_id}.db"

# 既存の環境変数がなければ設定（テストプロセス全体で有効）
if "HOIKUICT_DATABASE_URL" not in os.environ:
    os.environ["HOIKUICT_DATABASE_URL"] = f"sqlite:///{_test_db_path.as_posix()}"

from cache_service import invalidate_all_caches


def pytest_sessionstart(session):
    """各テストワーカーの起動時に DB スキーマを自動初期化"""
    del session
    from database import create_db_and_tables
    create_db_and_tables()


@pytest.fixture(autouse=True)
def clear_caches_between_tests():
    invalidate_all_caches()
    yield
    invalidate_all_caches()


def pytest_sessionfinish(session, exitstatus):
    """テストセッション終了時に一時 DB ファイルをクリーンアップ"""
    del session, exitstatus
    try:
        from database import engine
        engine.dispose()
    except Exception:
        pass

    for ext in ("", "-wal", "-shm"):
        p = Path(str(_test_db_path) + ext)
        if p.exists():
            try:
                p.unlink()
            except Exception:
                pass
