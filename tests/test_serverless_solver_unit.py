"""Unit tests for NuShift Serverless Solver API and Client."""

from __future__ import annotations

import os
import unittest
from datetime import date
from fastapi.testclient import TestClient

from serverless_solver.main import app
from serverless_solver.schema import (
    FacilityConfigSchema,
    ShiftSlotSchema,
    ShiftSolveRequest,
    ShiftSolveResponse,
    StaffItemSchema,
)
from shift_schedule.services.serverless_client import (
    call_serverless_solve,
    check_serverless_health,
    is_serverless_configured,
)


class TestServerlessSolverUnit(unittest.TestCase):
    """サーバーレスソルバー単体テスト"""

    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        """GET /health が正常ステータス 200 を返すこと"""
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "healthy")
        self.assertIn("engine", data)
        self.assertIn("highs_available", data)

    def test_solve_endpoint_successful(self):
        """定員30名園モデル（職員5名・7日間・必要配置2名）で正常にシフトが求解されること"""
        req_data = {
            "facility_id": "test_fac_1",
            "target_month": "2026-11",
            "staffing_standard_key": "全国基準（厚労省）",
            "facility_config": {
                "opening_time": "07:00",
                "closing_time": "19:00",
                "eleven_hour_rule": True,
                "min_staff_present": 2,
                "closed_days": ["2026-11-01", "2026-11-08"],
                "holiday_dates": ["2026-11-03"],
            },
            "staff_list": [
                {
                    "staff_id": "S01",
                    "name": "園長/主任",
                    "employment_type": "FULL_TIME",
                    "is_qualified": True,
                    "weekly_contract_hours": 40.0,
                    "max_consecutive_days": 5,
                    "can_work_early": True,
                    "can_work_late": True,
                    "unavailable_dates": ["2026-11-04"],
                },
                {
                    "staff_id": "S02",
                    "name": "保育士B",
                    "employment_type": "FULL_TIME",
                    "is_qualified": True,
                    "weekly_contract_hours": 40.0,
                    "max_consecutive_days": 5,
                    "can_work_early": True,
                    "can_work_late": False,
                },
                {
                    "staff_id": "S03",
                    "name": "保育士C",
                    "employment_type": "FULL_TIME",
                    "is_qualified": True,
                    "weekly_contract_hours": 40.0,
                    "max_consecutive_days": 5,
                    "can_work_early": False,
                    "can_work_late": True,
                },
                {
                    "staff_id": "S04",
                    "name": "パート支援員D",
                    "employment_type": "PART_TIME",
                    "is_qualified": False,
                    "weekly_contract_hours": 20.0,
                    "max_consecutive_days": 4,
                },
                {
                    "staff_id": "S05",
                    "name": "パート支援員E",
                    "employment_type": "PART_TIME",
                    "is_qualified": False,
                    "weekly_contract_hours": 20.0,
                    "max_consecutive_days": 4,
                },
            ],
            "pinned_assignments": {
                "S01": {
                    "2026-11-02": {"code": "早", "start": "07:00", "end": "16:00", "is_pinned": True}
                }
            },
            "options": {
                "time_limit_sec": 10,
                "allow_shortfall": True,
            },
        }

        resp = self.client.post("/api/v1/solve", json=req_data)
        self.assertEqual(resp.status_code, 200)

        result = resp.json()
        self.assertIn(result["status"], ("OPTIMAL", "FEASIBLE", "FEASIBLE_WITH_SHORTFALL"))
        self.assertGreater(result["elapsed_sec"], 0.0)
        self.assertIn("schedule_matrix", result)
        self.assertIn("S01", result["schedule_matrix"])

        # ピン留めされたS01の11月2日が保護されているか
        s01_nov2 = result["schedule_matrix"]["S01"].get("2026-11-02")
        self.assertIsNotNone(s01_nov2)
        self.assertTrue(s01_nov2.get("is_pinned", False) or s01_nov2.get("code") == "早")

        # コンプライアンスレポートが含まれているか
        self.assertIn("compliance_report", result)
        self.assertGreaterEqual(result["compliance_report"]["coverage_ratio"], 0.0)

    def test_invalid_request_validation(self):
        """必須項目が欠けている場合に 422 Unprocessable Entity が返ること"""
        invalid_data = {
            "facility_id": "fac_1",
            # target_month が欠落
            "staff_list": [],
        }
        resp = self.client.post("/api/v1/solve", json=invalid_data)
        self.assertEqual(resp.status_code, 422)

    def test_client_fallback_when_unconfigured(self):
        """サーバーレスURL未設定時に安全に None を返しフォールバック可能であること"""
        old_url = os.environ.get("HOIKUICT_SERVERLESS_SOLVER_URL")
        try:
            if "HOIKUICT_SERVERLESS_SOLVER_URL" in os.environ:
                del os.environ["HOIKUICT_SERVERLESS_SOLVER_URL"]

            import importlib
            import shift_schedule.services.serverless_client as sc
            importlib.reload(sc)

            self.assertFalse(sc.is_serverless_configured())
            self.assertFalse(sc.check_serverless_health())

            dummy_req = ShiftSolveRequest(
                facility_id=1,
                target_month="2026-11",
                staff_list=[],
            )
            res = sc.call_serverless_solve(dummy_req)
            self.assertIsNone(res)
        finally:
            if old_url is not None:
                os.environ["HOIKUICT_SERVERLESS_SOLVER_URL"] = old_url

    def test_serverless_solver_bearer_auth_and_error_redaction(self):
        import os
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from serverless_solver.main import app as solver_app

        payload = {
            "facility_id": 1,
            "target_month": "2026-11",
            "staff_list": [{"staff_id": "s1", "name": "保育士A"}],
        }
        client = TestClient(solver_app)

        with patch.dict(os.environ, {"HOIKUICT_ENV": "production", "HOIKUICT_SERVERLESS_SOLVER_TOKEN": ""}):
            resp_503 = client.post("/api/v1/solve", json=payload)
            self.assertEqual(resp_503.status_code, 503)

        with patch.dict(os.environ, {"HOIKUICT_ENV": "production", "HOIKUICT_SERVERLESS_SOLVER_TOKEN": "solver-secret"}):
            self.assertEqual(client.post("/api/v1/solve", json=payload).status_code, 401)
            self.assertEqual(
                client.post("/api/v1/solve", json=payload, headers={"Authorization": "Bearer wrong"}).status_code,
                401,
            )
            with patch("serverless_solver.main.execute_solve", side_effect=RuntimeError("internal_solver_secret_trace")):
                resp_500 = client.post(
                    "/api/v1/solve",
                    json=payload,
                    headers={"Authorization": "Bearer solver-secret"},
                )
            self.assertEqual(resp_500.status_code, 500)
            self.assertNotIn("internal_solver_secret_trace", resp_500.text)

    def test_serverless_adapter_forwards_children_and_cell_slots(self):
        from datetime import date
        from unittest.mock import MagicMock, patch
        from shiftai.domain import AgeClass, CellState
        from serverless_solver.adapter import execute_solve
        from serverless_solver.schema import ChildPlanSchema, ShiftSolveRequest, StaffItemSchema

        req = ShiftSolveRequest(
            facility_id=1,
            target_month="2026-11",
            children=[
                ChildPlanSchema(
                    child_id="c1",
                    name="園児1",
                    day="2026-11-02",
                    age_class="1歳児",
                    arrive="08:30",
                    depart="16:30",
                )
            ],
            staff_list=[StaffItemSchema(staff_id="s1", name="保育士A")],
        )

        captured_contexts = []

        def fake_solve_monthly_hierarchical(context, **_kwargs):
            from types import SimpleNamespace

            captured_contexts.append(context)
            sday = SimpleNamespace(
                day=date(2026, 11, 2),
                assignments={
                    "s1": {
                        "08:30-09:00": CellState.WORK,
                        "09:00-09:30": CellState.BREAK,
                    }
                },
            )
            return SimpleNamespace(
                status=SimpleNamespace(name="OPTIMAL"),
                shift_days=[sday],
                assignments={},
                violations=[],
                score=None,
                overconstrained_shortfalls=[],
            )

        with patch("serverless_solver.adapter.solve_monthly_hierarchical", side_effect=fake_solve_monthly_hierarchical):
            resp = execute_solve(req)

        self.assertEqual(resp.status, "OPTIMAL")
        self.assertEqual(len(captured_contexts), 1)
        self.assertEqual(len(captured_contexts[0].children), 1)
        self.assertEqual(captured_contexts[0].children[0].age_class, AgeClass.AGE_1)
        slot_cell = resp.schedule_matrix["s1"]["2026-11-02"]
        self.assertEqual(slot_cell.slots["08:30-09:00"], CellState.WORK.value)
        self.assertEqual(slot_cell.slots["09:00-09:30"], CellState.BREAK.value)

    @classmethod
    def setUpClass(cls):
        import os as _os
        from unittest.mock import patch as _patch

        cls._env_patcher = _patch.dict(_os.environ, {"HOIKUICT_ENV": "test"})
        cls._env_patcher.start()

    @classmethod
    def tearDownClass(cls):
        cls._env_patcher.stop()
