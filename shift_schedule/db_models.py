"""Shift schedule database models.

Defines SQLModel tables for the staff shift auto-generation feature.
Tables are created by ``SQLModel.metadata.create_all()`` in
``database.create_db_and_tables()``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlmodel import Field, SQLModel

from time_utils import utc_now


class ShiftFacilitySettings(SQLModel, table=True):
    """施設シフト設定（id=1 の単一行）。開園/閉園・粒度・定員・配置基準等。"""

    __tablename__ = "shift_facility_settings"

    id: Optional[int] = Field(default=1, primary_key=True)
    day_open: str = Field(default="07:30", max_length=5)  # "HH:MM"
    day_close: str = Field(default="19:30", max_length=5)  # "HH:MM"
    granularity_min: int = Field(default=30)  # 分単位
    capacity: int = Field(default=60)  # 定員
    staffing_standard_key: str = Field(default="fukuoka_city", max_length=64)
    min_two_staff_rule: bool = Field(default=True)
    enforce_min_two: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=utc_now)


class ShiftFacilityClosedDays(SQLModel, table=True):
    """休園日・祝日。"""

    __tablename__ = "shift_facility_closed_days"

    id: Optional[int] = Field(default=None, primary_key=True)
    setting_id: int = Field(foreign_key="shift_facility_settings.id", index=True)
    target_date: date = Field(index=True)
    kind: str = Field(max_length=16)  # "closed" / "holiday"


class StaffQualifications(SQLModel, table=True):
    """職員資格。有効期間付き。"""

    __tablename__ = "staff_qualifications"

    id: Optional[int] = Field(default=None, primary_key=True)
    staff_user_id: int = Field(foreign_key="users.id", index=True)
    role: str = Field(max_length=32)  # 保育士 / 支援員 / 看護師 / 調理員 等
    effective_from: date = Field(index=True)
    effective_to: Optional[date] = Field(default=None, index=True)
    note: Optional[str] = Field(default=None, max_length=255)


class StaffContracts(SQLModel, table=True):
    """職員雇用契約。有効期間付き。"""

    __tablename__ = "staff_contracts"

    id: Optional[int] = Field(default=None, primary_key=True)
    staff_user_id: int = Field(foreign_key="users.id", index=True)
    employment_type: str = Field(max_length=32)  # full_time / part_time 等
    weekly_hours: Optional[float] = Field(default=None)
    daily_hours: Optional[float] = Field(default=None)
    min_monthly_hours: Optional[float] = Field(default=None)
    max_monthly_hours: Optional[float] = Field(default=None)
    max_weekly_days: Optional[int] = Field(default=None)
    max_consecutive_days: Optional[int] = Field(default=None)
    earliest_start: Optional[str] = Field(default=None, max_length=5)  # "HH:MM"
    latest_end: Optional[str] = Field(default=None, max_length=5)  # "HH:MM"
    can_work_holiday: bool = Field(default=False)
    overtime_allowed: bool = Field(default=False)
    effective_from: date = Field(index=True)
    effective_to: Optional[date] = Field(default=None, index=True)


class StaffShiftPreferences(SQLModel, table=True):
    """職員シフト希望（早番避け・遅番避け等）。"""

    __tablename__ = "staff_shift_preferences"

    id: Optional[int] = Field(default=None, primary_key=True)
    staff_user_id: int = Field(foreign_key="users.id", index=True)
    avoid_early: bool = Field(default=False)
    avoid_late: bool = Field(default=False)
    max_early_shifts: Optional[int] = Field(default=None)
    max_late_shifts: Optional[int] = Field(default=None)
    notes: Optional[str] = Field(default=None, max_length=255)


class StaffShiftUnavailability(SQLModel, table=True):
    """職員不在希望（希望休・出勤不可等）。"""

    __tablename__ = "staff_shift_unavailability"

    id: Optional[int] = Field(default=None, primary_key=True)
    staff_user_id: int = Field(foreign_key="users.id", index=True)
    target_date: date = Field(index=True)
    start_time: Optional[str] = Field(default=None, max_length=5)
    end_time: Optional[str] = Field(default=None, max_length=5)
    kind: str = Field(max_length=16)  # 希望休 / 出勤不可 / 出勤希望 / 休み希望
    reason: Optional[str] = Field(default=None, max_length=255)


class ChildPlannedArrivalDefaults(SQLModel, table=True):
    """園児ごとの既定登園予定時刻。"""

    __tablename__ = "child_planned_arrival_defaults"

    child_id: int = Field(foreign_key="children.id", index=True, primary_key=True)
    planned_check_in_time: str = Field(max_length=5)  # "HH:MM"
    effective_from: date = Field(index=True)
    effective_to: Optional[date] = Field(default=None, index=True)
    updated_by_user_id: Optional[int] = Field(default=None, index=True)
    updated_by_name: Optional[str] = Field(default=None, max_length=100)
    updated_at: datetime = Field(default_factory=utc_now)


class ShiftPlans(SQLModel, table=True):
    """シフトプランヘッド。対象月単位。"""

    __tablename__ = "shift_plans"

    id: Optional[int] = Field(default=None, primary_key=True)
    target_month: str = Field(max_length=7, index=True)  # "YYYY-MM"
    status: str = Field(default="draft", max_length=16)  # draft/generated/approved/archived
    staffing_standard_key: str = Field(default="fukuoka_city", max_length=64)
    lock_version: int = Field(default=1)
    input_fingerprint: Optional[str] = Field(default=None, max_length=64)
    created_by_user_id: Optional[int] = Field(default=None, index=True)
    created_by_name: Optional[str] = Field(default=None, max_length=100)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class ShiftPlanCells(SQLModel, table=True):
    """シフトプランセル。職員×日付×スロット。"""

    __tablename__ = "shift_plan_cells"

    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="shift_plans.id", index=True)
    staff_user_id: int = Field(foreign_key="users.id", index=True)
    target_date: date = Field(index=True)
    slot_label: str = Field(max_length=32)
    cell_state: str = Field(default="unspecified", max_length=32)  # specified / pinned / unspecified
    pinned_by_user_id: Optional[int] = Field(default=None, index=True)


class ShiftSolveJobs(SQLModel, table=True):
    """ソルバ実行ジョブ。CBC はバックグラウンドワーカーで実行。"""

    __tablename__ = "shift_solve_jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="shift_plans.id", index=True)
    status: str = Field(default="queued", max_length=16)  # queued/running/succeeded/failed/cancelled
    requested_by_user_id: Optional[int] = Field(default=None, index=True)
    requested_at: datetime = Field(default_factory=utc_now)
    started_at: Optional[datetime] = Field(default=None)
    finished_at: Optional[datetime] = Field(default=None)
    time_limit_sec: int = Field(default=30)
    relax_level: int = Field(default=0)
    is_approved_snapshot: bool = Field(default=False)
    stats: Optional[str] = Field(default=None, max_length=4096)  # JSON
    error_message: Optional[str] = Field(default=None, max_length=1024)


class ShiftViolations(SQLModel, table=True):
    """ソルバ違反検出結果。追記専用。"""

    __tablename__ = "shift_violations"

    id: Optional[int] = Field(default=None, primary_key=True)
    plan_id: int = Field(foreign_key="shift_plans.id", index=True)
    job_id: Optional[int] = Field(default=None, index=True)
    code: str = Field(max_length=32, index=True)  # 21種の違反コード
    severity: str = Field(max_length=16)  # BLOCKER / WARNING / INFO
    target_date: Optional[date] = Field(default=None, index=True)
    slot_label: Optional[str] = Field(default=None, max_length=32)
    staff_user_id: Optional[int] = Field(default=None, index=True)
    message: Optional[str] = Field(default=None, max_length=512)


class ShiftPlanningAudits(SQLModel, table=True):
    """シフト操作監査ログ。追記専用。"""

    __tablename__ = "shift_planning_audits"

    id: Optional[int] = Field(default=None, primary_key=True)
    actor_user_id: Optional[int] = Field(default=None, index=True)
    target_plan_id: Optional[int] = Field(default=None, index=True)
    action: str = Field(max_length=32)
    summary: Optional[str] = Field(default=None, max_length=512)
    audit_metadata: Optional[str] = Field(default=None, max_length=2048)  # JSON
    created_at: datetime = Field(default_factory=utc_now)
