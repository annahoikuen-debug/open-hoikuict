"""掲示板QRコード（施設掲示・年度内固定・併用型）のテスト。"""
from __future__ import annotations

import os
import unittest
from datetime import date
from uuid import uuid4

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from guardian_qr_service import (
    generate_board_qr_token,
    generate_parent_qr_token,
    verify_board_qr_token,
    verify_parent_qr_token,
)
from models import (
    AttendanceRecord,
    Child,
    ChildStatus,
    Classroom,
    FacilitySettings,
    Family,
    ParentAccount,
    ParentChildLink,
    User,
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


class TestBoardQR(unittest.TestCase):
    def setUp(self):
        self.engine = _build_engine()
        with Session(self.engine) as session:
            self.admin = User(
                id=uuid4(),
                email="admin@example.com",
                display_name="園長",
                staff_role="admin",
                is_admin=True,
                is_active=True,
            )
            session.add(self.admin)

            self.family = Family(family_name="田中")
            self.other_family = Family(family_name="鈴木")
            session.add_all([self.family, self.other_family])
            session.flush()

            self.parent = ParentAccount(
                family_id=self.family.id,
                email="tanaka@example.com",
                display_name="田中保護者",
            )
            session.add(self.parent)
            session.flush()

            self.classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(self.classroom)
            session.flush()

            self.child1 = Child(
                family_id=self.family.id,
                classroom_id=self.classroom.id,
                last_name="田中",
                first_name="陽葵",
                last_name_kana="タナカ",
                first_name_kana="ヒマリ",
                status=ChildStatus.enrolled,
                birth_date=date(2022, 5, 1),
                enrollment_date=date(2024, 4, 1),
            )
            self.child2 = Child(
                family_id=self.family.id,
                classroom_id=self.classroom.id,
                last_name="田中",
                first_name="湊",
                last_name_kana="タナカ",
                first_name_kana="ミナト",
                status=ChildStatus.enrolled,
                birth_date=date(2024, 2, 10),
                enrollment_date=date(2024, 4, 1),
            )
            self.other_child = Child(
                family_id=self.other_family.id,
                classroom_id=self.classroom.id,
                last_name="鈴木",
                first_name="凛",
                last_name_kana="スズキ",
                first_name_kana="リン",
                status=ChildStatus.enrolled,
                birth_date=date(2023, 3, 20),
                enrollment_date=date(2024, 4, 1),
            )
            session.add_all([self.child1, self.child2, self.other_child])
            session.flush()

            session.add_all([
                ParentChildLink(parent_account_id=self.parent.id, child_id=self.child1.id),
                ParentChildLink(parent_account_id=self.parent.id, child_id=self.child2.id),
            ])
            session.commit()

            self.admin_id = self.admin.id
            self.parent_id = self.parent.id
            self.family_id = self.family.id
            self.child1_id = self.child1.id
            self.child2_id = self.child2.id
            self.other_child_id = self.other_child.id

    def test_board_qr_token_verification_and_cross_type_rejection(self):
        token = generate_board_qr_token(version=1)
        payload = verify_board_qr_token(token, expected_version=1, enabled=True)
        self.assertEqual(payload["kind"], "facility_board")
        self.assertEqual(payload["ver"], 1)

        with self.assertRaises(ValueError):
            verify_board_qr_token(token, expected_version=2, enabled=True)

        with self.assertRaises(ValueError):
            verify_board_qr_token(token, expected_version=1, enabled=False)

        with self.assertRaises(ValueError):
            verify_parent_qr_token(token)

        parent_token = generate_parent_qr_token(self.parent_id, self.family_id)
        with self.assertRaises(ValueError):
            verify_board_qr_token(parent_token, expected_version=1, enabled=True)

    def test_admin_board_qr_management_and_parent_checkin_flow(self):
        from fastapi.testclient import TestClient
        from main import app
        from database import get_session
        from auth import MOCK_PARENT_ACCOUNT_COOKIE, get_current_staff_user
        from csrf import CSRF_COOKIE_NAME, generate_csrf_token

        old_mock_env = os.environ.get("HOIKUICT_ENABLE_MOCK_AUTH")
        os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = "1"

        def _override_get_session():
            with Session(self.engine) as s:
                yield s

        def _override_staff():
            from types import SimpleNamespace
            return SimpleNamespace(
                user_id=self.admin_id,
                email="admin@example.com",
                display_name="園長",
                is_admin=True,
                staff_role="admin",
            )

        app.dependency_overrides[get_session] = _override_get_session
        app.dependency_overrides[get_current_staff_user] = _override_staff

        try:
            csrf_token = generate_csrf_token()
            admin_client = TestClient(app, cookies={CSRF_COOKIE_NAME: csrf_token})

            # 1. 管理者ポスター画面とSVG取得
            page_res = admin_client.get("/settings/board-qr")
            self.assertEqual(page_res.status_code, 200)
            self.assertIn("登降園QRコード", page_res.text)
            self.assertIn("第 1 版", page_res.text)

            svg_res = admin_client.get("/settings/board-qr.svg")
            self.assertEqual(svg_res.status_code, 200)
            self.assertEqual(svg_res.headers["content-type"], "image/svg+xml")
            self.assertIn("<svg", svg_res.text)

            token_v1 = generate_board_qr_token(version=1)

            # 2. 未ログイン保護者はログイン画面へリダイレクト（元のURLを保持）
            anon_client = TestClient(app)
            anon_res = anon_client.get(f"/parent-portal/board-check-in?t={token_v1}", follow_redirects=False)
            self.assertEqual(anon_res.status_code, 303)
            self.assertIn("/parent-portal/login?redirect=", anon_res.headers["location"])

            # 3. ログイン済み保護者が確認画面を開く
            parent_client = TestClient(
                app,
                cookies={
                    MOCK_PARENT_ACCOUNT_COOKIE: str(self.parent_id),
                    CSRF_COOKIE_NAME: csrf_token,
                },
            )
            checkin_get = parent_client.get(f"/parent-portal/board-check-in?t={token_v1}")
            self.assertEqual(checkin_get.status_code, 200)
            self.assertIn("田中 陽葵", checkin_get.text)
            self.assertIn("田中 湊", checkin_get.text)

            # 4. 兄弟まとめて登園打刻（他人の子IDが混ざっても無視される）
            checkin_post = parent_client.post(
                "/parent-portal/board-check-in",
                data={
                    "t": token_v1,
                    "action": "check_in",
                    "child_ids": [str(self.child1_id), str(self.child2_id), str(self.other_child_id)],
                    "csrf_token": csrf_token,
                },
                headers={"X-CSRF-Token": csrf_token},
            )
            self.assertEqual(checkin_post.status_code, 200)
            self.assertIn("登園の打刻が完了しました", checkin_post.text)
            self.assertIn("2名分の打刻を記録しました", checkin_post.text)

            with Session(self.engine) as s:
                r1 = s.exec(select(AttendanceRecord).where(AttendanceRecord.child_id == self.child1_id)).first()
                r2 = s.exec(select(AttendanceRecord).where(AttendanceRecord.child_id == self.child2_id)).first()
                r_other = s.exec(select(AttendanceRecord).where(AttendanceRecord.child_id == self.other_child_id)).first()
                self.assertIsNotNone(r1.check_in_at)
                self.assertIsNotNone(r2.check_in_at)
                self.assertIsNone(r_other)

            # 5. 管理者がQRを再発行すると旧トークン（v1）は即座に拒否される
            reissue_res = admin_client.post(
                "/settings/board-qr",
                data={"action": "reissue", "csrf_token": csrf_token},
                headers={"X-CSRF-Token": csrf_token},
                follow_redirects=False,
            )
            self.assertEqual(reissue_res.status_code, 303)
            self.assertIn("reissued=true", reissue_res.headers["location"])

            with Session(self.engine) as s:
                fs = s.get(FacilitySettings, 1)
                self.assertEqual(fs.board_qr_version, 2)

            old_qr_res = parent_client.get(f"/parent-portal/board-check-in?t={token_v1}")
            self.assertEqual(old_qr_res.status_code, 400)
            self.assertIn("再発行により無効", old_qr_res.text)

            # 6. 新トークン（v2）では降園打刻ができる
            token_v2 = generate_board_qr_token(version=2)
            checkout_post = parent_client.post(
                "/parent-portal/board-check-in",
                data={
                    "t": token_v2,
                    "action": "check_out",
                    "actual_pickup_person": "父",
                    "child_ids": [str(self.child1_id)],
                    "csrf_token": csrf_token,
                },
                headers={"X-CSRF-Token": csrf_token},
            )
            self.assertEqual(checkout_post.status_code, 200)
            self.assertIn("降園の打刻が完了しました", checkout_post.text)

            # 7. 受付停止中はv2でも拒否される
            toggle_res = admin_client.post(
                "/settings/board-qr",
                data={"action": "toggle", "csrf_token": csrf_token},
                headers={"X-CSRF-Token": csrf_token},
                follow_redirects=False,
            )
            self.assertEqual(toggle_res.status_code, 303)
            stopped_res = parent_client.get(f"/parent-portal/board-check-in?t={token_v2}")
            self.assertEqual(stopped_res.status_code, 400)
            self.assertIn("停止中", stopped_res.text)
        finally:
            app.dependency_overrides.pop(get_session, None)
            app.dependency_overrides.pop(get_current_staff_user, None)
            if old_mock_env is None:
                os.environ.pop("HOIKUICT_ENABLE_MOCK_AUTH", None)
            else:
                os.environ["HOIKUICT_ENABLE_MOCK_AUTH"] = old_mock_env
