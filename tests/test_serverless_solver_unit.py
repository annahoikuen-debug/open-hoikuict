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
