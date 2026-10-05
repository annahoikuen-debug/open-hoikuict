"""Smoke tests for the vendored shiftai core.

Guards the vendoring contract: importing shiftai must work from `vendor/nushift`
without installing it and without streamlit, and the pieces `shift_schedule`
depends on must keep their public shape.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

VENDOR_ROOT = Path(__file__).resolve().parent / "vendor" / "nushift"
PACKAGE_DIR = VENDOR_ROOT / "shiftai"


def _ensure_on_path() -> None:
    path = str(VENDOR_ROOT)
    if path not in sys.path:
        sys.path.insert(0, path)


def test_vendor_tree_present() -> None:
    assert PACKAGE_DIR.is_dir(), f"vendored package missing: {PACKAGE_DIR}"
    assert (PACKAGE_DIR / "domain.py").is_file()
    assert (PACKAGE_DIR / "solver.py").is_file()
    assert (PACKAGE_DIR / "standards.py").is_file()
    assert (PACKAGE_DIR / "local_rules.py").is_file()
    assert (PACKAGE_DIR / "gap_analysis.py").is_file()
    assert (VENDOR_ROOT / "README.md").is_file(), "provenance README is required"


def test_provenance_is_recorded() -> None:
    readme = (VENDOR_ROOT / "README.md").read_text(encoding="utf-8")
    assert "annahoikuen-debug/nushift" in readme
    assert "c5c86f3" in readme


def test_import_works_without_install_and_without_streamlit() -> None:
    """The whole point of vendoring: no pip install, no streamlit dependency."""
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(VENDOR_ROOT)!r});"
        "import shiftai;"
        "from shiftai import domain, standards, local_rules, solver, gap_analysis, config;"
        "assert 'streamlit' not in sys.modules, 'shiftai core must not import streamlit';"
        "print(shiftai.__version__)"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip()


def test_core_exposes_what_shift_schedule_needs() -> None:
    _ensure_on_path()
    from shiftai import config, domain, gap_analysis, local_rules, solver, standards

    # domain: the frozen dataclasses the bridge writes into
    for name in ("ChildPlan", "StaffMember", "Contract", "FacilitySettings",
                 "StaffPreferences", "Unavailability", "AgeClass", "Role",
                 "EmploymentType"):
        assert hasattr(domain, name), f"domain.{name} missing"

    # standards / local_rules: requirement + staffing-standard construction
    assert callable(standards.build_requirements)
    assert callable(local_rules.build_standard)
    assert len(local_rules.MUNICIPAL_PRESETS) >= 14, "expected the 14 documented presets"

    # solver + gap_analysis: the solve entry point and the violation checks
    assert callable(solver.solve_shift)
    assert callable(solver.supply_hours)
    assert callable(solver.shortfall_rows)
    assert callable(gap_analysis.check_violations)
    assert callable(gap_analysis.analyze_gap)

    # config: the daily thresholds the approval gate depends on (proposal 2.13)
    assert config.STATUTORY_MAX_DAILY_WORK_HOURS == 10.0
    assert config.STATUTORY_DAILY_LIMIT_HOURS == 8.75


def test_solve_shift_accepts_our_call_shape() -> None:
    """Lock the keyword arguments `shift_schedule.services.solve_jobs` will pass."""
    import inspect

    _ensure_on_path()
    from shiftai import solver

    params = inspect.signature(solver.solve_shift).parameters
    for name in ("time_limit_sec", "settings", "standard", "fixed_assignments",
                 "relaxation", "preferences", "weights"):
        assert name in params, f"solve_shift lost the {name!r} parameter"


def test_unknown_staff_role_still_raises() -> None:
    """A staff member with no qualification must raise, not be silently dropped.

    `shift_schedule` relies on this to report the staff member as an error row.
    """
    from datetime import time

    _ensure_on_path()
    from shiftai.domain import Contract, EmploymentType, StaffMember

    with pytest.raises(ValueError):
        StaffMember(
            staff_id="X-1",
            name="資格なし",
            roles=(),
            contract=Contract(
                weekly_hours=20.0,
                daily_hours=5.0,
                employment_type=EmploymentType.PART,
                earliest_start=time(8, 0),
                latest_end=time(17, 0),
            ),
        )


def test_ui_and_gas_are_present_but_unused() -> None:
    """We keep a faithful copy; exclusions are enforced by import discipline."""
    assert (PACKAGE_DIR / "ui").is_dir(), "faithful copy should keep ui/"
    assert (PACKAGE_DIR / "gas_client.py").is_file()
