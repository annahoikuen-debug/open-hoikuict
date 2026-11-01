"""Sync vendor/nushift from upstream repository.

Copies src/shiftai from the given nushift repository directory into
vendor/nushift/shiftai and updates vendor/nushift/README.md provenance info.

Usage:
    python scripts/sync_nushift_vendor.py [--source PATH]
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "vendor" / "nushift"
DEST_SHIFTAI = VENDOR_DIR / "shiftai"
README_FILE = VENDOR_DIR / "README.md"
TEST_FILE = ROOT / "tests" / "services" / "test_shiftai_vendor.py"

DEFAULT_SOURCE = Path(r"E:\nushift\nushift")


def get_git_commit(repo_path: Path) -> str:
    res = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip()[:7]


def compute_file_hash(path: Path) -> str:
    hasher = hashlib.sha256()
    hasher.update(path.read_bytes())
    return hasher.hexdigest()


def verify(source_repo: Path) -> bool:
    """upstream と vendor のファイルを比較し、差分があれば False を返す。"""
    src_dir = source_repo / "src" / "shiftai"
    if not src_dir.is_dir():
        print(f"Error: {src_dir} does not exist.", file=sys.stderr)
        return False
    if not DEST_SHIFTAI.is_dir():
        print(f"Error: {DEST_SHIFTAI} does not exist.", file=sys.stderr)
        return False

    src_files = {p.relative_to(src_dir): p for p in src_dir.rglob("*.py") if "__pycache__" not in p.parts}
    dest_files = {p.relative_to(DEST_SHIFTAI): p for p in DEST_SHIFTAI.rglob("*.py") if "__pycache__" not in p.parts}

    missing_in_dest = set(src_files.keys()) - set(dest_files.keys())
    extra_in_dest = set(dest_files.keys()) - set(src_files.keys())
    mismatched = []

    for rel_path in sorted(set(src_files.keys()) & set(dest_files.keys())):
        h_src = compute_file_hash(src_files[rel_path])
        h_dest = compute_file_hash(dest_files[rel_path])
        if h_src != h_dest:
            mismatched.append(rel_path)

    if missing_in_dest or extra_in_dest or mismatched:
        print("[VERIFY FAILED] Vendor differences detected:")
        if missing_in_dest:
            print(f"  Missing in vendor: {sorted(str(p) for p in missing_in_dest)}")
        if extra_in_dest:
            print(f"  Extra in vendor: {sorted(str(p) for p in extra_in_dest)}")
        if mismatched:
            print(f"  Content mismatched: {sorted(str(p) for p in mismatched)}")
        return False

    print(f"[VERIFY SUCCESS] All {len(src_files)} files match between {src_dir} and {DEST_SHIFTAI}.")
    return True


def sync(source_repo: Path) -> None:
    src_dir = source_repo / "src" / "shiftai"
    if not src_dir.is_dir():
        print(f"Error: {src_dir} does not exist.", file=sys.stderr)
        sys.exit(1)

    commit_hash = get_git_commit(source_repo)
    print(f"Syncing from {src_dir} (commit: {commit_hash}) to {DEST_SHIFTAI}...")

    # Copy files
    if DEST_SHIFTAI.exists():
        shutil.rmtree(DEST_SHIFTAI)
    shutil.copytree(src_dir, DEST_SHIFTAI)

    # Update README
    if README_FILE.exists():
        content = README_FILE.read_text(encoding="utf-8")
        content = re.sub(
            r"\| 基準コミット \| `[a-f0-9]+`.* \|",
            f"| 基準コミット | `{commit_hash}`（`master`） |",
            content,
        )
        README_FILE.write_text(content, encoding="utf-8")
        print(f"Updated {README_FILE} with commit {commit_hash}")

    # Update test_shiftai_vendor.py
    if TEST_FILE.exists():
        t_content = TEST_FILE.read_text(encoding="utf-8")
        t_content = re.sub(
            r'assert "[a-f0-9]{7}" in readme',
            f'assert "{commit_hash}" in readme',
            t_content,
        )
        TEST_FILE.write_text(t_content, encoding="utf-8")
        print(f"Updated {TEST_FILE} with commit {commit_hash}")

    print("Running verification test...")
    res = subprocess.run([sys.executable, "-m", "pytest", str(TEST_FILE)])
    if res.returncode != 0:
        print("Vendor smoke tests failed!", file=sys.stderr)
        sys.exit(res.returncode)
    print("Sync and verification successful!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync or verify nushift vendor tree")
    parser.add_argument(
        "--source",
        type=Path,
        default=DEFAULT_SOURCE,
        help="Path to nushift repository root",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify file hash integrity without copying",
    )
    args = parser.parse_args()
    if args.verify:
        success = verify(args.source)
        sys.exit(0 if success else 1)
    sync(args.source)


if __name__ == "__main__":
    main()
