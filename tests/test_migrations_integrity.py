"""マイグレーション定義の整合性と全SQLModelカラム存在を検証するテスト (Phase 1 #9)。"""
from __future__ import annotations

import os
import re

os.environ.setdefault("HOIKUICT_ENV", "development")

from sqlalchemy import inspect
from sqlmodel import SQLModel

import database
import models  # noqa: F401 - 全モデルを SQLModel.metadata に登録
from db_migrations.sqlite_legacy import _sqlite_migrations


def test_sqlite_migration_ids_are_unique_and_ordered() -> None:
    migrations = _sqlite_migrations()
    ids = [m_id for m_id, _ in migrations]
    assert len(ids) == len(set(ids)), f"重複するマイグレーションIDが存在します: {ids}"

    prefixes = []
    for m_id in ids:
        m = re.match(r"^(\d+)_", m_id)
        assert m, f"マイグレーションIDは 'NNN_name' 形式である必要があります: {m_id}"
        prefixes.append(int(m.group(1)))
    assert prefixes == sorted(prefixes), "マイグレーション番号は昇順である必要があります"


def test_all_model_columns_exist_after_init() -> None:
    database.create_db_and_tables()
    inspector = inspect(database.engine)
    existing_tables = set(inspector.get_table_names())

    missing_columns: list[str] = []
    for table_name, table in SQLModel.metadata.tables.items():
        if table_name not in existing_tables:
            missing_columns.append(f"{table_name} (テーブル自体が未作成)")
            continue
        actual_cols = {c["name"] for c in inspector.get_columns(table_name)}
        for col in table.columns:
            if col.name not in actual_cols:
                missing_columns.append(f"{table_name}.{col.name}")

    assert not missing_columns, f"DBに不足しているカラムがあります: {missing_columns}"


def test_sqlite_foreign_keys_clean() -> None:
    with database.engine.connect() as conn:
        violations = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    assert not violations, f"SQLite外部キー違反を検出: {violations[:5]}"
