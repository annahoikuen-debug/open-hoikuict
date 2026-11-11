"""保護者登降園QRコードおよびキオスク兄弟打刻のテスト。"""
from __future__ import annotations

import unittest
from datetime import date
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models import (
    AttendanceRecord,
    Child,
    ChildStatus,
    Classroom,
    Family,
    ParentAccount,
    ParentChildLink,
)
from guardian_qr_service import (
    generate_parent_qr_svg,
    generate_parent_qr_token,
    verify_parent_qr_token,
)


def _build_engine():
    import models  # noqa: F401

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


class TestGuardianQRService(unittest.TestCase):
    def setUp(self):
        self.engine = _build_engine()
        with Session(self.engine) as session:
            self.family = Family(family_name="佐藤")
            session.add(self.family)
            session.flush()

            self.parent = ParentAccount(
                family_id=self.family.id,
                email="sato@example.com",
                display_name="佐藤保護者",
            )
            session.add(self.parent)
            session.flush()

            self.classroom1 = Classroom(name="ひよこ組", display_order=1)
            self.classroom2 = Classroom(name="うさぎ組", display_order=2)
            session.add_all([self.classroom1, self.classroom2])
            session.flush()

            self.child1 = Child(
                family_id=self.family.id,
                classroom_id=self.classroom1.id,
                last_name="佐藤",
                first_name="蓮",
                last_name_kana="サトウ",
                first_name_kana="レン",
                status=ChildStatus.enrolled,
                birth_date=date(2022, 6, 1),
                enrollment_date=date(2024, 4, 1),
            )
            self.child2 = Child(
                family_id=self.family.id,
                classroom_id=self.classroom2.id,
                last_name="佐藤",
                first_name="葵",
                last_name_kana="サトウ",
                first_name_kana="アオイ",
                status=ChildStatus.enrolled,
                birth_date=date(2024, 1, 15),
                enrollment_date=date(2024, 4, 1),
            )
            session.add_all([self.child1, self.child2])
            session.flush()

            session.add_all([
                ParentChildLink(parent_account_id=self.parent.id, child_id=self.child1.id),
                ParentChildLink(parent_account_id=self.parent.id, child_id=self.child2.id),
            ])
            session.commit()

            self.child1_id = self.child1.id
            self.child2_id = self.child2.id
            self.parent_id = self.parent.id
            self.family_id = self.family.id

    def test_qr_token_generation_and_verification(self):
        token = generate_parent_qr_token(
            parent_account_id=self.parent_id,
            family_id=self.family_id,
            expires_in_days=7,
        )
        self.assertIsInstance(token, str)
        self.assertIn(".", token)

        payload = verify_parent_qr_token(token)
        self.assertEqual(payload["pid"], self.parent_id)
        self.assertEqual(payload["fid"], self.family_id)

    def test_qr_token_tampered_fails(self):
        token = generate_parent_qr_token(
            parent_account_id=self.parent_id,
            family_id=self.family_id,
        )
        tampered = token[:-2] + ("aa" if token[-2:] != "aa" else "bb")
        with self.assertRaises(ValueError):
            verify_parent_qr_token(tampered)

    def test_qr_token_expired_fails(self):
        token = generate_parent_qr_token(
            parent_account_id=self.parent_id,
            family_id=self.family_id,
            expires_in_days=-1,  # 過去の日時（期限切れ）
        )
        with self.assertRaises(ValueError):
            verify_parent_qr_token(token)

    def test_qr_svg_generation(self):
        token = generate_parent_qr_token(
            parent_account_id=self.parent_id,
            family_id=self.family_id,
        )
        svg_content = generate_parent_qr_svg(token)
        self.assertIn("<svg", svg_content)
        self.assertIn("</svg>", svg_content)

    def test_parent_portal_qr_code_endpoint(self):
        import os
        from fastapi.testclient import TestClient
        from main import app
        from database import get_session
        from auth import MOCK_PARENT_ACCOUNT_COOKIE

        old_mock_env = os.environ.get("HOIKUICT_ENABLE_MOCK_AUTH")
        os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = "1"

        def _override_get_session():
            with Session(self.engine) as s:
                yield s

        app.dependency_overrides[get_session] = _override_get_session
        try:
            client = TestClient(app, cookies={MOCK_PARENT_ACCOUNT_COOKIE: str(self.parent_id)})
            res = client.get("/parent-portal/qr-code.svg")
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.headers["content-type"], "image/svg+xml")
            self.assertIn("<svg", res.text)
            self.assertIn("</svg>", res.text)
        finally:
            app.dependency_overrides.pop(get_session, None)
            if old_mock_env is None:
                os.environ.pop("HOIKUICT_ENABLE_MOCK_AUTH", None)
            else:
                os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = old_mock_env

    def test_kiosk_qr_scan_and_commit_endpoints(self):
        from fastapi.testclient import TestClient
        from main import app
        from database import get_session
        from kiosk_security import require_kiosk_access
        from csrf import generate_csrf_token, CSRF_COOKIE_NAME

        def _override_get_session():
            with Session(self.engine) as s:
                yield s

        app.dependency_overrides[get_session] = _override_get_session
        app.dependency_overrides[require_kiosk_access] = lambda: None
        try:
            csrf_token = generate_csrf_token()
            client = TestClient(app, cookies={CSRF_COOKIE_NAME: csrf_token})

            qr_token = generate_parent_qr_token(
                parent_account_id=self.parent_id,
                family_id=self.family_id,
            )

            # 1. QRスキャンAPI (/guardian/qr/scan)
            scan_res = client.post(
                "/guardian/qr/scan",
                data={"qr_token": qr_token, "csrf_token": csrf_token},
                headers={"X-CSRF-Token": csrf_token},
            )
            self.assertEqual(scan_res.status_code, 200)
            scan_data = scan_res.json()
            self.assertEqual(scan_data["family_name"], "佐藤")
            self.assertEqual(len(scan_data["children"]), 2)
            c_names = [c["full_name"] for c in scan_data["children"]]
            self.assertIn("佐藤 蓮", c_names)
            self.assertIn("佐藤 葵", c_names)

            # 2. 兄弟まとめ登園コミット (/guardian/qr/commit)
            commit_res = client.post(
                "/guardian/qr/commit",
                data={
                    "qr_token": qr_token,
                    "action": "check_in",
                    "child_ids": [str(self.child1_id), str(self.child2_id)],
                    "csrf_token": csrf_token,
                },
                headers={"X-CSRF-Token": csrf_token},
            )
            self.assertEqual(commit_res.status_code, 200)
            commit_data = commit_res.json()
            self.assertTrue(commit_data["success"])
            self.assertEqual(commit_data["count"], 2)
            self.assertIn("登園を受け付けました", commit_data["message"])

            # DBレコード検証（登園）
            with Session(self.engine) as session:
                r1 = session.exec(select(AttendanceRecord).where(
                    AttendanceRecord.child_id == self.child1_id,
                )).first()
                r2 = session.exec(select(AttendanceRecord).where(
                    AttendanceRecord.child_id == self.child2_id,
                )).first()
                self.assertIsNotNone(r1)
                self.assertIsNotNone(r2)
                self.assertIsNotNone(r1.check_in_at)
                self.assertIsNotNone(r2.check_in_at)
                self.assertIsNone(r1.check_out_at)

            # 3. 兄弟まとめ降園コミット (/guardian/qr/commit)
            checkout_res = client.post(
                "/guardian/qr/commit",
                data={
                    "qr_token": qr_token,
                    "action": "check_out",
                    "actual_pickup_person": "母",
                    "child_ids": [str(self.child1_id), str(self.child2_id)],
                    "csrf_token": csrf_token,
                },
                headers={"X-CSRF-Token": csrf_token},
            )
            self.assertEqual(checkout_res.status_code, 200)
            checkout_data = checkout_res.json()
            self.assertTrue(checkout_data["success"])
            self.assertIn("降園を受け付けました", checkout_data["message"])

            # DBレコード検証（降園）
            with Session(self.engine) as session:
                r1 = session.exec(select(AttendanceRecord).where(
                    AttendanceRecord.child_id == self.child1_id,
                )).first()
                self.assertIsNotNone(r1.check_out_at)
                self.assertEqual(r1.actual_pickup_person, "母")

            # 4. 不正なトークンの拒絶テスト
            tampered_token = qr_token[:-4] + "xxxx"
            bad_res = client.post(
                "/guardian/qr/scan",
                data={"qr_token": tampered_token, "csrf_token": csrf_token},
                headers={"X-CSRF-Token": csrf_token},
            )
            self.assertEqual(bad_res.status_code, 400)

            # 5. 他人の園児IDを混入させたコミットの拒絶テスト
            unauthorized_res = client.post(
                "/guardian/qr/commit",
                data={
                    "qr_token": qr_token,
                    "action": "check_in",
                    "child_ids": ["99999"],  # 存在しない/無関係な園児
                    "csrf_token": csrf_token,
                },
                headers={"X-CSRF-Token": csrf_token},
            )
            self.assertEqual(unauthorized_res.status_code, 400)
        finally:
            app.dependency_overrides.pop(get_session, None)
            app.dependency_overrides.pop(require_kiosk_access, None)



