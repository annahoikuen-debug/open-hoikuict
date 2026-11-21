"""Concurrency Stress Test for Database-per-Tenant Architecture.

定員30名の50園が同時に登園打刻・書き込みトランザクションを実行しても、
SQLiteの書き込みロック（database is locked）が0件であり、
ミリ秒級で完全に並列処理されることを実証するベンチマークテスト。
"""

from __future__ import annotations

import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4
import pytest
from sqlmodel import Session, select

from database_tenants.registry import TenantEngineRegistry
from database_tenants.migration import provision_tenant_from_template
from models.core import Child, Classroom, AttendanceRecord
from time_utils import local_today, utc_now


def test_50_facilities_concurrent_write_zero_lock_conflicts():
    """50園が同時に打刻・書き込みを行っても、ロック競合が0件で全件高速完了すること"""
    with tempfile.TemporaryDirectory() as tmp_dir:
        base_dir = Path(tmp_dir) / "tenants"
        registry = TenantEngineRegistry(base_dir=base_dir, max_cached_engines=100)

        num_facilities = 50
        facility_ids = [uuid4() for _ in range(num_facilities)]

    try:
        # 1. 50園のDBをプロビジョニング（各園に初期クラスを作成）
        for fac_id in facility_ids:
            provision_tenant_from_template(fac_id, target_dir=base_dir)
            engine = registry.get_engine(fac_id)
            with Session(engine) as session:
                room = Classroom(name="きりん組")
                session.add(room)
                session.commit()

        # 2. 50園から一斉に同時書き込みトランザクションを発行するワーカー関数
        errors: list[Exception] = []
        timings: list[float] = []

        def _facility_concurrent_worker(fac_id):
            try:
                t0 = time.perf_counter()
                engine = registry.get_engine(fac_id)
                with Session(engine) as session:
                    room = session.exec(select(Classroom)).first()
                    # 園児追加
                    child = Child(
                        last_name=f"園児_{str(fac_id)[:4]}",
                        first_name="太郎",
                        last_name_kana="エンジ",
                        first_name_kana="タロウ",
                        birth_date=local_today(),
                        enrollment_date=local_today(),
                        classroom_id=room.id if room else None,
                    )
                    session.add(child)
                    session.commit()
                    session.refresh(child)

                    # 打刻レコード追加
                    record = AttendanceRecord(
                        child_id=child.id,
                        attendance_date=local_today(),
                        check_in_at=utc_now(),
                    )
                    session.add(record)
                    session.commit()

                elapsed_ms = (time.perf_counter() - t0) * 1000
                timings.append(elapsed_ms)
            except Exception as exc:
                errors.append(exc)

        # 3. 50スレッドで一斉並列実行
        start_all = time.perf_counter()
        with ThreadPoolExecutor(max_workers=50) as executor:
            list(executor.map(_facility_concurrent_worker, facility_ids))
        total_duration_sec = time.perf_counter() - start_all

        # 4. 検証アサーション
        # (1) database is locked エラーなどの例外が一切発生していないこと
        assert len(errors) == 0, f"Concurrent write produced errors: {errors}"

        # (2) 全50園でレコードが正常に永続化されていること
        for fac_id in facility_ids:
            engine = registry.get_engine(fac_id)
            with Session(engine) as session:
                children = session.exec(select(Child)).all()
                attendances = session.exec(select(AttendanceRecord)).all()
                assert len(children) == 1
                assert len(attendances) == 1

        # (3) 50園並列書き込みが短時間（10秒以内）、平均1秒未満で完了すること
        avg_ms = sum(timings) / len(timings) if timings else 0.0
        assert total_duration_sec < 10.0, f"Total execution took too long: {total_duration_sec:.2f}s"
        assert avg_ms < 1000.0, f"Average transaction took too long: {avg_ms:.2f}ms"
    finally:
        registry.close_all()
