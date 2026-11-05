"""振り返りパイプラインの統合テスト。架空データ・インメモリDBのみ使用。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import date
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import database
from csrf import CsrfTokenMiddleware, verify_csrf
from models import Child, Classroom
from plan_docs.auth_adapter import StaffUser, resolve_plan_docs_staff_user
from plan_docs.contracts import DocumentType, Role
from plan_docs.db_models import PlanDocumentRow
from plan_docs.routers.plans import router as plans_router
from plan_docs.routers.documents import router as documents_router


class ReflectionPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {
            "HOIKUICT_ENV":"production", "HOIKUICT_SECRET_KEY":"reflection-test-only",
            "HOIKUICT_CSRF_ENFORCE":"1",
        })
        self.env.start()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread":False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add_all([Classroom(id=1, name="A組"), Classroom(id=2,name="B組")])
            for i in (1, 2):
                session.add(Child(id=i, last_name="架空", first_name=str(i), last_name_kana="カクウ",
                    first_name_kana=str(i), birth_date=date(2024, 5, 1),
                    enrollment_date=date(2024, 6, 1), classroom_id=1))
            session.commit()
        self.user = StaffUser(role=Role.CAN_EDIT, actor_ref="staff:test", nursery_ref="test-nursery",
                              classroom_refs=("A組",), name="架空職員")
        self.app = FastAPI(dependencies=[Depends(verify_csrf)])
        self.app.add_middleware(CsrfTokenMiddleware)
        self.app.include_router(plans_router, prefix="/plans")
        self.app.include_router(documents_router, prefix="/plans")
        self.app.dependency_overrides[resolve_plan_docs_staff_user] = lambda: self.user
        def session_override():
            with Session(self.engine) as session: yield session
        self.app.dependency_overrides[database.get_session] = session_override
        self.client = TestClient(self.app, base_url="https://testserver")
        self.client.get('/plans/')
        self.client.headers['X-CSRF-Token'] = self.client.cookies.get('hoikuict_csrf')

    def tearDown(self):
        self.client.close(); self.engine.dispose(); self.env.stop(); self.temp.cleanup()

    def _csrf(self):
        return self.client.cookies.get('hoikuict_csrf')

    def _create_weekly_plan(self, target_week: str, reflection_body: str = "") -> int:
        payload = {
            "target_week": target_week,
            "classroom_ref": "A組",
            "age_class": "2歳児",
            "owner_name": "架空職員",
            "parent_document_id": "",
            "related_monthly_summary": "",
            "previous_week_reflection": reflection_body,
            "current_children_snapshot": "",
            "weekly_activities_note": "",
            "seasonal_context": "",
            "family_context": "",
            "class_notes": "",
            "include_saturday": "",
        }
        resp = self.client.post("/plans/weekly-plans", data=payload,
                                headers={"X-CSRF-Token": self._csrf()}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303, resp.text)
        with Session(self.engine) as session:
            rows = session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.WEEKLY_PLAN.value,
                PlanDocumentRow.target_week == target_week,
            )).all()
        return rows[0].id

    def _create_monthly_plan(self, target_month: str, reflection_body: str = "") -> int:
        payload = {
            "target_month": target_month,
            "class_name": "A組",
            "classroom_ref": "A組",
            "owner_name": "架空職員",
            "related_annual_summary": "",
            "previous_reflection": reflection_body,
            "current_children_snapshot": "",
            "play_interests": "",
            "seasonal_context": "",
            "family_context": "",
            "class_notes": "",
        }
        resp = self.client.post("/plans/monthly-plans", data=payload,
                                headers={"X-CSRF-Token": self._csrf()}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303, resp.text)
        with Session(self.engine) as session:
            rows = session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.MONTHLY_PLAN.value,
                PlanDocumentRow.target_month == target_month,
            )).all()
        return rows[0].id

    def _create_daily_plan_with_submitted_reflection(self, target_date: date, reflection_body: str) -> int:
        resp = self.client.post("/plans/daily-plans", data={
            "target_date": target_date.isoformat(),
            "classroom_ref": "A組",
            "age_class": "2歳児",
            "owner_name": "架空職員",
            "daily_aims": "",
            "daily_content": "",
            "timeline_row_key": ["row_1"],
            "timeline_time": [""],
            "timeline_activity": ["散歩"],
            "timeline_children": [""],
            "timeline_support": [""],
            "timeline_considerations": [""],
            "example_id": "",
            "example_source_ref": "",
            "parent_document_id": "",
        }, headers={"X-CSRF-Token": self._csrf()}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303, resp.text)
        with Session(self.engine) as session:
            docs = session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.DAILY_PLAN.value,
                PlanDocumentRow.target_date == target_date.isoformat(),
            )).all()
        doc_id = docs[0].id
        self.client.post(f"/plans/documents/{doc_id}/reflection", data={
            "reflection_body": reflection_body,
            "action": "submit",
        }, headers={"X-CSRF-Token": self._csrf()})
        return doc_id

    def test_weekly_plan_prefills_previous_week_reflection(self):
        self._create_weekly_plan("2026-W40", reflection_body="先週の絵の具遊びの振り返りです。")
        resp = self.client.get("/plans/weekly-plans/new?target_week=2026-W41&classroom_ref=A組",
                               headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("先週の絵の具遊びの振り返りです。", resp.text)
        self.assertIn("出所", resp.text)

    def test_weekly_plan_no_previous_week_no_prefill(self):
        resp = self.client.get("/plans/weekly-plans/new?target_week=2026-W41&classroom_ref=A組",
                               headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotIn("先週の絵の具遊びの振り返りです。", resp.text)

    def test_monthly_plan_prefills_previous_month_reflection(self):
        self._create_monthly_plan("2026-09", reflection_body="9月は体調不良が多かった。")
        resp = self.client.get("/plans/monthly-plans/new?target_month=2026-10&classroom_ref=A組",
                               headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("9月は体調不良が多かった。", resp.text)

    def test_monthly_plan_year_boundary(self):
        self._create_monthly_plan("2026-03", reflection_body="3月の年度末振り返り。")
        resp = self.client.get("/plans/monthly-plans/new?target_month=2026-04&classroom_ref=A組",
                               headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("3月の年度末振り返り。", resp.text)

    def test_daily_plan_shows_previous_business_day_reflection(self):
        self._create_daily_plan_with_submitted_reflection(date(2026, 10, 2),
                                                          "午睡後、絵本コーナーに自然と集まりました。")
        resp = self.client.get("/plans/daily-plans/new?target_date=2026-10-05&classroom_ref=A組",
                               headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("午睡後、絵本コーナーに自然と集まりました。", resp.text)
        self.assertIn("2026-10-02", resp.text)
        self.assertIn("insertPreviousDayReflection", resp.text)

    def test_daily_plan_skips_draft_reflection(self):
        # draft の振り返りは表示されない
        resp = self.client.post("/plans/daily-plans", data={
            "target_date": "2026-10-02", "classroom_ref": "A組", "age_class": "2歳児",
            "owner_name": "架空職員", "daily_aims": "", "daily_content": "",
            "timeline_row_key": ["row_1"], "timeline_time": [""], "timeline_activity": ["散歩"],
            "timeline_children": [""], "timeline_support": [""], "timeline_considerations": [""],
            "example_id": "",             "example_source_ref": "", "parent_document_id": "",
        }, headers={"X-CSRF-Token": self._csrf()}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303, resp.text)
        with Session(self.engine) as session:
            docs = session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.DAILY_PLAN.value,
                PlanDocumentRow.target_date == "2026-10-02",
            )).all()
        self.client.post(f"/plans/documents/{docs[0].id}/reflection", data={
            "reflection_body": "下書きの振り返り。",
            "action": "save",
        }, headers={"X-CSRF-Token": self._csrf()})
        resp = self.client.get("/plans/daily-plans/new?target_date=2026-10-05&classroom_ref=A組",
                               headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotIn("下書きの振り返り。", resp.text)

    def test_daily_plan_weekend_uses_friday(self):
        self._create_daily_plan_with_submitted_reflection(date(2026, 10, 2), "金曜日の振り返り。")
        resp = self.client.get("/plans/daily-plans/new?target_date=2026-10-05&classroom_ref=A組",
                               headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("金曜日の振り返り。", resp.text)
