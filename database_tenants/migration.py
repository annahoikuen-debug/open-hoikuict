"""Tenant Migration and Provisioning Manager.

全テナントDB（50園）に対する並列マイグレーション、
およびテンプレートDB（storage/templates/tenant_template.db）を用いた新規園の秒速開設を行う。
"""

from __future__ import annotations

import logging
import os
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, Sequence
from uuid import UUID

from sqlalchemy import create_engine, text
from sqlmodel import SQLModel

logger = logging.getLogger("database_tenants.migration")


def get_template_db_path() -> Path:
    """新規園開設用テンプレートDBのパスを取得する。"""
    root = Path(os.getenv("HOIKUICT_DATA_ROOT", "."))
    template_path = root / "storage" / "templates" / "tenant_template.db"
    template_path.parent.mkdir(parents=True, exist_ok=True)
    return template_path.resolve()


def ensure_tenant_template_initialized(force_recreate: bool = False) -> Path:
    """最新スキーマが適用された空の雛形DB（tenant_template.db）を作成・初期化する。"""
    template_path = get_template_db_path()

    if template_path.exists() and not force_recreate:
        return template_path

    # 全モデルをロードしてテーブル定義を登録
    import models  # noqa: F401
    import child_records.models  # noqa: F401
    import plan_docs.db_models  # noqa: F401
    import shift_schedule.db_models  # noqa: F401

    if template_path.exists():
        template_path.unlink()

    engine = create_engine(f"sqlite:///{template_path.as_posix()}", echo=False)
    try:
        # WALモードとスキーマ作成
        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.execute(text("PRAGMA synchronous=NORMAL"))
            conn.commit()

        SQLModel.metadata.create_all(engine)

        # 組み込みマイグレーションのテーブルを作成し、最新マイグレーション済みとして記録
        from database import _ensure_schema_migrations_table, _sqlite_migrations
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "  migration_id TEXT PRIMARY KEY,"
                "  applied_at TEXT DEFAULT (datetime('now'))"
                ")"
            ))
            for mid, _ in _sqlite_migrations():
                conn.execute(
                    text("INSERT OR IGNORE INTO schema_migrations (migration_id) VALUES (:mid)"),
                    {"mid": mid},
                )
            conn.commit()

        logger.info("Created tenant template DB at: %s", template_path)
    finally:
        engine.dispose()

    return template_path


def provision_tenant_from_template(facility_id: UUID | str, target_dir: Optional[Path] = None) -> Path:
    """テンプレートDBをコピーし、指定施設IDの独立DBを瞬時にプロビジョニングする（所要時間: < 0.01秒）。"""
    template_path = ensure_tenant_template_initialized()

    if target_dir is None:
        root = Path(os.getenv("HOIKUICT_DATA_ROOT", "."))
        target_dir = root / "storage" / "tenants"
    target_dir.mkdir(parents=True, exist_ok=True)

    normalized_id = str(facility_id).replace("-", "").lower()
    target_db_path = target_dir / f"{normalized_id}.db"

    if not target_db_path.exists():
        shutil.copyfile(template_path, target_db_path)
        logger.info("Provisioned new tenant DB: %s", target_db_path)

    return target_db_path


def migrate_single_tenant_db(db_path: Path) -> int:
    """単一のテナントDBに対して未適用のマイグレーションを適用する。適用件数を返す。"""
    from database import _sqlite_migrations

    if not db_path.exists():
        return 0

    engine = create_engine(f"sqlite:///{db_path.as_posix()}", echo=False)
    applied_count = 0
    try:
        with engine.connect() as conn:
            conn.execute(text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "  migration_id TEXT PRIMARY KEY,"
                "  applied_at TEXT DEFAULT (datetime('now'))"
                ")"
            ))
            applied = set(
                row[0] for row in conn.execute(text("SELECT migration_id FROM schema_migrations"))
            )

            for mid, migrate_fn in _sqlite_migrations():
                if mid not in applied:
                    try:
                        # 単一DBマイグレーションを実行
                        migrate_fn()
                        conn.execute(
                            text("INSERT INTO schema_migrations (migration_id) VALUES (:mid)"),
                            {"mid": mid},
                        )
                        conn.commit()
                        applied_count += 1
                    except Exception as exc:
                        logger.error("Migration %s failed on %s: %s", mid, db_path.name, exc)
                        raise
    finally:
        engine.dispose()

    return applied_count


def migrate_all_tenants_parallel(
    tenants_dir: Optional[Path] = None,
    max_workers: int = 8,
) -> tuple[int, int]:
    """ディレクトリ内の全テナントDBをマルチスレッドで並列マイグレーションする。

    Returns:
        (処理園数, 適用マイグレーション総数)
    """
    if tenants_dir is None:
        root = Path(os.getenv("HOIKUICT_DATA_ROOT", "."))
        tenants_dir = root / "storage" / "tenants"

    if not tenants_dir.exists():
        return 0, 0

    db_paths = [p for p in tenants_dir.glob("*.db") if not p.name.endswith("-wal") and not p.name.endswith("-shm")]
    if not db_paths:
        return 0, 0

    total_applied = 0
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(migrate_single_tenant_db, db_paths))
        total_applied = sum(results)

    logger.info("Migrated %d tenant DBs in parallel (applied %d migrations)", len(db_paths), total_applied)
    return len(db_paths), total_applied
