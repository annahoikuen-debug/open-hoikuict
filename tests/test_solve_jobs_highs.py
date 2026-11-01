from unittest.mock import patch
from shift_schedule.services.solve_jobs import (
    cbc_available,
    get_configured_solver_name,
    solver_available,
)


class TestSolveJobsSolverSelection:
    """求解ワーカーにおけるソルバー選択およびフォールバックのテスト。"""

    def test_solver_available_at_least_one(self):
        """システムに少なくとも1つのソルバーが存在すれば solver_available は True を返す。"""
        assert solver_available() is True
        # 後方互換 API の確認
        assert isinstance(cbc_available(), bool)

    def test_get_configured_solver_name_auto(self, monkeypatch):
        """HOIKUICT_SHIFT_SOLVER=auto の場合、利用可能性に応じたソルバー名が返る。"""
        monkeypatch.setenv("HOIKUICT_SHIFT_SOLVER", "auto")
        solver_name = get_configured_solver_name()
        assert solver_name in ("HiGHS", "PULP_CBC_CMD")

    def test_get_configured_solver_name_explicit_highs(self, monkeypatch):
        """HOIKUICT_SHIFT_SOLVER=highs 指定時の動作。"""
        monkeypatch.setenv("HOIKUICT_SHIFT_SOLVER", "highs")
        with patch("shift_schedule.services.solve_jobs.is_highs_available", return_value=True):
            assert get_configured_solver_name() == "HiGHS"

    def test_get_configured_solver_name_fallback_to_cbc_when_highs_missing(self, monkeypatch):
        """HiGHS が利用不可の場合、CBC にフォールバックする。"""
        monkeypatch.setenv("HOIKUICT_SHIFT_SOLVER", "auto")
        with patch("shift_schedule.services.solve_jobs.is_highs_available", return_value=False):
            with patch("shift_schedule.services.solve_jobs.cbc_available", return_value=True):
                assert get_configured_solver_name() == "PULP_CBC_CMD"

    def test_get_configured_solver_name_explicit_cbc(self, monkeypatch):
        """HOIKUICT_SHIFT_SOLVER=cbc 指定時は CBC を選択する。"""
        monkeypatch.setenv("HOIKUICT_SHIFT_SOLVER", "cbc")
        with patch("shift_schedule.services.solve_jobs.cbc_available", return_value=True):
            assert get_configured_solver_name() == "PULP_CBC_CMD"
