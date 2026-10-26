"""実際のSQLModel.metadataからbackup contract JSONのmainセクションを再生成する。"""
from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import SQLModel

import models  # noqa: F401 -- register all tables
import child_records.models  # noqa: F401
import plan_docs.db_models  # noqa: F401
import shift_schedule.db_models  # noqa: F401

contract_path = Path("scripts/backup_contracts/monthly-library-20260927.json")
contract = json.loads(contract_path.read_text(encoding="utf-8"))

actual_main = {
    name: sorted(table.columns.keys()) for name, table in SQLModel.metadata.tables.items()
}
contract["main"] = actual_main

contract_path.write_text(
    json.dumps(contract, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
print(f"regenerated {contract_path} with {len(actual_main)} tables")
