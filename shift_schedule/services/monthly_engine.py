"""月次シフト2段階階層的求解（Hierarchical MILP）エンジン アダプター。

本エンジンのコア最適化ロジックは本家 NuShift（`shiftai.monthly`）に完全統合・統一されています。
本モジュールは open-hoikuict との型互換性・DB セッション連携のための薄いアダプター層を提供します。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from typing import Any

from sqlmodel import Session

from shiftai.domain import Contract, EmploymentType, SolveResult
from shiftai.monthly import (
    MonthlySolveContext as ShiftaiMonthlySolveContext,
    _solve_stage1_daily_patterns as shiftai_solve_stage1,
    solve_monthly_hierarchical as shiftai_solve_monthly,
)


class MonthlySolveContext(ShiftaiMonthlySolveContext):
    """open-hoikuict との互換性のための Context ラッパー。

    `contracts` に `StaffContracts` が渡された場合は自動的に `shiftai.domain.Contract`
    相当のオブジェクトとして扱えるようにラップする（`_normalize_context` 参照）。
    """

    pass


def _to_contract(raw: Any) -> Contract:
    """DB モデル（StaffContracts など）を shiftai の Contract に変換する。"""
    if isinstance(raw, Contract):
        return raw

    emp = getattr(raw, "employment_type", None)
    try:
        emp_type = EmploymentType(emp) if emp else EmploymentType.PART
    except ValueError:
        emp_type = (
            EmploymentType.SEI
            if str(emp) in ("full_time", "常勤", "正職員")
            else EmploymentType.PART
        )

    def _to_time(value: Any, default: dt.time) -> dt.time:
        if value is None:
            return default
        if isinstance(value, str):
            return dt.time.fromisoformat(value)
        return value

    return Contract(
        weekly_hours=float(getattr(raw, "weekly_hours", None) or 40.0),
        daily_hours=float(getattr(raw, "daily_hours", None) or 8.0),
        employment_type=emp_type,
        min_monthly_hours=float(getattr(raw, "min_monthly_hours", None) or 0.0),
        max_monthly_hours=float(getattr(raw, "max_monthly_hours", None) or 200.0),
        max_weekly_days=int(getattr(raw, "max_weekly_days", None) or 5),
        max_consecutive_days=int(getattr(raw, "max_consecutive_days", None) or 5),
        earliest_start=_to_time(getattr(raw, "earliest_start", None), dt.time(9, 0)),
        latest_end=_to_time(getattr(raw, "latest_end", None), dt.time(18, 0)),
        can_work_holiday=bool(getattr(raw, "can_work_holiday", False)),
        overtime_allowed=bool(getattr(raw, "overtime_allowed", False)),
        has_36_agreement=bool(getattr(raw, "has_36_agreement", True)),
        variable_working_hours=bool(getattr(raw, "variable_working_hours", False)),
    )


def _normalize_context(context: Any) -> Any:
    """contracts に shiftai 以外の契約オブジェクトが混在していれば Contract に変換する。"""
    contracts = getattr(context, "contracts", None) or {}
    needs_wrap = any(not isinstance(c, Contract) for c in contracts.values())
    if not needs_wrap:
        return context
    wrapped = {sid: _to_contract(c) for sid, c in contracts.items()}
    return replace(context, contracts=wrapped)


def _solve_stage1_daily_patterns(
    context: Any,
    time_limit_sec: int = 30,
    solver_name: str | None = None,
    weights: Any | None = None,
    messages: list[str] | None = None,
) -> dict[tuple[str, dt.date], str]:
    """Stage 1: 日単位パターン割り当て（shiftai.monthly へ委譲）。"""
    return shiftai_solve_stage1(
        context=_normalize_context(context),
        time_limit_sec=time_limit_sec,
        solver_name=solver_name,
        weights=weights,
        messages=messages,
    )


def solve_monthly_hierarchical(
    session: Session | None,
    context: Any,
    time_limit_sec: int = 120,
    solver_name: str | None = None,
    progress_callback: Any = None,
    cancellation_token: Any = None,
    parallel_workers: int = 1,
    weights: Any | None = None,
) -> SolveResult:
    """2段階階層的アプローチにより月次一括シフトを求解する（shiftai.monthly へ委譲）。"""
    return shiftai_solve_monthly(
        context=_normalize_context(context),
        time_limit_sec=time_limit_sec,
        solver_name=solver_name,
        progress_callback=progress_callback,
        cancellation_token=cancellation_token,
        parallel_workers=parallel_workers,
        weights=weights,
    )
