"""Dynamic Session Dispatcher for Multi-Tenant Architecture.

FastAPI のリクエストコンテキスト（ContextVar: current_facility_id）に基づき、
各施設専用の独立DBセッションを自動的にルーティングする。
また、システム管理用の Master DB セッションも提供する。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Generator
from uuid import UUID

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlmodel import Session

from database_tenants.registry import TenantEngineRegistry
from security.tenant import get_current_facility_id

logger = logging.getLogger("database_tenants.dispatcher")

# グローバルな TenantEngineRegistry
_root = Path(os.getenv("HOIKUICT_DATA_ROOT", "."))
tenant_engine_registry = TenantEngineRegistry(base_dir=_root / "storage" / "tenants")

# Master DB の Engine 初期化
_master_db_path = (_root / "storage" / "master.db").resolve()
_master_db_path.parent.mkdir(parents=True, exist_ok=True)
master_engine: Engine = create_engine(
    f"sqlite:///{_master_db_path.as_posix()}",
    echo=False,
    connect_args={"timeout": 15},
)


@event.listens_for(master_engine, "connect")
def _set_master_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    del connection_record
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        cursor.close()


def is_multi_tenant_enabled() -> bool:
    """マルチテナントモード（1園1DB）が有効か判定する。"""
    mode = os.getenv("HOIKUICT_TENANT_DB_MODE", "multi").lower()
    return mode in ("multi", "1", "true", "enabled")


def get_tenant_session() -> Generator[Session, None, None]:
    """現在のアクティブな施設IDに対応する独立DBセッションを生成・提供する。

    DBが存在しない場合はテンプレートから自動プロビジョニングし、
    FastAPI Depends(get_session) から透過的に利用可能にする。
    """
    facility_id = get_current_facility_id()
    db_path = tenant_engine_registry.get_db_path(facility_id)
    if not db_path.exists():
        from database_tenants.migration import provision_tenant_from_template

        provision_tenant_from_template(facility_id, target_dir=tenant_engine_registry.base_dir)

    engine = tenant_engine_registry.get_engine(facility_id)
    with Session(engine) as session:
        yield session


def get_master_session() -> Generator[Session, None, None]:
    """法人管理・施設プロビジョニング・共通管理者用の Master DB セッションを提供する。"""
    with Session(master_engine) as session:
        yield session


def get_session_for_facility(facility_id: UUID | str) -> Session:
    """明示的に指定した facility_id の DB セッションを直接オープンする（バックグラウンドワーカー用）。"""
    engine = tenant_engine_registry.get_engine(facility_id)
    return Session(engine)
