"""Timefold 思想に基づく Planner Benchmark 自動実行フレームワーク。

ソルバー（HiGHS / CBC）× タイムリミット × データセット規模のマトリクス測定を行い、
求解所要時間、ハード違反数、ソフトスコア、カバレッジ充足率を JSON / Markdown レポート化する。
"""

from __future__ import annotations

import argparse
import datetime as dt
from datetime import date, time
import json
import os
import sys
import time as time_mod
from pathlib import Path
from typing import Any

from vendor.nushift.shiftai import local_rules
from vendor.nushift.shiftai.domain import (
    AgeClass,
    ChildPlan,
    Contract,
    EmploymentType,
    FacilitySettings,
    Role,
    SolveResult,
    SolveStatus,
    StaffMember,
)
from vendor.nushift.shiftai.monthly import MonthlySolveContext, solve_monthly_hierarchical
from vendor.nushift.shiftai.shift_patterns import ShiftPattern
from vendor.nushift.shiftai.solver import is_highs_available
from vendor.nushift.shiftai.standards import build_requirements


def create_benchmark_dataset(dataset_name: str = "standard_7days") -> MonthlySolveContext:
    """ベンチマーク用の標準データセットを生成する。"""
    if dataset_name == "small_3days":
        days_count = 3
        staff_sei = 2
        staff_part = 2
        child_count = 5
    else:  # standard_7days
        days_count = 7
        staff_sei = 4
        staff_part = 4
        child_count = 10

    days = [date(2026, 11, d) for d in range(2, 2 + days_count)]  # 11/2(月)開始

    staff = []
    contracts = {}
    for i in range(1, staff_sei + 1):
        sid = f"staff_sei_{i:02d}"
        c = Contract(
            weekly_hours=40.0,
            daily_hours=8.0,
            employment_type=EmploymentType.SEI,
            max_consecutive_days=5,
        )
        s = StaffMember(
            staff_id=sid,
            name=f"常勤保育士_{i}",
            roles=(Role.HOIKUSHI,),
            contract=c,
        )
        staff.append(s)
        contracts[sid] = c

    for i in range(1, staff_part + 1):
        sid = f"staff_part_{i:02d}"
        c = Contract(
            weekly_hours=20.0,
            daily_hours=4.0,
            employment_type=EmploymentType.PART,
            max_consecutive_days=4,
        )
        s = StaffMember(
            staff_id=sid,
            name=f"パート保育士_{i}",
            roles=(Role.HOIKUSHI,),
            contract=c,
        )
        staff.append(s)
        contracts[sid] = c

    children = []
    for d in days:
        if d.weekday() < 5:
            for cid in range(1, child_count + 1):
                children.append(
                    ChildPlan(
                        child_id=f"c_{cid:03d}",
                        name=f"園児_{cid}",
                        day=d,
                        age_class=AgeClass.AGE_1,
                        arrive=time(8, 30),
                        depart=time(16, 30),
                    )
                )

    patterns = [
        ShiftPattern(key="EARLY", label="早番", start=time(7, 30), end=time(16, 30)),
        ShiftPattern(key="NORMAL", label="日勤", start=time(8, 30), end=time(17, 30)),
        ShiftPattern(key="LATE", label="遅番", start=time(9, 30), end=time(18, 30)),
        ShiftPattern(key="HALF", label="半日", start=time(8, 30), end=time(12, 30)),
    ]

    settings = FacilitySettings()
    standard = local_rules.get_standard(local_rules.DEFAULT_PRESET_KEY)
    req_table = build_requirements(
        children=children,
        days=days,
        standard=standard,
        day_open=time(7, 30),
        day_close=time(18, 30),
    )

    return MonthlySolveContext(
        target_month="2026-11",
        all_days=days,
        staff=staff,
        contracts=contracts,
        preferences={},
        patterns=patterns,
        requirements=req_table,
        facility_settings=settings,
        fixed_assignments={},
        prior_duty_history={},
        monthly_holiday_target=2 if days_count == 7 else 1,
        children=children,
        standard=standard,
    )


def run_benchmark_matrix(
    datasets: list[str] | None = None,
    solvers: list[str] | None = None,
    time_limits: list[int] | None = None,
    parallel_workers: list[int] | None = None,
) -> list[dict[str, Any]]:
    """マトリクス設定でベンチマークを一括実行する。"""
    datasets = datasets or ["standard_7days"]
    solvers = solvers or (["HiGHS"] if is_highs_available() else ["PULP_CBC_CMD"])
    time_limits = time_limits or [15]
    parallel_workers = parallel_workers or [1, 2]

    results = []

    for d_name in datasets:
        ctx = create_benchmark_dataset(d_name)
        for s_name in solvers:
            for t_lim in time_limits:
                for pw in parallel_workers:
                    print(f"Running Benchmark: dataset={d_name}, solver={s_name}, time_limit={t_lim}s, workers={pw}...")
                    start_t = time_mod.perf_counter()
                    res = solve_monthly_hierarchical(
                        context=ctx,
                        time_limit_sec=t_lim,
                        solver_name=s_name,
                        parallel_workers=pw,
                    )
                    elapsed = time_mod.perf_counter() - start_t

                    hard_score = res.score.hard_score if res.score else 0
                    soft_score = res.score.soft_score if res.score else 0.0
                    blockers = sum(1 for v in res.violations if v.severity.value == "BLOCKER")

                    row = {
                        "dataset": d_name,
                        "solver": s_name,
                        "time_limit_sec": t_lim,
                        "parallel_workers": pw,
                        "status": res.status.value,
                        "elapsed_sec": round(elapsed, 2),
                        "hard_score": hard_score,
                        "soft_score": round(soft_score, 1),
                        "blocker_count": blockers,
                        "violations_count": len(res.violations),
                        "days_solved": len(res.shift_days),
                    }
                    results.append(row)
                    print(f" -> Completed in {elapsed:.2f}s, status={res.status.value}, Hard={hard_score}, Soft={soft_score:.1f}")

    return results


def format_markdown_report(results: list[dict[str, Any]]) -> str:
    """ベンチマーク結果を GitHub Flavored Markdown 表形式に整形する。"""
    lines = [
        "# Shift Solver Benchmark Report (Timefold-inspired Matrix)",
        "",
        f"*Generated at: {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*",
        "",
        "| Dataset | Solver | Time Limit | Workers | Status | Elapsed (s) | Hard Score | Soft Score | Blockers |",
        "|---|---|---:|---:|---|---:|---:|---:|---:|",
    ]
    for r in results:
        lines.append(
            f"| `{r['dataset']}` | `{r['solver']}` | {r['time_limit_sec']}s | {r['parallel_workers']} | "
            f"**{r['status']}** | {r['elapsed_sec']:.2f}s | {r['hard_score']} | {r['soft_score']} | {r['blocker_count']} |"
        )
    lines.append("")
    return "\n".join(lines)


def main():
    default_out = Path(__file__).resolve().parent.parent.parent / "benchmark_reports"
    parser = argparse.ArgumentParser(description="Run Shift Solver Benchmark")
    parser.add_argument("--output-dir", default=str(default_out), help="Directory to save report")
    parser.add_argument("--dataset", default="standard_7days", help="Dataset name")
    args = parser.parse_args()

    results = run_benchmark_matrix(datasets=[args.dataset])
    md_report = format_markdown_report(results)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_file = out_dir / "latest_benchmark.md"
    json_file = out_dir / "latest_benchmark.json"

    report_file.write_text(md_report, encoding="utf-8")
    json_file.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReport written to {report_file}")


if __name__ == "__main__":
    main()
