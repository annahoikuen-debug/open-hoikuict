"""月案 前月引き継ぎの統合テスト。架空データ・インメモリDBのみ使用。"""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
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
from plan_docs.routers.monthly_library import router as monthly_router
from plan_docs.routers.documents import router as documents_router
from plan_docs.services.monthly_library import previous_months


class MonthlyCarryOverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.corpus = Path(self.temp.name) / "phrases.sqlite"
        with closing(sqlite3.connect(self.corpus)) as con:
            con.executescript('''
                CREATE TABLE source(id INTEGER PRIMARY KEY, rel_path TEXT);
                CREATE TABLE cell(id INTEGER PRIMARY KEY, source_id INTEGER, sheet TEXT);
                CREATE TABLE phrase(id INTEGER PRIMARY KEY, cell_id INTEGER, source_id INTEGER,
                    text TEXT, norm TEXT, age INTEGER, month INTEGER, year INTEGER,
                    item TEXT, section TEXT, ryoiki TEXT);
                INSERT INTO source VALUES(1, 'fictional/2025-10.xls');
                INSERT INTO cell VALUES(1, 1, 'Sheet1');
            ''')
            con.executemany("INSERT INTO phrase VALUES(?,1,1,?,?,?,10,2025,?,?,?)",
                            [(i, t, t, 1, item, section, domain)
                             for i, (t, age, item, section, domain) in enumerate([
                                 ("手洗いを楽しむ。", 1, "生活・健康", "個人別", None),
                                 ("クラスの評価", 1, "評価・反省", "クラス全体", None),
                                 ("個人の評価", 1, "評価・反省", "個人別", None),
                                 ("食育の環境", 3, "環境構成", "食育", None),
                             ], 1)])
            con.commit()
        self.corpus_bytes = self.corpus.read_bytes()
        self.env = patch.dict('os.environ', {
            "HOIKU_MONTHLY_LIBRARY_SOURCES": json.dumps({"test-nursery": {"id":"fixture", "path":str(self.corpus)}}),
            "HOIKUICT_ENV":"production", "HOIKUICT_SECRET_KEY":"carryover-test-only",
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
        self.app.include_router(monthly_router, prefix="/plans")
        self.app.include_router(documents_router, prefix="/plans")
        self.app.dependency_overrides[resolve_plan_docs_staff_user] = lambda: self.user
        def session_override():
            with Session(self.engine) as session: yield session
        self.app.dependency_overrides[database.get_session] = session_override
        self.client = TestClient(self.app, base_url="https://testserver")
        self.client.get('/plans/monthly-library')
        self.client.headers['X-CSRF-Token'] = self.client.cookies.get('hoikuict_csrf')

    def tearDown(self):
        self.assertEqual(self.corpus_bytes, self.corpus.read_bytes(), "phrase corpus must be read-only")
        self.client.close(); self.engine.dispose(); self.env.stop(); self.temp.cleanup()

    def _save_sheet(self, target_month: str, age: int, fields: dict, classroom_id: int = 1):
        """指定月の月案を下書き保存し、PlanDocumentRow を返す。"""
        payload = {
            "classroom_id": classroom_id,
            "target_month": target_month,
            "age": age,
            "owner_name": "架空職員",
            "fields": {k: {"body": v, "origins": []} for k, v in fields.items()},
        }
        token = self.client.cookies.get('hoikuict_csrf')
        resp = self.client.post("/plans/monthly-library/save", json=payload,
                                headers={"X-CSRF-Token": token})
        self.assertEqual(resp.status_code, 200, resp.text)
        with Session(self.engine) as session:
            rows = session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.target_month == target_month,
                PlanDocumentRow.document_type == DocumentType.MONTHLY_PLAN.value,
            )).all()
        return rows[0]

    def test_carry_over_copies_fields_and_origins(self):
        # 前月（2026-09）を保存
        prev = self._save_sheet("2026-09", 1, {
            "common:goal": "水遊びを通して季節を感じる。",
            "child:1:life": "朝は少し眠そう。",
        })
        # 対象月（2026-10）は未存在
        token = self.client.cookies.get('hoikuict_csrf')
        resp = self.client.post("/plans/monthly-library/carry-over", data={
            "classroom_id": 1, "target_month": "2026-10", "age": 1,
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        sheet = data["sheet"]
        self.assertEqual(sheet["fields"]["common:goal"]["body"], "水遊びを通して季節を感じる。")
        self.assertEqual(sheet["fields"]["child:1:life"]["body"], "朝は少し眠そう。")
        self.assertEqual(sheet["fields"]["common:goal"]["carried_from"], "2026-09")
        self.assertEqual(sheet["fields"]["child:1:life"]["carried_from"], "2026-09")
        # 前月の文書は不変
        with Session(self.engine) as session:
            prev_row = session.get(PlanDocumentRow, prev.id)
        self.assertEqual(prev_row.monthly_sheet["fields"]["common:goal"]["body"], "水遊びを通して季節を感じる。")
        self.assertNotIn("carried_from", prev_row.monthly_sheet["fields"]["common:goal"])

    def test_carry_over_target_exists_409(self):
        self._save_sheet("2026-09", 1, {"common:goal": "ねらい"})
        self._save_sheet("2026-10", 1, {"common:goal": "既存"})
        token = self.client.cookies.get('hoikuict_csrf')
        resp = self.client.post("/plans/monthly-library/carry-over", data={
            "classroom_id": 1, "target_month": "2026-10", "age": 1,
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(resp.status_code, 409, resp.text)

    def test_carry_over_no_previous_404(self):
        token = self.client.cookies.get('hoikuict_csrf')
        resp = self.client.post("/plans/monthly-library/carry-over", data={
            "classroom_id": 1, "target_month": "2026-10", "age": 1,
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(resp.status_code, 404, resp.text)

    def test_carry_over_preserves_roster_and_empty_new_child(self):
        # 前月に子1だけ在籍、対象月に子2が新規入園
        self._save_sheet("2026-09", 1, {"child:1:life": "元からいる子"})
        token = self.client.cookies.get('hoikuict_csrf')
        resp = self.client.post("/plans/monthly-library/carry-over", data={
            "classroom_id": 1, "target_month": "2026-10", "age": 1,
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        # 新規園児は空欄で追加、既存園児の欄は保持
        self.assertEqual(len(data["sheet"]["children"]), 2)
        self.assertEqual(data["sheet"]["fields"]["child:1:life"]["body"], "元からいる子")

    def test_carry_over_cross_template_common_fields_only(self):
        # 2歳児（乳児テンプレート）→ 3歳児（幼児テンプレート）の年度替わり
        self._save_sheet("2026-03", 2, {
            "common:goal": "共通のねらい",
            "common:home": "共通の家庭連携",
            "common:review": "共通の反省",
            "child:1:life": "個人別（コピー対象外）",
        })
        token = self.client.cookies.get('hoikuict_csrf')
        resp = self.client.post("/plans/monthly-library/carry-over", data={
            "classroom_id": 1, "target_month": "2026-04", "age": 3,
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        fields = data["sheet"]["fields"]
        self.assertEqual(fields["common:goal"]["body"], "共通のねらい")
        self.assertEqual(fields["common:home"]["body"], "共通の家庭連携")
        self.assertEqual(fields["common:review"]["body"], "共通の反省")
        self.assertNotIn("child:1:life", fields)
        self.assertEqual(fields["common:goal"]["carried_from"], "2026-03")

    def test_carry_over_across_year_boundary(self):
        self._save_sheet("2026-12", 1, {"common:goal": "年末のねらい"})
        token = self.client.cookies.get('hoikuict_csrf')
        resp = self.client.post("/plans/monthly-library/carry-over", data={
            "classroom_id": 1, "target_month": "2027-01", "age": 1,
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()
        self.assertEqual(data["sheet"]["fields"]["common:goal"]["carried_from"], "2026-12")

    def test_carry_over_requires_edit_permission(self):
        view_user = StaffUser(role=Role.VIEW_ONLY, actor_ref="staff:viewer", nursery_ref="test-nursery",
                              classroom_refs=("A組",), name="閲覧職員")
        self.app.dependency_overrides[resolve_plan_docs_staff_user] = lambda: view_user
        token = self.client.cookies.get('hoikuict_csrf')
        resp = self.client.post("/plans/monthly-library/carry-over", data={
            "classroom_id": 1, "target_month": "2026-10", "age": 1,
        }, headers={"X-CSRF-Token": token})
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_carry_over_rejects_csrf_missing(self):
        self._save_sheet("2026-09", 1, {"common:goal": "ねらい"})
        # CSRFクッキーを持たない新規クライアントでPOST → 403
        no_csrf_client = TestClient(self.app, base_url="https://testserver")
        resp = no_csrf_client.post("/plans/monthly-library/carry-over", data={
            "classroom_id": 1, "target_month": "2026-10", "age": 1,
        })
        self.assertEqual(resp.status_code, 403, resp.text)
        no_csrf_client.close()

    def test_previous_months_helper(self):
        self.assertEqual(previous_months("2026-10"), ["2026-07", "2026-08", "2026-09"])
