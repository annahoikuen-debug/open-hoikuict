"""参照系インメモリ TTL キャッシュサービス (P5-1)。

登降園の集中時間帯（朝・夕）に頻繁にアクセスされるマスタ情報
（クラス一覧、施設設定、在園児マスタ）を短時間キャッシュし、
DB読み取り負荷を軽減します。
マスタ更新時は即時パージ（ライトスルー）を行います。
"""
from __future__ import annotations

import threading
from typing import Optional

from cachetools import TTLCache
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from models import Child, ChildStatus, Classroom, FacilitySettings

_cache_lock = threading.Lock()

# キャッシュコンテナ (TTL: 秒)
_classrooms_cache: TTLCache[str, list[Classroom]] = TTLCache(maxsize=10, ttl=120)
_settings_cache: TTLCache[str, Optional[FacilitySettings]] = TTLCache(maxsize=5, ttl=300)
_children_cache: TTLCache[str, list[Child]] = TTLCache(maxsize=50, ttl=60)


def get_cached_classrooms(session: Session) -> list[Classroom]:
    """全クラス一覧を取得する（TTL: 120秒）。"""
    with _cache_lock:
        if "all" in _classrooms_cache:
            return [c.model_copy(deep=True) for c in _classrooms_cache["all"]]

    items = session.exec(
        select(Classroom).order_by(Classroom.display_order, Classroom.id)
    ).all()

    with _cache_lock:
        _classrooms_cache["all"] = [c.model_copy(deep=True) for c in items]
    return items


def get_cached_facility_settings(session: Session) -> Optional[FacilitySettings]:
    """施設基本設定を取得する（TTL: 300秒）。"""
    with _cache_lock:
        if "current" in _settings_cache:
            cached = _settings_cache["current"]
            return cached.model_copy(deep=True) if cached else None

    setting = session.exec(select(FacilitySettings)).first()

    with _cache_lock:
        _settings_cache["current"] = setting.model_copy(deep=True) if setting else None
    return setting


def get_cached_active_children(
    session: Session, classroom_id: Optional[int] = None
) -> list[Child]:
    """在園児一覧を取得する（TTL: 60秒）。"""
    key = f"class_{classroom_id}" if classroom_id else "all"
    with _cache_lock:
        if key in _children_cache:
            return [c.model_copy(deep=True) for c in _children_cache[key]]

    query = (
        select(Child)
        .options(selectinload(Child.classroom))
        .where(Child.status == ChildStatus.enrolled)
    )
    if classroom_id:
        query = query.where(Child.classroom_id == classroom_id)

    children = session.exec(query).all()

    with _cache_lock:
        _children_cache[key] = [c.model_copy(deep=True) for c in children]
    return children


def invalidate_classrooms_cache() -> None:
    """クラス一覧キャッシュを即時無効化する。"""
    with _cache_lock:
        _classrooms_cache.clear()


def invalidate_facility_settings_cache() -> None:
    """施設設定キャッシュを即時無効化する。"""
    with _cache_lock:
        _settings_cache.clear()


def invalidate_children_cache() -> None:
    """園児マスタキャッシュを即時無効化する。"""
    with _cache_lock:
        _children_cache.clear()


def invalidate_all_caches() -> None:
    """全参照系キャッシュを即時パージする。"""
    with _cache_lock:
        _classrooms_cache.clear()
        _settings_cache.clear()
        _children_cache.clear()
