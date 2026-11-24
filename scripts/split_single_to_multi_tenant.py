"""Data Splitting Migration Script: Single DB to Multi-Tenant DBs.

既存の単一DB（hoikuict.db）を安全に分解し、
1. storage/master.db （法人、施設マスタ）
2. storage/templates/tenant_template.db （最新空スキーマ）
3. storage/tenants/{facility_id}.db （各園ごとの独立DB）
を生成する。
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import List


from database_tenants.migration import (
    ensure_tenant_template_initialized,
)
from models.organization import DEFAULT_FACILITY_ID, DEFAULT_ORGANIZATION_ID

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("split_single_to_multi_tenant")

# Master DB に属するテーブル（施設横断・共通管理）
MASTER_TABLES = {
    "organizations",
    "facilities",
    "system_admins",
    "schema_migrations",
}


def backup_source_db(source_db_path: Path, backup_path: Path) -> None:
    """元DBのオンラインスナップショット（VACUUM INTO）を取得する。"""
    logger.info("Taking pre-migration backup of %s -> %s", source_db_path, backup_path)
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    if backup_path.exists():
        backup_path.unlink()

    src_con = sqlite3.connect(source_db_path.as_posix())
    try:
        src_con.execute(f"VACUUM INTO '{backup_path.as_posix()}'")
    finally:
        src_con.close()
    logger.info("Backup successfully completed.")


def export_master_data(source_db_path: Path, master_db_path: Path) -> List[str]:
    """法人・施設マスタ情報を master.db へエクスポートする。"""
    logger.info("Initializing master DB at %s", master_db_path)
    master_db_path.parent.mkdir(parents=True, exist_ok=True)

    master_con = sqlite3.connect(master_db_path.as_posix())
    src_con = sqlite3.connect(source_db_path.as_posix())

    facility_ids: List[str] = []
    try:
        # organizations テーブルの移行
        master_con.execute("""
            CREATE TABLE IF NOT EXISTS organizations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT NOT NULL UNIQUE,
                description TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        # facilities テーブルの移行
        master_con.execute("""
            CREATE TABLE IF NOT EXISTS facilities (
                id TEXT PRIMARY KEY,
                organization_id TEXT NOT NULL,
                name TEXT NOT NULL,
                code TEXT,
                facility_type TEXT DEFAULT 'licensed_nursery',
                postal_code TEXT,
                address TEXT,
                phone_number TEXT,
                is_active INTEGER DEFAULT 1,
                created_at TEXT,
                updated_at TEXT
            )
        """)
        master_con.commit()

        # ソースDBに facilities があるか確認
        cur = src_con.cursor()
        has_fac = cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='facilities'").fetchone()

        if has_fac:
            fac_rows = cur.execute("SELECT id, organization_id, name, code, is_active FROM facilities").fetchall()
            for row in fac_rows:
                fac_id = str(row[0])
                facility_ids.append(fac_id)
                master_con.execute(
                    "INSERT OR REPLACE INTO facilities (id, organization_id, name, code, is_active) VALUES (?, ?, ?, ?, ?)",
                    row,
                )
            master_con.commit()
            logger.info("Exported %d facilities to master DB.", len(facility_ids))

        if not facility_ids:
            # 施設テーブルが空または未存在の場合はデフォルト施設を登録
            def_id = str(DEFAULT_FACILITY_ID).replace("-", "").lower()
            def_org = str(DEFAULT_ORGANIZATION_ID).replace("-", "").lower()
            facility_ids.append(def_id)
            master_con.execute(
                "INSERT OR REPLACE INTO facilities (id, organization_id, name, code) VALUES (?, ?, ?, ?)",
                (def_id, def_org, "既定保育園", "DEFAULT"),
            )
            master_con.commit()
            logger.info("Registered default facility: %s", def_id)

    finally:
        master_con.close()
        src_con.close()

    return facility_ids


def split_tenant_data(source_db_path: Path, facility_ids: List[str], tenants_dir: Path) -> None:
    """各園のデータを個別の storage/tenants/{facility_id}.db へ投入する。"""
    tenants_dir.mkdir(parents=True, exist_ok=True)
    template_path = ensure_tenant_template_initialized()

    src_con = sqlite3.connect(source_db_path.as_posix())
    src_tables = [
        row[0] for row in src_con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        if row[0] not in MASTER_TABLES
    ]

    try:
        for fac_id in facility_ids:
            norm_id = fac_id.replace("-", "").lower()
            tenant_db_path = tenants_dir / f"{norm_id}.db"

            logger.info("Populating tenant DB for facility: %s -> %s", fac_id, tenant_db_path.name)
            if not tenant_db_path.exists():
                shutil.copyfile(template_path, tenant_db_path)

            dest_con = sqlite3.connect(tenant_db_path.as_posix())
            try:
                # データをテーブルごとにコピー
                for table in src_tables:
                    # 対象テーブルが存在するか
                    dest_has_table = dest_con.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
                    ).fetchone()
                    if not dest_has_table:
                        continue

                    # ソースDBのカラム一覧を取得
                    col_info = src_con.execute(f"PRAGMA table_info({table})").fetchall()
                    col_names = [c[1] for c in col_info]
                    col_list_str = ", ".join(col_names)
                    placeholders = ", ".join("?" for _ in col_names)

                    # 施設IDカラムがあるテーブルは絞り込み、無いテーブル（単一園データ）は全件移行
                    if "facility_id" in col_names:
                        rows = src_con.execute(
                            f"SELECT {col_list_str} FROM {table} WHERE facility_id = ? OR facility_id = ?",
                            (fac_id, norm_id),
                        ).fetchall()
                    else:
                        rows = src_con.execute(f"SELECT {col_list_str} FROM {table}").fetchall()

                    if rows:
                        dest_con.executemany(
                            f"INSERT OR REPLACE INTO {table} ({col_list_str}) VALUES ({placeholders})",
                            rows,
                        )
                dest_con.commit()
            finally:
                dest_con.close()

    finally:
        src_con.close()

    logger.info("All tenant DBs successfully populated.")


def main():
    parser = argparse.ArgumentParser(description="Split single SQLite database into multi-tenant databases.")
    parser.add_argument("--source", default="./hoikuict.db", help="Path to source hoikuict.db")
    parser.add_argument("--dest-dir", default="./storage", help="Path to target storage directory")
    args = parser.parse_args()

    source_path = Path(args.source).resolve()
    if not source_path.exists():
        logger.error("Source database does not exist: %s", source_path)
        sys.exit(1)

    dest_dir = Path(args.dest_dir).resolve()
    backup_path = dest_dir / "backups" / f"hoikuict_pre_split_{int(Path(args.source).stat().st_mtime)}.db"
    master_db_path = dest_dir / "master.db"
    tenants_dir = dest_dir / "tenants"

    # 1. バックアップ
    backup_source_db(source_path, backup_path)

    # 2. マスターデータエクスポート
    facility_ids = export_master_data(source_path, master_db_path)

    # 3. テナントデータ分割
    split_tenant_data(source_path, facility_ids, tenants_dir)

    logger.info("🎉 Database splitting completed successfully!")


if __name__ == "__main__":
    main()
