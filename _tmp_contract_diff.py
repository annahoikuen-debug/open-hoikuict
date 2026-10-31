from scripts.backup_validation import load_contract
from sqlmodel import SQLModel

contract, _ = load_contract()
actual = {name: sorted(table.columns.keys()) for name, table in SQLModel.metadata.tables.items()}
expected = contract["main"]

for name in sorted(set(expected) | set(actual)):
    e = set(expected.get(name, []))
    a = set(actual.get(name, []))
    if e != a:
        print(f"{name}: contract_only={sorted(e - a)} actual_only={sorted(a - e)}")
