"""Tenant Engine Registry for Database-per-Tenant Architecture.

園ごとに独立した SQLite データベースファイル（storage/tenants/{facility_id}.db）への
SQLAlchemy Engine を生成・LRUキャッシュ管理し、WALモードと高速メモリキャッシュを自動適用する。
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Union
from uuid import UUID

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine

logger = logging.getLogger("database_tenants.registry")

# デフォルト設定値
DEFAULT_MAX_CACHED_ENGINES = 100
DEFAULT_BUSY_TIMEOUT_MS = 5000  # 1園1DBでは競合がほぼないため5秒で十分
DEFAULT_CACHE_SIZE_KB = -16000  # 1園あたり16MBのオンメモリページキャッシュ


class TenantEngineRegistry:
    """テナント（施設）ごとの SQLite Engine を管理するスレッドセーフな LRU レジストリ。"""

    def __init__(
        self,
        base_dir: Optional[Path] = None,
        max_cached_engines: int = DEFAULT_MAX_CACHED_ENGINES,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        if base_dir is None:
            # open-hoikuict/storage/tenants をデフォルト配置先とする
            root = Path(os.getenv("HOIKUICT_DATA_ROOT", "."))
            base_dir = root / "storage" / "tenants"
        self.base_dir = base_dir.resolve()
        self.max_cached_engines = max_cached_engines
        self.busy_timeout_ms = busy_timeout_ms
        self._engines: OrderedDict[str, Engine] = OrderedDict()
        self._lock = threading.Lock()

        # ストレージディレクトリの確実な初期化
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def get_db_path(self, facility_id: Union[UUID, str]) -> Path:
        """指定施設IDに対応する SQLite DB ファイルの絶対パスを返す。"""
        normalized_id = str(facility_id).replace("-", "").lower()
        return self.base_dir / f"{normalized_id}.db"

    def get_engine(self, facility_id: Union[UUID, str]) -> Engine:
        """指定施設IDに対応する Engine を取得する（存在しない場合はLRUキャッシュに生成）。"""
        key = str(facility_id).replace("-", "").lower()

        with self._lock:
            if key in self._engines:
                self._engines.move_to_end(key)
                return self._engines[key]

            db_path = self.get_db_path(facility_id)
            db_url = f"sqlite:///{db_path.as_posix()}"

            engine = create_engine(
                db_url,
                echo=False,
                connect_args={"timeout": self.busy_timeout_ms / 1000.0},
            )
            self._configure_sqlite_pragmas(engine)

            # キャッシュ上限超過時は最も使われていない Engine を解放
            if len(self._engines) >= self.max_cached_engines:
                old_key, old_engine = self._engines.popitem(last=False)
                try:
                    old_engine.dispose()
                except Exception as exc:
                    logger.warning("Engine dispose failed for tenant %s: %s", old_key, exc)

            self._engines[key] = engine
            return engine

    def _configure_sqlite_pragmas(self, engine: Engine) -> None:
        """SQLite 接続確立時に WAL モード・高速キャッシュ等の PRAGMA を注入する。"""
        busy_timeout = self.busy_timeout_ms
        cache_size = DEFAULT_CACHE_SIZE_KB

        @event.listens_for(engine, "connect")
        def _set_pragmas(dbapi_connection, connection_record) -> None:
            del connection_record
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute(f"PRAGMA busy_timeout={busy_timeout}")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute(f"PRAGMA cache_size = {cache_size}")
                cursor.execute("PRAGMA temp_store = MEMORY")
            finally:
                cursor.close()

    def close_all(self) -> None:
        """保持している全 Engine の接続プールを破棄しキャッシュをクリアする。"""
        with self._lock:
            for key, engine in self._engines.items():
                try:
                    engine.dispose()
                except Exception as exc:
                    logger.warning("Error disposing engine %s: %s", key, exc)
            self._engines.clear()

    @property
    def active_engine_count(self) -> int:
        """現在キャッシュされているアクティブ Engine 数。"""
        with self._lock:
            return len(self._engines)
