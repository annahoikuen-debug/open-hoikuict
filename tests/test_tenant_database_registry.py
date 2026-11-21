"""Unit tests for TenantEngineRegistry and Provisioning."""

from __future__ import annotations

import tempfile
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import text
from sqlmodel import Session, select

from database_tenants.registry import TenantEngineRegistry
from database_tenants.migration import (
    ensure_tenant_template_initialized,
    provision_tenant_from_template,
)
from models.core import Child, Classroom, ChildSex, ChildStatus
from time_utils import local_today


def test_tenant_engine_registry_lru_and_pragmas():
    """Engine Registry が LRU キャッシュ上限を守り、PRAGMA WAL を自動設定すること"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir)
        registry = TenantEngineRegistry(base_dir=base_dir, max_cached_engines=3)

        ids = [uuid4() for _ in range(5)]

        # 5つの園の Engine を要求（上限は3）
        for fac_id in ids:
            engine = registry.get_engine(fac_id)
            assert engine is not None
            # WAL モードと foreign_keys が有効か確認
            with engine.connect() as conn:
                mode = conn.execute(text("PRAGMA journal_mode")).scalar()
                fk = conn.execute(text("PRAGMA foreign_keys")).scalar()
                assert str(mode).upper() == "WAL"
                assert fk == 1

        # キャッシュ上限 3 を超えていないことを確認
        assert registry.active_engine_count == 3

        # クローズ
        registry.close_all()
        assert registry.active_engine_count == 0


def test_tenant_provisioning_and_isolation():
    """テンプレートから独立DBが瞬時にプロビジョニングされ、物理的に完全分離されること"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        tenants_dir = tmp_path / "tenants"

        fac_a = uuid4()
        fac_b = uuid4()

        # 1. 2園のDBをプロビジョニング
        path_a = provision_tenant_from_template(fac_a, target_dir=tenants_dir)
        path_b = provision_tenant_from_template(fac_b, target_dir=tenants_dir)

        assert path_a.exists()
        assert path_b.exists()
        assert path_a != path_b

        # 2. 園AのDBに園児とクラスを登録
        registry = TenantEngineRegistry(base_dir=tenants_dir)
        engine_a = registry.get_engine(fac_a)
        engine_b = registry.get_engine(fac_b)

        with Session(engine_a) as session_a:
            room = Classroom(name="うさぎ組")
            session_a.add(room)
            session_a.commit()
            session_a.refresh(room)

            child = Child(
                last_name="山田",
                first_name="太郎",
                last_name_kana="ヤマダ",
                first_name_kana="タロウ",
                birth_date=local_today(),
                enrollment_date=local_today(),
                classroom_id=room.id,
            )
            session_a.add(child)
            session_a.commit()

        # 3. 園Aにはデータが存在し、園Bには1件もデータが存在しないこと（物理分離検証）
        with Session(engine_a) as session_a:
            children_a = session_a.exec(select(Child)).all()
            assert len(children_a) == 1
            assert children_a[0].last_name == "山田"

        with Session(engine_b) as session_b:
            children_b = session_b.exec(select(Child)).all()
            assert len(children_b) == 0, "園Bには園Aのデータが一切漏洩・混入してはならない"

        registry.close_all()
