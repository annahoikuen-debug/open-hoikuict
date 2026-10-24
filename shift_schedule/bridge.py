"""Bridge between open-hoikuict DB rows and shiftai frozen dataclasses.

Maps domain rows (children, attendance_records, users, staff_qualifications,
staff_contracts, etc.) into shiftai ``ChildPlan`` / ``StaffMember`` /
``Contract`` / ``FacilitySettings`` instances for solving.
"""

from __future__ import annotations

from datetime import date, time

from sqlmodel import Session, select

from shiftai.domain import (
    AgeClass,
    ChildPlan,
    Contract,
    EmploymentType,
    FacilitySettings as ShiftaiFacilitySettings,
    Role,
    StaffMember,
    StaffPreferences,
    Unavailability,
)

from models import (
    AttendanceRecord,
    Child,
    User,
)

from .db_models import (
    ChildPlannedArrivalDefaults,
    ShiftFacilitySettings,
    StaffContracts,
    StaffQualifications,
    StaffShiftUnavailability,
)


def age_class_on(target_date: date, birth_date: date | None) -> AgeClass:
    """対象日基準の年齢区分を返す。birth_date が不明なら AgeClass.UNKNOWN。"""
    if birth_date is None:
        return AgeClass.UNKNOWN
    years = target_date.year - birth_date.year
    if (target_date.month, target_date.day) < (birth_date.month, birth_date.day):
        years -= 1
    return AgeClass.from_years(max(years, 0))


def build_child_plan(
    session: Session,
    child: Child,
    target_date: date,
    *,
    attendance_record: AttendanceRecord | None = None,
    planned_arrival_default: ChildPlannedArrivalDefaults | None,
) -> ChildPlan | None:
    """単園児×対象日の ChildPlan を組み立てる。

    登園時刻は 5 段階の優先度で決定（統合提案 2.9.1）：
      1. 実績打刻（今日以前）
      2. 当日の planned_check_in_time 上書き
      3. 園児ごとの既定値
      4. ExtendedCareFeeRule.normal_start_time
      5. 施設 day_open

    解析不能（depart <= arrive）なら None を返し、呼び出し側でエラー行として扱う。
    """
    # arrive（登園時刻）
    arrive: time | None = None
    if attendance_record is not None and attendance_record.check_in_at is not None:
        arrive = attendance_record.check_in_at.time()
    elif attendance_record is not None and attendance_record.planned_check_in_time:
        arrive = time.fromisoformat(attendance_record.planned_check_in_time)
    elif planned_arrival_default is not None:
        arrive = time.fromisoformat(planned_arrival_default.planned_check_in_time)
    else:
        arrive = time(8, 0)

    # depart（降園時刻）
    depart: time | None = None
    if attendance_record is not None and attendance_record.planned_pickup_time:
        depart = time.fromisoformat(attendance_record.planned_pickup_time)
    else:
        depart = time(18, 0)

    if depart is not None and arrive is not None and depart <= arrive:
        return None  # 園児単位でエラー行として収集

    # is_short_time（短時間保育）
    is_short_time = bool(child.care_time_category == "short")

    # absent（未登園予定）
    absent = bool(attendance_record is not None and attendance_record.is_absent)

    return ChildPlan(
        child_id=str(child.id),
        name=child.full_name,
        day=target_date,
        age_class=age_class_on(target_date, child.birth_date),
        arrive=arrive,
        depart=depart,
        is_short_time=is_short_time,
        absent=absent,
        uses_early_care=arrive is not None and arrive < time(8, 30),
        uses_late_care=depart is not None and depart > time(17, 0),
        notes=attendance_record.note if attendance_record else None,
    )


def build_staff_preferences(
    session: Session,
    user: User,
) -> StaffPreferences:
    """職員の希望休・承認済み有給休暇から StaffPreferences を構築。"""
    uid_hex = user.id.hex if hasattr(user.id, "hex") else str(user.id)
    uid_str = str(user.id)
    uids = list({uid_hex, uid_str})

    unavailabilities = list(
        session.exec(
            select(StaffShiftUnavailability).where(
                StaffShiftUnavailability.staff_user_id.in_(uids),
                StaffShiftUnavailability.target_date >= date.today(),
            )
        ).all()
    )

    # 有給承認データを希望休として自動統合
    from models import StaffPaidLeaveRequest
    approved_paid_leaves = session.exec(
        select(StaffPaidLeaveRequest).where(
            StaffPaidLeaveRequest.staff_user_id == user.id,
            StaffPaidLeaveRequest.status == "APPROVED",
        )
    ).all()

    unavail_list = [
        Unavailability(
            day=u.target_date,
            start=time.fromisoformat(u.start_time) if u.start_time else time(0, 0),
            end=time.fromisoformat(u.end_time) if u.end_time else time(23, 59),
            reason=u.reason or "",
        )
        for u in unavailabilities
    ]
    for pl in approved_paid_leaves:
        unavail_list.append(
            Unavailability(
                day=pl.target_date,
                reason=pl.reason or "有給休暇",
            )
        )

    return StaffPreferences(unavailable=unavail_list)


def build_staff_member(
    session: Session,
    user: User,
) -> StaffMember | None:
    uid_hex = user.id.hex if hasattr(user.id, "hex") else str(user.id)
    uid_str = str(user.id)
    uids = list({uid_hex, uid_str})

    qualifications = session.exec(
        select(StaffQualifications).where(
            StaffQualifications.staff_user_id.in_(uids),
            (StaffQualifications.effective_to.is_(None))
            | (StaffQualifications.effective_to >= date.today()),
        )
    ).all()
    if not qualifications:
        return None

    roles = tuple(Role(q.role) for q in qualifications)

    contract = session.exec(
        select(StaffContracts).where(
            StaffContracts.staff_user_id.in_(uids),
            (StaffContracts.effective_to.is_(None))
            | (StaffContracts.effective_to >= date.today()),
        )
    ).first()
    if contract is None:
        return None

    return StaffMember(
        staff_id=str(user.id),
        name=user.display_name,
        roles=roles,
        contract=Contract(
            weekly_hours=contract.weekly_hours or 40.0,
            daily_hours=contract.daily_hours or 8.0,
            employment_type=EmploymentType(contract.employment_type),
            earliest_start=time.fromisoformat(contract.earliest_start) if contract.earliest_start else time(9, 0),
            latest_end=time.fromisoformat(contract.latest_end) if contract.latest_end else time(18, 0),
        ),
        skills=frozenset(),
    )


def build_facility_settings(
    settings: ShiftFacilitySettings | None,
) -> ShiftaiFacilitySettings | None:
    """DB 行から shiftai FacilitySettings を構築。"""
    if settings is None:
        return None
    return ShiftaiFacilitySettings(
        day_open=settings.day_open,
        day_close=settings.day_close,
        granularity_min=settings.granularity_min,
        capacity=settings.capacity,
        staffing_standard_key=settings.staffing_standard_key,
        min_two_staff_rule=settings.min_two_staff_rule,
    )
