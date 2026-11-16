from __future__ import annotations

import unittest
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import child_records.models  # noqa: F401
from auth import Role, StaffUser
from models import AttendanceRecord, Child, ChildStatus, Classroom
import routers.attendance as attendance_module


class AttendanceOptimisticLockTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(attendance_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.current_user = StaffUser(role=Role.CAN_EDIT, name="打刻担当")

        def override_get_current_staff_user():
            return self.current_user

        self.app.dependency_overrides[attendance_module.get_session] = override_get_session
        self.app.dependency_overrides[attendance_module.get_current_staff_user] = override_get_current_staff_user

        self.client = TestClient(self.app, follow_redirects=False)
        self.today = date(2026, 11, 16)

        with Session(self.engine) as session:
            classroom = Classroom(name="ひまわり組", capacity=20)
            session.add(classroom)
            session.commit()
            session.refresh(classroom)

            self.child = Child(
                first_name="太郎",
                last_name="山田",
                first_name_kana="タロウ",
                last_name_kana="ヤマダ",
                status=ChildStatus.enrolled,
                birth_date=date(2022, 5, 1),
                enrollment_date=date(2023, 4, 1),
                classroom_id=classroom.id,
            )
            session.add(self.child)
            session.commit()
            session.refresh(self.child)

    def test_check_in_and_out_optimistic_locking(self):
        # 1. 初回登園打刻 (レコード新規作成 -> lock_version=1)
        res1 = self.client.post(
            f"/attendance/{self.child.id}/check-in",
            data={"date": self.today.isoformat(), "expected_version": 1},
        )
        assert res1.status_code == 303, res1.text

        with Session(self.engine) as session:
            record = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == self.child.id,
                    AttendanceRecord.attendance_date == self.today,
                )
            ).first()
            assert record is not None
            assert record.check_in_at is not None
            assert record.lock_version == 1

        # 2. 正常な降園打刻 (expected_version=1 -> 更新成功し lock_version=2)
        res2 = self.client.post(
            f"/attendance/{self.child.id}/check-out",
            data={"date": self.today.isoformat(), "expected_version": 1},
        )
        assert res2.status_code == 303, res2.text

        with Session(self.engine) as session:
            record = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == self.child.id,
                    AttendanceRecord.attendance_date == self.today,
                )
            ).first()
            assert record is not None
            assert record.check_out_at is not None
            assert record.lock_version == 2

        # 3. 別の端末が古い画面 (expected_version=1) のまま打刻を試行 -> 409 Conflict
        res_conflict = self.client.post(
            f"/attendance/{self.child.id}/check-out",
            data={"date": self.today.isoformat(), "expected_version": 1},
        )
        assert res_conflict.status_code == 409
        assert "他の端末で打刻が更新されています" in res_conflict.json()["detail"]
