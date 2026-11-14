"""CI ベンチマーク回帰ゲートテスト (改善案 8: Planner Benchmark Regression Gate).

制約改修やソルバー設定変更による求解性能・実行可能性の劣化を検知し、
基準を満たさない PR を CI で自動遮断する回帰防止ゲート。
"""

import time
import pytest
from tools.benchmark.run_shift_benchmark import create_benchmark_dataset
from vendor.nushift.shiftai.domain import SolveStatus
from vendor.nushift.shiftai.monthly import solve_monthly_hierarchical
from vendor.nushift.shiftai.solver import is_highs_available


def test_standard_7days_regression_gate():
    """標準7日間シフト求解の性能・実行可能性回帰ゲート。

    - 求解所要時間: 15秒以内 (Performance Gate)
    - 求解ステータス: OPTIMAL または FEASIBLE (Feasibility Gate)
    - 生成日数: 7日間完全生成
    - カバレッジ充足率: 90% 以上 (Quality Gate)
    - Hard/Soft スコア算出: 正常に計算されていること
    """
    ctx = create_benchmark_dataset("standard_7days")
    solver_name = "HiGHS" if is_highs_available() else "PULP_CBC_CMD"

    start_time = time.perf_counter()
    res = solve_monthly_hierarchical(
        context=ctx,
        time_limit_sec=20,
        solver_name=solver_name,
        parallel_workers=2,  # Stage 2 並列探索
    )
    elapsed = time.perf_counter() - start_time

    # 1. 求解ステータスの検証
    assert res.status in (SolveStatus.OPTIMAL, SolveStatus.FEASIBLE), (
        f"ステータスが実行可能解を満たしていません: {res.status}"
    )

    # 2. 全日数の生成確認
    assert len(res.shift_days) == 7, (
        f"7日分すべて生成されていません: 生成日数 {len(res.shift_days)}"
    )

    # 3. カバレッジ充足率の検証（Quality Gate: >= 90%）
    total_needed = sum(
        ctx.requirements.needed_staff(sd.day, s)
        for sd in res.shift_days
        for s in ctx.requirements.slots
    )
    total_assigned = sum(
        1
        for sd in res.shift_days
        for a in sd.assignments.values()
        for s in ctx.requirements.slots
        if a.get(s.label) and getattr(a.get(s.label), "name", str(a.get(s.label))) == "WORK"
    )
    coverage_rate = min(total_assigned / max(total_needed, 1), 1.0) * 100.0
    assert coverage_rate >= 90.0, (
        f"カバレッジ充足率 ({coverage_rate:.1f}%) が基準値 90.0% 未満です"
    )

    # 4. スコアモデルの検証
    assert res.score is not None, "ShiftScore が算出されていません"
    assert isinstance(res.score.hard_score, int)
    assert isinstance(res.score.soft_score, float)
    assert len(res.score.matches) > 0, "スコア説明 (matches) が空です"

    # 5. 所要時間の検証（回帰防止閾値: 15.0秒）
    assert elapsed <= 15.0, (
        f"求解所要時間 ({elapsed:.2f}s) が回帰防止閾値 15.0s を超過しました"
    )
