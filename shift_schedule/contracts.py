"""Shift schedule domain contracts (StrEnum definitions).

Shared vocabulary between the bridge, services, and routers layers.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """職員資格ロール。"""

    PRESCHOOL_TEACHER = "保育士"
    SUPPORT_STAFF = "支援員"
    NURSE = "看護師"
    COOK = "調理員"
    DIRECTOR = "園長"
    HEAD_TEACHER = "主任"


class EmploymentType(StrEnum):
    """雇用形態。"""

    FULL_TIME = "full_time"
    PART_TIME = "part_time"
    TEMPORARY = "temporary"


class StaffingStandardKey(StrEnum):
    """自治体配置基準キー。"""

    FUKUOKA_CITY = "fukuoka_city"
    OSAKA_CITY = "osaka_city"
    TOKYO = "tokyo"
    GENERIC = "generic"


class SolveJobStatus(StrEnum):
    """ソルバ実行ジョブの状態。"""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ViolationSeverity(StrEnum):
    """違反の重大度。"""

    BLOCKER = "BLOCKER"
    WARNING = "WARNING"
    INFO = "INFO"


class PlanStatus(StrEnum):
    """シフトプランの状態。"""

    DRAFT = "draft"
    GENERATED = "generated"
    APPROVED = "approved"
    ARCHIVED = "archived"
