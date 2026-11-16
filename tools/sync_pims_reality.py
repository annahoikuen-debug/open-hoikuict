"""Core 台帳 (Child/AttendanceRecord) と PIMS (PunchChild/PunchLog) の突合・修復スクリプト。

使用方法:
    python tools/sync_pims_reality.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database import engine
from sqlmodel import Session, select
from models.core import Child, AttendanceRecord
from models.pims import PunchChild, PunchLog
from pims_service import sync_core_child_to_pims


def audit_and_repair(dry_run: bool = False) -> None:
    print(f"=== PIMS ↔ Core 台帳・打刻突合ツール (dry_run={dry_run}) ===")

    with Session(engine) as session:
        # 1. 園児マスタ突合
        core_children = session.exec(select(Child)).all()
        print(f"Core 園児数: {len(core_children)}")

        synced_count = 0
        for child in core_children:
            c_id = str(child.id)
            p_child = session.get(PunchChild, c_id)
            if p_child is None or p_child.name != f"{child.last_name} {child.first_name}".strip():
                synced_count += 1
                if not dry_run:
                    sync_core_child_to_pims(session, child)

        print(f"園児マスタ同期/修復対象: {synced_count} 件")

        # 2. 登降園打刻突合
        attendance_records = session.exec(select(AttendanceRecord)).all()
        print(f"Core 打刻レコード数: {len(attendance_records)}")

        missing_check_in_logs = 0
        missing_check_out_logs = 0

        for att in attendance_records:
            if not att.child_id:
                continue
            cid_str = str(att.child_id)

            if att.check_in_at:
                # 登園 PunchLog が存在するか確認
                dt_start = datetime.combine(att.attendance_date, datetime.min.time())
                dt_end = datetime.combine(att.attendance_date, datetime.max.time())
                existing_in = session.exec(
                    select(PunchLog).where(
                        PunchLog.child_id == cid_str,
                        PunchLog.punch_type == "登園",
                        PunchLog.punched_at >= dt_start,
                        PunchLog.punched_at <= dt_end,
                    )
                ).first()
                if not existing_in:
                    missing_check_in_logs += 1
                    if not dry_run:
                        session.add(
                            PunchLog(
                                child_id=cid_str,
                                punched_at=att.check_in_at,
                                punch_type="登園",
                                is_auto_filled=False,
                            )
                        )

            if att.check_out_at:
                # 降園 PunchLog が存在するか確認
                dt_start = datetime.combine(att.attendance_date, datetime.min.time())
                dt_end = datetime.combine(att.attendance_date, datetime.max.time())
                existing_out = session.exec(
                    select(PunchLog).where(
                        PunchLog.child_id == cid_str,
                        PunchLog.punch_type == "降園",
                        PunchLog.punched_at >= dt_start,
                        PunchLog.punched_at <= dt_end,
                    )
                ).first()
                if not existing_out:
                    missing_check_out_logs += 1
                    if not dry_run:
                        session.add(
                            PunchLog(
                                child_id=cid_str,
                                punched_at=att.check_out_at,
                                punch_type="降園",
                                is_auto_filled=False,
                            )
                        )

        print(f"登園ログ修復対象: {missing_check_in_logs} 件")
        print(f"降園ログ修復対象: {missing_check_out_logs} 件")

        if not dry_run:
            session.commit()
            print("突合・修復処理をコミットしました。")
        else:
            print("dry-run のためコミットをスキップしました。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="PIMS ↔ Core 突合修復ツール")
    parser.add_argument("--dry-run", action="store_true", help="変更を適用せず結果のみ表示")
    args = parser.parse_args()

    audit_and_repair(dry_run=args.dry_run)
