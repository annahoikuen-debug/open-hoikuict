from datetime import date

from shiftai.compliance import StaffRecord
from shiftai.domain import (
    Contract,
    EmploymentType,
    Role,
    StaffMember,
    SolveResult,
    SolveStatus,
    Violation,
    qualified_count,
)
from shiftai.local_rules import build_standard


def test_fte_calculation_week_40h():
    """週40時間契約の職員の常勤換算(FTE)が 1.0 になること（週40時間÷40時間）。"""
    staff_full = StaffRecord(
        staff_id="s1",
        name="常勤",
        roles=(Role.HOIKUSHI,),
        weekly_hours=40.0,
    )
    assert staff_full.full_time_equivalent() == 1.0

    # 週20時間契約のパート職員の常勤換算(FTE)が 0.5 になること
    staff_part = StaffRecord(
        staff_id="s2",
        name="パート",
        roles=(Role.HOIKUSHI,),
        weekly_hours=20.0,
    )
    assert staff_part.full_time_equivalent() == 0.5


def test_nurse_concurrent_role_deduplication():
    """保育士と看護師を両方持つ兼任職員が 2 人ではなく 1 人として計数されること。"""
    standard = build_standard("全国基準（厚労省）")

    c = Contract(weekly_hours=40.0, daily_hours=8.0, employment_type=EmploymentType.SEI)
    concurrent_staff = StaffMember(
        staff_id="s1",
        name="兼任職員",
        roles=(Role.HOIKUSHI, Role.KANGSHI),
        contract=c,
    )
    # 単独で1人
    assert qualified_count([concurrent_staff], standard) == 1

    # 保育士1名 + 兼任1名 = 計2名（3名にはならない）
    regular_hoikushi = StaffMember(
        staff_id="s2",
        name="専任保育士",
        roles=(Role.HOIKUSHI,),
        contract=c,
    )
    assert qualified_count([concurrent_staff, regular_hoikushi], standard) == 2


def test_solve_result_has_shortfall_property():
    """SolveResult.has_shortfall プロパティがショートフォール違反の有無を正しく検知すること。"""
    # 違反なし
    res_clean = SolveResult(status=SolveStatus.OPTIMAL, violations=())
    assert res_clean.has_shortfall is False

    # 他の軽微な違反あり（SHORTFALLではない）
    v_pref = Violation(
        code="PREFERENCE_UNMET",
        severity="INFO",
        staff_id="s1",
        day=date(2026, 11, 1),
        message="希望休不一致",
    )
    res_pref = SolveResult(status=SolveStatus.OPTIMAL, violations=(v_pref,))
    assert res_pref.has_shortfall is False

    # SHORTFALL 違反あり
    v_shortfall = Violation(
        code="SHORTFALL_QUALIFIED",
        severity="BLOCKER",
        staff_id="s1",
        day=date(2026, 11, 1),
        message="有資格者不足",
    )
    res_shortfall = SolveResult(status=SolveStatus.FEASIBLE, violations=(v_shortfall,))
    assert res_shortfall.has_shortfall is True
