"""Check integrity of vendor/nushift directory against VENDOR.json manifest.

Usage:
    python scripts/check_vendor_integrity.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "vendor" / "nushift"
DEST_SHIFTAI = VENDOR_DIR / "shiftai"
MANIFEST_FILE = VENDOR_DIR / "VENDOR.json"


def compute_file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def main() -> None:
    if not MANIFEST_FILE.is_file():
        print(f"Error: Manifest file {MANIFEST_FILE} not found.", file=sys.stderr)
        sys.exit(1)

    if not DEST_SHIFTAI.is_dir():
        print(f"Error: Vendor directory {DEST_SHIFTAI} not found.", file=sys.stderr)
        sys.exit(1)

    manifest = json.loads(MANIFEST_FILE.read_text(encoding="utf-8"))
    recorded_files: dict[str, str] = manifest.get("files", {})
    source_commit: str = manifest.get("source_commit", "unknown")

    actual_files = {
        str(p.relative_to(DEST_SHIFTAI).as_posix()): compute_file_hash(p)
        for p in sorted(DEST_SHIFTAI.rglob("*.py"))
        if "__pycache__" not in p.parts
    }

    missing_in_vendor = set(recorded_files.keys()) - set(actual_files.keys())
    extra_in_vendor = set(actual_files.keys()) - set(recorded_files.keys())
    mismatched = [
        rel_path
        for rel_path in sorted(set(recorded_files.keys()) & set(actual_files.keys()))
        if recorded_files[rel_path] != actual_files[rel_path]
    ]

    if missing_in_vendor or extra_in_vendor or mismatched:
        print(f"[INTEGRITY FAILED] Discrepancies detected against manifest (commit: {source_commit}):", file=sys.stderr)
        if missing_in_vendor:
            print(f"  Missing: {sorted(missing_in_vendor)}", file=sys.stderr)
        if extra_in_vendor:
            print(f"  Extra: {sorted(extra_in_vendor)}", file=sys.stderr)
        if mismatched:
            print(f"  Hash mismatch: {sorted(mismatched)}", file=sys.stderr)
        sys.exit(1)

    print(f"[INTEGRITY SUCCESS] All {len(actual_files)} files match manifest (commit: {source_commit}).")
    sys.exit(0)


if __name__ == "__main__":
    main()

