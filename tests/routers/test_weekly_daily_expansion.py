"""週案→日案展開の統合テスト。架空データ・インメモリDBのみ使用。"""
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
from models import Classroom
from plan_docs.auth_adapter import StaffUser, resolve_plan_docs_staff_user
from plan_docs.contracts import DocumentStatus, DocumentType, Role
from plan_docs.db_models import PlanDocumentRow
from plan_docs.routers.plans import router as plans_router
from plan_docs.routers.documents import router as documents_router


class WeeklyDailyExpansionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict('os.environ', {
            "HOIKUICT_ENV":"production", "HOIKUICT_SECRET_KEY":"expansion-test-only",
            "HOIKUICT_CSRF_ENFORCE":"1",
        })
        self.env.start()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread":False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add_all([Classroom(id=1, name="A組"), Classroom(id=2,name="B組")])
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

    def _create_weekly_plan(self, target_week: str, classroom_ref: str = "A組",
                            age_class: str = "2歳児", schedule: dict | None = None,
                            status: str = DocumentStatus.APPROVED.value,
                            weekly_activities_note: str = "") -> int:
        payload = {
            "target_week": target_week,
            "classroom_ref": classroom_ref,
            "age_class": age_class,
            "owner_name": "架空職員",
            "parent_document_id": "",
            "related_monthly_summary": "",
            "previous_week_reflection": "",
            "current_children_snapshot": "",
            "weekly_activities_note": weekly_activities_note,
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

    def _get_document_sections(self, document_id: int):
        with Session(self.engine) as session:
            doc = session.get(PlanDocumentRow, document_id)
        return doc.sections

    def test_daily_plan_prefill_from_weekly(self):
        # 2026-09-28 (月) の週案を作成し、その週の月曜日に日案フォームを開くと事前入力される
        weekly_id = self._create_weekly_plan("2026-W40",
                                             weekly_activities_note="粘土遊び")

        resp = self.client.get("/plans/daily-plans/new?target_date=2026-09-28&classroom_ref=A組",
                               headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        html = resp.text
        self.assertIn("粘土遊び", html)
        self.assertIn("週案から事前入力しました", html)
        # hidden parent_document_id
        self.assertIn(f'name="parent_document_id" type="hidden" value="{weekly_id}"', html)

    def test_daily_plan_no_weekly_no_prefill(self):
        resp = self.client.get("/plans/daily-plans/new?target_date=2026-09-28&classroom_ref=A組",
                               headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertNotIn("週案から事前入力しました", resp.text)

    def test_create_daily_plan_sets_parent_document_id(self):
        schedule = {
            "layout": "weekly_grid",
            "include_saturday": False,
            "rows": [
                {"row_key": "mon", "cells": {
                    "activity": {"body": "粘土遊び"},
                    "support": {"body": "用具の置き場に配慮"},
                }},
            ],
        }
        weekly_id = self._create_weekly_plan("2026-W40", schedule=schedule)

        token = self._csrf()
        resp = self.client.post("/plans/daily-plans", data={
            "target_date": "2026-09-28",
            "classroom_ref": "A組",
            "age_class": "2歳児",
            "owner_name": "架空職員",
            "daily_aims": "",
            "daily_content": "",
            "timeline_row_key": ["row_1"],
            "timeline_time": [""],
            "timeline_activity": ["粘土遊び"],
            "timeline_children": [""],
            "timeline_support": ["用具の置き場に配慮"],
            "timeline_considerations": [""],
            "example_id": "",
            "example_source_ref": "",
            "parent_document_id": str(weekly_id),
        }, headers={"X-CSRF-Token": token}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303, resp.text)

        with Session(self.engine) as session:
            docs = session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.DAILY_PLAN.value,
                PlanDocumentRow.target_date == date(2026, 9, 28).isoformat(),
            )).all()
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].parent_document_id, weekly_id)
        self.assertIn(f"weekly.document:{weekly_id}", str(docs[0].sections))

    def test_create_daily_plan_rejects_invalid_parent(self):
        resp = self.client.post("/plans/daily-plans", data={
            "target_date": "2026-09-28",
            "classroom_ref": "A組",
            "age_class": "2歳児",
            "owner_name": "架空職員",
            "daily_aims": "",
            "daily_content": "",
            "timeline_row_key": ["row_1"],
            "timeline_time": [""],
            "timeline_activity": ["粘土遊び"],
            "timeline_children": [""],
            "timeline_support": [""],
            "timeline_considerations": [""],
            "example_id": "",
            "example_source_ref": "",
            "parent_document_id": "99999",
        }, headers={"X-CSRF-Token": self._csrf()})
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertIn("週案が見つかりません", resp.text)

    def test_bulk_from_weekly_creates_drafts(self):
        weekly_id = self._create_weekly_plan("2026-W40",
                                             weekly_activities_note="粘土遊び")

        token = self._csrf()
        resp = self.client.post("/plans/daily-plans/bulk-from-weekly", data={
            "target_week": "2026-W40",
            "classroom_ref": "A組",
        }, headers={"X-CSRF-Token": token}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303, resp.text)
        self.assertIn("created=5", resp.headers["location"])
        self.assertIn("skipped=0", resp.headers["location"])

        with Session(self.engine) as session:
            docs = session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.DAILY_PLAN.value,
                PlanDocumentRow.parent_document_id == weekly_id,
            )).all()
        self.assertEqual(len(docs), 5)
        for d in docs:
            self.assertEqual(d.status, DocumentStatus.DRAFT.value)

    def test_bulk_from_weekly_skips_existing(self):
        self._create_weekly_plan("2026-W40", weekly_activities_note="粘土遊び")
        # 月曜日の日案を先に作成
        resp = self.client.post("/plans/daily-plans", data={
            "target_date": "2026-09-28", "classroom_ref": "A組", "age_class": "2歳児",
            "owner_name": "架空職員", "daily_aims": "", "daily_content": "",
            "timeline_row_key": ["row_1"], "timeline_time": [""], "timeline_activity": ["既存"],
            "timeline_children": [""], "timeline_support": [""], "timeline_considerations": [""],
            "example_id": "", "example_source_ref": "", "parent_document_id": "",
        }, headers={"X-CSRF-Token": self._csrf()}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303, resp.text)

        token = self._csrf()
        resp = self.client.post("/plans/daily-plans/bulk-from-weekly", data={
            "target_week": "2026-W40", "classroom_ref": "A組",
        }, headers={"X-CSRF-Token": token}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303, resp.text)
        self.assertIn("skipped=1", resp.headers["location"])

    def test_bulk_from_weekly_no_weekly_404(self):
        token = self._csrf()
        resp = self.client.post("/plans/daily-plans/bulk-from-weekly", data={
            "target_week": "2026-W40", "classroom_ref": "A組",
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(resp.status_code, 404, resp.text)
