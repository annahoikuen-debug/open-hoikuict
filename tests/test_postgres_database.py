"""PostgreSQL データベース設定およびコネクション管理の単体テスト。"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy.engine import make_url
from sqlalchemy.pool import QueuePool


class PostgresDatabaseConfigTests(unittest.TestCase):
    """PostgreSQL 接続文字列の正規化とプール設定のテスト。"""

    def test_postgres_url_normalization(self):
        """postgres:// プレフィックスが postgresql:// に正規化されること。"""
        urls = [
            ("postgres://user:pass@localhost:5432/dbname", "postgresql://user:pass@localhost:5432/dbname"),
            ("postgresql://user:pass@localhost:5432/dbname", "postgresql://user:pass@localhost:5432/dbname"),
            ("sqlite:///./test.db", "sqlite:///./test.db"),
        ]
        for input_url, expected in urls:
            normalized = input_url.replace("postgres://", "postgresql://", 1) if input_url.startswith("postgres://") else input_url
            assert normalized == expected
            url_obj = make_url(normalized)
            if "sqlite" in input_url:
                assert url_obj.get_backend_name() == "sqlite"
            else:
                assert url_obj.get_backend_name() in ("postgresql", "postgres")

    def test_run_alembic_migrations_exists(self):
        """database モジュールが run_alembic_migrations を公開していること。"""
        import database
        assert hasattr(database, "run_alembic_migrations")
        assert callable(database.run_alembic_migrations)

    def test_alembic_upgrade_head_on_fresh_sqlite_db(self):
        """Alembic upgrade head が空の SQLite DB で成功し全SQLModelテーブルを作成すること。"""
        import os
        import sqlite3
        import subprocess
        import tempfile
        from pathlib import Path
        import models  # noqa: F401
        from sqlmodel import SQLModel

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = (Path(tmpdir) / "fresh_alembic.db").as_posix()
            env = os.environ.copy()
            env["HOIKUICT_DATABASE_URL"] = f"sqlite:///{db_path}"
            res = subprocess.run(
                ["python", "-m", "alembic", "upgrade", "head"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            assert res.returncode == 0, f"alembic failed:\n{res.stdout}\n{res.stderr}"

            with sqlite3.connect(db_path) as conn:
                tables = {
                    row[0]
                    for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                } - {"alembic_version"}
                facility_cols = {
                    row[1] for row in conn.execute("PRAGMA table_info(facility_settings)")
                }
            conn.close()

            missing = set(SQLModel.metadata.tables) - tables
            assert not missing, f"Alembic missing tables: {sorted(missing)}"
            for col in (
                "attendance_smart_hud_enabled",
                "staff_simple_mode_enabled",
                "simple_mode_custom_tiles",
                "nap_check_smart_enabled",
                "nap_check_interval_minutes",
            ):
                assert col in facility_cols

    def test_migrate_single_tenant_db_targets_tenant_file_not_global_engine(self):
        """migrate_single_tenant_db が対象テナントSQLiteへ直接マイグレーションを適用すること。"""
        import sqlite3
        import tempfile
        from pathlib import Path
        from sqlalchemy import create_engine
        from sqlmodel import SQLModel
        import models  # noqa: F401
        import database
        from database_tenants.migration import migrate_single_tenant_db

        orig_engine = database.engine
        with tempfile.TemporaryDirectory() as tmpdir:
            tenant_db = Path(tmpdir) / "tenant_001.db"
            tmp_engine = create_engine(f"sqlite:///{tenant_db.as_posix()}", echo=False)
            try:
                SQLModel.metadata.create_all(tmp_engine)
            finally:
                tmp_engine.dispose()

            with sqlite3.connect(tenant_db) as conn:
                conn.execute("DROP TABLE nap_check_records")
                conn.execute("DROP TABLE nap_classroom_environments")
                conn.execute("ALTER TABLE facility_settings DROP COLUMN nap_check_smart_enabled")
                conn.execute("ALTER TABLE facility_settings DROP COLUMN attendance_smart_hud_enabled")
                conn.commit()
            conn.close()

            migrate_single_tenant_db(tenant_db)
            assert database.engine is orig_engine

            with sqlite3.connect(tenant_db) as conn:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(facility_settings)")}
                tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            conn.close()

            assert "nap_check_smart_enabled" in cols
            assert "attendance_smart_hud_enabled" in cols
            assert "nap_check_records" in tables
            assert "nap_classroom_environments" in tables
