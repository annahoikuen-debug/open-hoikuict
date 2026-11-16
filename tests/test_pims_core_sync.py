"""PIMS ↔ Core 台帳・打刻双方向同期の結合テスト。"""

from __future__ import annotations

from datetime import date, datetime
import unittest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

import models  # noqa: F401
from models.pims import PunchChild, PunchLog
from models.core import Child, ChildStatus, AttendanceRecord
from pims_service import (
    sync_core_child_to_pims,
    record_punch,
)
from guardian_qr_service import execute_sibling_qr_punch


def _build_test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


class TestPimsCoreSync(unittest.TestCase):
    def setUp(self):
        self.engine = _build_test_engine()

    def test_sync_core_child_to_pims(self):
        """Child の情報が PunchChild へ正しく同期されること。"""
        with Session(self.engine) as session:
            child = Child(
                first_name="太郎",
                last_name="山田",
                first_name_kana="たろう",
                last_name_kana="やまだ",
                birth_date=date(2021, 5, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
            )
            session.add(child)
            session.commit()
            session.refresh(child)

            p_child = sync_core_child_to_pims(session, child)
            session.commit()

            assert p_child is not None
            assert p_child.child_id == str(child.id)
            assert p_child.name == "山田 太郎"
            assert p_child.kana == "やまだ たろう"
            assert p_child.is_active is True

            # 退園ステータスへの変更同期
            child.status = ChildStatus.withdrawn
            p_child_updated = sync_core_child_to_pims(session, child)
            session.commit()

            assert p_child_updated.is_active is False

    def test_record_punch_pims_to_core_attendance(self):
        """PIMS で打刻した際に、Core の AttendanceRecord が同期作成されること。"""
        with Session(self.engine) as session:
            child = Child(
                first_name="花子",
                last_name="佐藤",
                first_name_kana="はなこ",
                last_name_kana="さとう",
                birth_date=date(2022, 3, 15),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
            )
            session.add(child)
            session.commit()
            session.refresh(child)

            sync_core_child_to_pims(session, child)
            session.commit()

            test_now = datetime(2026, 11, 16, 8, 30)
            logs, _ = record_punch(
                session=session,
                child_ids=[str(child.id)],
                punch_type="登園",
                punched_at=test_now,
                send_email=False,
            )
            assert len(logs) == 1

            # Core の AttendanceRecord を確認
            att = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == child.id,
                    AttendanceRecord.attendance_date == test_now.date(),
                )
            ).first()

            assert att is not None
            assert att.check_in_at == test_now

            # 降園打刻の同期
            test_checkout = datetime(2026, 11, 16, 17, 30)
            record_punch(
                session=session,
                child_ids=[str(child.id)],
                punch_type="降園",
                punched_at=test_checkout,
                send_email=False,
            )

            session.refresh(att)
            assert att.check_out_at == test_checkout

    def test_qr_punch_to_pims_punch_log(self):
        """QR打刻（execute_sibling_qr_punch）実行時に PunchLog が自動作成されること。"""
        with Session(self.engine) as session:
            child = Child(
                first_name="次郎",
                last_name="鈴木",
                first_name_kana="じろう",
                last_name_kana="すずき",
                birth_date=date(2023, 1, 10),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
            )
            session.add(child)
            session.commit()
            session.refresh(child)

            target_day = date(2026, 11, 16)
            records = execute_sibling_qr_punch(
                session,
                child_ids=[child.id],
                action="check_in",
                target_date=target_day,
            )
            session.commit()

            assert len(records) == 1

            # PunchLog が同期作成されているか確認
            punch_log = session.exec(
                select(PunchLog).where(
                    PunchLog.child_id == str(child.id),
                    PunchLog.punch_type == "登園",
                )
            ).first()

            assert punch_log is not None
            assert punch_log.punched_at.date() == target_day
