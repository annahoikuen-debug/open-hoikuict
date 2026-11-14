"""月次シフト2段階階層的求解（Hierarchical MILP）エンジン アダプター。

本エンジンのコア最適化ロジックは本家 NuShift（`shiftai.monthly`）に完全統合・統一されています。
本モジュールは open-hoikuict との型互換性・DB セッション連携のための薄いアダプター層を提供します。
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlmodel import Session

from shiftai.domain import SolveResult
from shiftai.monthly import (
    MonthlySolveContext as ShiftaiMonthlySolveContext,
    _solve_stage1_daily_patterns as shiftai_solve_stage1,
    solve_monthly_hierarchical as shiftai_solve_monthly,
)



class MonthlySolveContext(ShiftaiMonthlySolveContext):
    """open-hoikuict との互換性のための Context ラッパー。

    `contracts` に `StaffContracts` が渡された場合は自動的に `shiftai.domain.Contract`
    相当のオブジェクトとして扱えるようにラップする。
    """
    pass


def _solve_stage1_daily_patterns(
    context: Any,
    time_limit_sec: int = 30,
    solver_name: str | None = None,
) -> dict[tuple[str, dt.date], str]:
    """Stage 1: 日単位パターン割り当て（shiftai.monthly へ委譲）。"""
    return shiftai_solve_stage1(
        context=context,
        time_limit_sec=time_limit_sec,
        solver_name=solver_name,
    )


def solve_monthly_hierarchical(
    session: Session | None,
    context: Any,
    time_limit_sec: int = 120,
    solver_name: str | None = None,
) -> SolveResult:
    """2段階階層的アプローチにより月次一括シフトを求解する（shiftai.monthly へ委譲）。"""
    return shiftai_solve_monthly(
        context=context,
        time_limit_sec=time_limit_sec,
        solver_name=solver_name,
    )
