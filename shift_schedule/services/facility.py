"""施設シフト設定サービス。

shift_facility_settings / shift_facility_closed_days のCRUD。
"""

from __future__ import annotations

from datetime import date

from ..db_models import ShiftFacilityClosedDays, ShiftFacilitySettings
from ..store import ShiftRepository


def get_or_create_settings(repo: ShiftRepository) -> ShiftFacilitySettings:
    """施設設定を取得。無ければデフォルト値で作成。"""
    settings = repo.facility_settings()
    if settings is None:
        settings = ShiftFacilitySettings()
        repo.save_facility_settings(settings)
    return settings


def update_settings(
    repo: ShiftRepository,
    *,
    day_open: str | None = None,
    day_close: str | None = None,
    granularity_min: int | None = None,
    capacity: int | None = None,
    staffing_standard_key: str | None = None,
    min_two_staff_rule: bool | None = None,
    enforce_min_two: bool | None = None,
) -> ShiftFacilitySettings:
    settings = get_or_create_settings(repo)
    if day_open is not None:
        settings.day_open = day_open
    if day_close is not None:
        settings.day_close = day_close
    if granularity_min is not None:
        settings.granularity_min = granularity_min
    if capacity is not None:
        settings.capacity = capacity
    if staffing_standard_key is not None:
        settings.staffing_standard_key = staffing_standard_key
    if min_two_staff_rule is not None:
        settings.min_two_staff_rule = min_two_staff_rule
    if enforce_min_two is not None:
        settings.enforce_min_two = enforce_min_two
    repo.save_facility_settings(settings)
    return settings


def list_closed_days(repo: ShiftRepository, setting_id: int) -> list[ShiftFacilityClosedDays]:
    from sqlmodel import select

    return repo.session.exec(
        select(ShiftFacilityClosedDays).where(ShiftFacilityClosedDays.setting_id == setting_id)
    ).all()


def add_closed_day(
    repo: ShiftRepository,
    setting_id: int,
    target_date: date,
    kind: str,
) -> ShiftFacilityClosedDays:
    closed_day = ShiftFacilityClosedDays(
        setting_id=setting_id,
        target_date=target_date,
        kind=kind,
    )
    repo.session.add(closed_day)
    repo.session.commit()
    return closed_day
