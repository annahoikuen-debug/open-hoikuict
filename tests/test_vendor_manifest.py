"""VENDOR.json マニフェストの整合性検証。

マニフェストに記録されたハッシュが vendor 実ファイルと一致すること、
マニフェストにない .py が vendor に存在しないことを検査する（改善案9）。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_FILE = ROOT / "vendor" / "nushift" / "VENDOR.json"
DEST_SHIFTAI = ROOT / "vendor" / "nushift" / "shiftai"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_manifest_exists_and_wellformed():
    assert MANIFEST_FILE.is_file(), "VENDOR.json missing"
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    assert manifest["source_commit"], "source_commit required"
    assert manifest["files"], "files map required"


def test_manifest_hashes_match_vendor_files():
    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    recorded = dict(manifest["files"])
    actual = {
        str(p.relative_to(DEST_SHIFTAI).as_posix()): _sha256(p)
        for p in DEST_SHIFTAI.rglob("*.py")
        if "__pycache__" not in p.parts
    }
    assert set(recorded) == set(actual), (
        f"manifest/file mismatch: only_in_manifest={sorted(set(recorded) - set(actual))}, "
        f"only_in_vendor={sorted(set(actual) - set(recorded))}"
    )
    for rel, expected_hash in recorded.items():
        assert actual[rel] == expected_hash, f"hash mismatch: {rel}"


def test_manifest_commit_matches_provenance_readme():
    import re

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    readme = (MANIFEST_FILE.parent / "README.md").read_text(encoding="utf-8")
    match = re.search(r"\| 基準コミット \| `([a-f0-9]+)`", readme)
    assert match, "provenance commit line missing in README"
    assert manifest["source_commit"] == match.group(1)
