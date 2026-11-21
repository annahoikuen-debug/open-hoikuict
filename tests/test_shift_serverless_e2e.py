"""End-to-End integration tests for NuShift Serverless Solver fallback and execution."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from sqlmodel import Session

from database import engine
from shift_schedule.contracts import PlanStatus, SolveJobStatus
from shift_schedule.db_models import ShiftPlans, ShiftSolveJobs
from shift_schedule.services.serverless_client import (
    execute_via_serverless_if_available,
    is_serverless_configured,
)
from shift_schedule.services.solve_jobs import _run_solve_sync


class TestShiftServerlessE2E(unittest.TestCase):
    """サーバーレスソルバー統合E2Eテスト"""

    def setUp(self):
        self.session = Session(engine)

    def tearDown(self):
        self.session.close()

    def test_serverless_unconfigured_falls_back_to_local(self):
        """サーバーレス未設定時に execute_via_serverless_if_available が None を返しフォールバックすること"""
        with patch.dict(os.environ, {"HOIKUICT_SERVERLESS_SOLVER_URL": ""}):
            import importlib
            import shift_schedule.services.serverless_client as sc
            importlib.reload(sc)

            self.assertFalse(sc.is_serverless_configured())
            res = sc.execute_via_serverless_if_available(
                context=MagicMock(),
                facility_id=1,
                staffing_standard_key="全国基準（厚労省）",
                time_limit_sec=10,
            )
            self.assertIsNone(res)

    def test_serverless_mock_success_returns_solver_result(self):
        """サーバーレスAPIが正常応答した場合に SolveResult 互換オブジェクトへ正しく復元されること"""
        from datetime import date
        from serverless_solver.schema import (
            ComplianceReportSchema,
            ScoreReportSchema,
            ShiftSlotSchema,
            ShiftSolveResponse,
        )
        from shiftai.domain import CellState, ShiftDay
        from shiftai.monthly import SolveResult, SolveStatus

        mock_resp = ShiftSolveResponse(
            status="OPTIMAL",
            elapsed_sec=0.45,
            score=ScoreReportSchema(hard=0, medium=0, soft=-10),
            schedule_matrix={
                "S01": {
                    "2026-11-01": ShiftSlotSchema(code="早", is_pinned=False),
                    "2026-11-02": ShiftSlotSchema(code="休", is_pinned=False),
                }
            },
            compliance_report=ComplianceReportSchema(coverage_ratio=1.0),
        )

        dummy_context = MagicMock()
        dummy_context.staff = []
        dummy_context.contracts = {}
        dummy_context.preferences = {}
        dummy_context.fixed_assignments = {}
        dummy_context.target_month = "2026-11"
        dummy_context.all_days = [date(2026, 11, 1), date(2026, 11, 2)]
        dummy_context.facility_settings.day_open.strftime.return_value = "07:00"
        dummy_context.facility_settings.day_close.strftime.return_value = "19:00"
        dummy_context.facility_settings.granularity_min = 30
        dummy_context.facility_settings.closed_days = ()
        dummy_context.facility_settings.holiday_dates = ()
        dummy_context.prior_duty_history = {}

        with patch.dict(os.environ, {"HOIKUICT_SERVERLESS_SOLVER_URL": "http://mock-solver"}):
            import importlib
            import shift_schedule.services.serverless_client as sc
            importlib.reload(sc)

            with patch.object(sc, "call_serverless_solve", return_value=mock_resp):
                result = sc.execute_via_serverless_if_available(
                    context=dummy_context,
                    facility_id=1,
                    staffing_standard_key="全国基準（厚労省）",
                    time_limit_sec=10,
                )

                self.assertIsNotNone(result)
                self.assertEqual(result.status, SolveStatus.OPTIMAL)
                self.assertTrue(result.stats.get("serverless"))
                self.assertEqual(len(result.shift_days), 2)
