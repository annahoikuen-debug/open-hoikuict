"""日案PDF帳票出力 (P2-1) のテスト。"""

from __future__ import annotations

import unittest
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlmodel import Session

from auth import Role
from database import engine
from main import app
from models import Classroom, User
from plan_docs.services.daily_export_layout import render_daily_plan_pdf
from testing_helpers import authenticate_mock_staff


class DailyPlanPdfExportTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app, base_url="https://testserver")
        unique_suffix = uuid4().hex[:8]
        self.staff_user_id = uuid4()

        with Session(engine) as session:
            staff = User(
                id=self.staff_user_id,
                username=f"staff_pdf_{unique_suffix}",
                email=f"staff_pdf_{unique_suffix}@example.com",
                display_name="指導案担当",
                staff_role="admin",
                can_export_documents=True,
                is_active=True,
            )
            session.add(staff)

            classroom = Classroom(name=f"ゆり_{unique_suffix}組", display_order=1)
            session.add(classroom)
            session.commit()
            session.refresh(classroom)
            self.classroom_id = classroom.id
            self.classroom_name = classroom.name

        authenticate_mock_staff(
            self.client,
            role=Role.ADMIN,
            user_id=self.staff_user_id,
        )

    def test_daily_plan_preview_data_endpoint(self):
        """帳票プレビューAPIで日案 (daily_plan) の情報が返ること。"""
        resp = self.client.get("/document-exports/preview/daily_plan")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["export_type"], "daily_plan")
        self.assertIn("日 案", data["preview_data"]["title"])
        self.assertTrue(len(data["preview_data"]["fields"]) > 0)

    def test_download_daily_plan_pdf(self):
        """日案PDFダウンロードエンドポイントから有効なPDFファイルが取得できること。"""
        resp = self.client.get(
            f"/document-exports/download-daily-plan?date=2026-11-16&classroom_id={self.classroom_id}"
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("content-type"), "application/pdf")
        self.assertTrue(resp.content.startswith(b"%PDF-"))
        self.assertIn("Content-Disposition", resp.headers)
        self.assertIn("daily_plan_", resp.headers["Content-Disposition"])

    def test_render_daily_plan_pdf_direct(self):
        """日案レンダラーが任意のタイムライン・ねらい・振り返りデータからPDFバイト列を生成できること。"""
        sample_plan = {
            "title": "デイリー指導計画（日案）",
            "facility_name": "あんな保育園",
            "target_date": "2026-11-16",
            "weather": "曇りのち晴",
            "classroom_name": "さくら組",
            "age_class": "4歳児",
            "owner_name": "鈴木保育士",
            "daily_aims": "集団でのルールのある遊びを通して友達と協力する喜びを味わう。",
            "daily_health_safety": "活動前後の水分補給を促し、汗の始末を自分で行えるよう見守る。",
            "timeline_rows": [
                {
                    "time_label": "9:30〜10:30",
                    "child_state": "園庭でリレー遊び。チームで順番を決めて走る。",
                    "support": "勝敗にこだわりすぎず楽しんで走れるよう声をかける。",
                    "considerations": "トラック内の小石を取り除き転倒予防を図る。",
                },
                {
                    "time_label": "10:30〜11:30",
                    "child_state": "室内で折り紙製作。どんぐりや栗を折る。",
                    "support": "折り方の見本を示し、難しい部分は一緒に手を添える。",
                    "considerations": "ハサミ使用時の安全管理徹底",
                },
            ],
            "reflection": "リレー遊びでは自分たちで応援し合う姿が見られ成長を感じた。",
        }

        pdf_bytes = render_daily_plan_pdf(sample_plan)
        self.assertIsInstance(pdf_bytes, bytes)
        self.assertTrue(pdf_bytes.startswith(b"%PDF-"))
        self.assertGreater(len(pdf_bytes), 1000)
