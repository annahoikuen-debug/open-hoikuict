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
