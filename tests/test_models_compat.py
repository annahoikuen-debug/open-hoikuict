"""models パッケージ分割（改善案7）の互換性スナップショットテスト。

- スナップショット内の全公開名が `models` から import できること
- SQLModel.metadata のテーブル名・列名がスナップショットと完全一致すること

スナップショットは分割前の models.py から生成済み:
  tests/snapshots/models_public_names.txt  (214 names)
  tests/snapshots/metadata_schema.json     (123 tables)
"""
from __future__ import annotations

import json
from pathlib import Path

import models

SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"


def test_public_names_are_preserved():
    snapshot = SNAPSHOT_DIR / "models_public_names.txt"
    names = snapshot.read_text(encoding="utf-8").splitlines()
    assert len(names) > 0, "snapshot is empty"
    missing = [name for name in names if not hasattr(models, name)]
    assert not missing, f"models から失われた公開名: {missing}"


def test_metadata_schema_is_preserved():
    snapshot = SNAPSHOT_DIR / "metadata_schema.json"
    schema = json.loads(snapshot.read_text(encoding="utf-8"))
    # テスト環境では shift_schedule.db_models など関連パッケージのテーブルも
    # 同一 metadata に登録されるため、スナップショット外のテーブルは除外して比較する。
    import shift_schedule.db_models  # noqa: F401
    import child_records.models  # noqa: F401
    import plan_docs.db_models  # noqa: F401

    actual = {
        name: sorted(c.name for c in table.columns)
        for name, table in models.SQLModel.metadata.tables.items()
    }
    expected = {name: sorted(cols) for name, cols in schema.items()}
    missing_tables = set(expected) - set(actual)
    assert not missing_tables, f"失われたテーブル: {sorted(missing_tables)}"
    for name in expected:
        assert actual[name] == expected[name], f"列の不一致: {name}"
