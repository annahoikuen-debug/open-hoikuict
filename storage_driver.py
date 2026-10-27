"""ストレージ抽象化ドライバー基盤。

ローカルファイルシステムおよび将来のS3/クラウドオブジェクトストレージに対応する
統一的なStorageDriverインターフェースとファクトリを提供する。
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional


class StorageDriver(ABC):
    """ファイルストレージの抽象基底クラス。"""

    @abstractmethod
    def save(self, path: str | Path, content: bytes | BinaryIO) -> int:
        """指定パスにファイルを保存し、書き込んだバイト数を返す。"""
        pass

    @abstractmethod
    def read(self, path: str | Path) -> bytes:
        """指定パスのファイル内容を読み込む。存在しない場合は FileNotFoundError。"""
        pass

    @abstractmethod
    def exists(self, path: str | Path) -> bool:
        """ファイルが存在するか確認する。"""
        pass

    @abstractmethod
    def delete(self, path: str | Path) -> bool:
        """ファイルを削除する。削除できた場合は True、存在しなかった場合は False。"""
        pass

    @abstractmethod
    def get_local_path(self, path: str | Path) -> Optional[Path]:
        """ローカルファイルシステム上の絶対パスを返す（ローカルストレージ時のみ）。"""
        pass


class LocalFileSystemStorageDriver(StorageDriver):
    """ローカルファイルシステムを使用するストレージドライバー。"""

    def __init__(self, base_dir: str | Path = "storage"):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str | Path) -> Path:
        resolved = (self.base_dir / path).resolve()
        if not resolved.is_relative_to(self.base_dir):
            raise ValueError(f"Path escapes storage directory: {path}")
        return resolved

    def save(self, path: str | Path, content: bytes | BinaryIO) -> int:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            return target.write_bytes(content)
        data = content.read()
        return target.write_bytes(data)

    def read(self, path: str | Path) -> bytes:
        target = self._resolve(path)
        return target.read_bytes()

    def exists(self, path: str | Path) -> bool:
        try:
            return self._resolve(path).is_file()
        except ValueError:
            return False

    def delete(self, path: str | Path) -> bool:
        try:
            target = self._resolve(path)
            if target.is_file():
                target.unlink()
                return True
        except ValueError:
            pass
        return False

    def get_local_path(self, path: str | Path) -> Optional[Path]:
        return self._resolve(path)


_default_driver: Optional[StorageDriver] = None


def get_storage_driver() -> StorageDriver:
    """設定に応じたデフォルトのストレージドライバーを返す。"""
    global _default_driver
    if _default_driver is None:
        base_path = os.getenv("HOIKUICT_STORAGE_DIR", "storage")
        _default_driver = LocalFileSystemStorageDriver(base_dir=base_path)
    return _default_driver
