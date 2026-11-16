from __future__ import annotations

from datetime import date, datetime
import unittest
from uuid import UUID

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser, get_current_staff_user
from csrf import CSRF_COOKIE_NAME, generate_csrf_token
from database import get_session
from main import app
import models  # noqa: F401
from models.core import AttendanceRecord, Child, ChildStatus, Family, ParentAccount, ParentChildLink
from models.pims import PunchLog


class TestBulkAttendanceOperations(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        def _override_session():
            with Session(self.engine, expire_on_commit=False) as session:
                yield session

        self.mock_user = StaffUser(
            role=Role.ADMIN,
            name="テスト管理者",
            user_id=UUID("00000000-0000-0000-0000-000000000001"),
            can_manage_child_records=True,
        )

        app.dependency_overrides[get_session] = _override_session
        app.dependency_overrides[get_current_staff_user] = lambda: self.mock_user

        self.client = TestClient(app, follow_redirects=False)
        self.csrf_token = generate_csrf_token()
        self.client.cookies.set(CSRF_COOKIE_NAME, self.csrf_token)
        self.headers = {"X-CSRF-Token": self.csrf_token}

    def tearDown(self):
        app.dependency_overrides.clear()
        self.engine.dispose()

    def _create_child(
        self,
        last_name: str,
        first_name: str,
        status: ChildStatus = ChildStatus.enrolled,
    ) -> int:
        with Session(self.engine, expire_on_commit=False) as session:
            child = Child(
                first_name=first_name,
                last_name=last_name,
                first_name_kana=first_name,
                last_name_kana=last_name,
                birth_date=date(2021, 1, 1),
                enrollment_date=date(2024, 4, 1),
                status=status,
            )
            session.add(child)
            session.commit()
            return child.id

    def test_bulk_check_in_success(self):
        """正常系: 複数園児の一括登園打刻が成功し、PIMS PunchLogも生成される。"""
        c1_id = self._create_child("山田", "太郎")
        c2_id = self._create_child("佐藤", "次郎")

        res = self.client.post(
            "/attendance/bulk-check-in",
            data={
                "child_ids": [c1_id, c2_id],
                "date": "2026-11-16",
            },
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 303)

        with Session(self.engine, expire_on_commit=False) as session:
            rec1 = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == c1_id,
                    AttendanceRecord.attendance_date == date(2026, 11, 16),
                )
            ).first()
            rec2 = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == c2_id,
                    AttendanceRecord.attendance_date == date(2026, 11, 16),
                )
            ).first()
            self.assertIsNotNone(rec1)
            self.assertIsNotNone(rec1.check_in_at)
            self.assertIsNotNone(rec2)
            self.assertIsNotNone(rec2.check_in_at)

            # PIMS PunchLog が各園児について記録されていること
            punch_logs = session.exec(select(PunchLog)).all()
            self.assertGreaterEqual(len(punch_logs), 2)
            child_ids_in_punch = {p.child_id for p in punch_logs}
            self.assertIn(str(c1_id), child_ids_in_punch)
            self.assertIn(str(c2_id), child_ids_in_punch)

    def test_bulk_check_in_rollback_on_conflict(self):
        """異常系 (all-or-nothing): 1名でも降園済みがいる場合、全体がロールバックされ誰の登園も記録されない。"""
        c1_id = self._create_child("田中", "花子")
        c2_id = self._create_child("鈴木", "一郎")

        # child2 にすでに降園打刻がある状態を作成
        with Session(self.engine, expire_on_commit=False) as session:
            rec2 = AttendanceRecord(
                child_id=c2_id,
                attendance_date=date(2026, 11, 16),
                check_in_at=datetime(2026, 11, 16, 8, 30),
                check_out_at=datetime(2026, 11, 16, 12, 0),
            )
            session.add(rec2)
            session.commit()

        res = self.client.post(
            "/attendance/bulk-check-in",
            data={
                "child_ids": [c1_id, c2_id],
                "date": "2026-11-16",
            },
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 409)
        self.assertIn("既に降園済み", res.text)

        # child1 の登園レコードがコミットされていないこと（ロールバック検証）
        with Session(self.engine, expire_on_commit=False) as session:
            rec1 = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == c1_id,
                    AttendanceRecord.attendance_date == date(2026, 11, 16),
                )
            ).first()
            self.assertIsNone(rec1)

    def test_bulk_check_in_rollback_on_withdrawn_child(self):
        """異常系 (all-or-nothing): 1名でも退園児が含まれる場合、全体がロールバックされる。"""
        c1_id = self._create_child("高橋", "三郎", status=ChildStatus.enrolled)
        c2_id = self._create_child("渡辺", "四郎", status=ChildStatus.withdrawn)

        res = self.client.post(
            "/attendance/bulk-check-in",
            data={
                "child_ids": [c1_id, c2_id],
                "date": "2026-11-16",
            },
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("在園中ではありません", res.text)

        with Session(self.engine, expire_on_commit=False) as session:
            rec1 = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == c1_id,
                    AttendanceRecord.attendance_date == date(2026, 11, 16),
                )
            ).first()
            self.assertIsNone(rec1)

    def test_bulk_check_out_success(self):
        """正常系: 複数園児の一括降園打刻が成功し、PIMS PunchLogも生成される。"""
        c1_id = self._create_child("伊藤", "五郎")
        c2_id = self._create_child("小林", "六郎")

        # 事前に登園打刻を作成
        with Session(self.engine, expire_on_commit=False) as session:
            r1 = AttendanceRecord(
                child_id=c1_id,
                attendance_date=date(2026, 11, 16),
                check_in_at=datetime(2026, 11, 16, 9, 0),
            )
            r2 = AttendanceRecord(
                child_id=c2_id,
                attendance_date=date(2026, 11, 16),
                check_in_at=datetime(2026, 11, 16, 9, 0),
            )
            session.add(r1)
            session.add(r2)
            session.commit()

        res = self.client.post(
            "/attendance/bulk-check-out",
            data={
                "child_ids": [c1_id, c2_id],
                "date": "2026-11-16",
            },
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 303)

        with Session(self.engine, expire_on_commit=False) as session:
            rec1 = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == c1_id,
                    AttendanceRecord.attendance_date == date(2026, 11, 16),
                )
            ).first()
            rec2 = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == c2_id,
                    AttendanceRecord.attendance_date == date(2026, 11, 16),
                )
            ).first()
            self.assertIsNotNone(rec1.check_out_at)
            self.assertIsNotNone(rec2.check_out_at)

    def test_bulk_check_out_rollback_when_not_checked_in(self):
        """異常系 (all-or-nothing): 1名でも未登園の園児が含まれる場合、全体がロールバックされる。"""
        c1_id = self._create_child("加藤", "七郎")
        c2_id = self._create_child("吉田", "八郎")

        # child1 だけ登園済み
        with Session(self.engine, expire_on_commit=False) as session:
            r1 = AttendanceRecord(
                child_id=c1_id,
                attendance_date=date(2026, 11, 16),
                check_in_at=datetime(2026, 11, 16, 9, 0),
            )
            session.add(r1)
            session.commit()

        res = self.client.post(
            "/attendance/bulk-check-out",
            data={
                "child_ids": [c1_id, c2_id],
                "date": "2026-11-16",
            },
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("登園打刻がされていません", res.text)

        # child1 の降園は記録されていないこと
        with Session(self.engine, expire_on_commit=False) as session:
            rec1 = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == c1_id,
                    AttendanceRecord.attendance_date == date(2026, 11, 16),
                )
            ).first()
            self.assertIsNone(rec1.check_out_at)

    def test_bulk_contact_confirmation(self):
        """出欠一括確認依頼: 複数園児に対して一括送信できる。"""
        c1_id = self._create_child("佐々木", "九郎")
        c2_id = self._create_child("松本", "十郎")

        # 保護者連携データを作成
        with Session(self.engine, expire_on_commit=False) as session:
            family = Family(family_name="佐々木家", home_address="東京都")
            session.add(family)
            session.commit()
            session.refresh(family)

            child1 = session.get(Child, c1_id)
            child1.family_id = family.id
            session.add(child1)

            parent = ParentAccount(
                family_id=family.id,
                email="parent@example.test",
                display_name="佐々木母",
            )
            session.add(parent)
            session.commit()
            session.refresh(parent)

            link = ParentChildLink(
                parent_account_id=parent.id,
                child_id=c1_id,
                relationship="母",
                is_primary=True,
            )
            session.add(link)
            session.commit()

        res = self.client.post(
            "/attendance-checks/bulk-contact-confirmation",
            data={
                "child_ids": [c1_id, c2_id],
                "date": "2026-11-16",
            },
            headers=self.headers,
        )
        self.assertEqual(res.status_code, 303)
