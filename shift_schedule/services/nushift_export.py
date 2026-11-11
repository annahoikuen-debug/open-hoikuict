"""NuShift 形式 CSV エクスポートサービス。

NuShift (shiftai.data_loader) の列定義に完全準拠した CSV データを生成する:
1. children_csv_rows (園児登降園計画)
2. staff_csv_rows (職員マスタ)
3. preferences_csv_rows (希望休・有給)
"""

from __future__ import annotations

import csv
import io
from datetime import date
from sqlmodel import Session, select

from models import (
    AttendanceRecord,
    AttendanceVerification,
    ChildCareCertification,
    StaffPaidLeaveRequest,
    User,
)
from shift_schedule.bridge import active_children, build_child_plan
from shift_schedule.db_models import (
    ChildPlannedArrivalDefaults,
    StaffContracts,
    StaffQualifications,
    StaffShiftUnavailability,
)

CHILDREN_HEADERS: list[str] = [
    "園児ID",
    "氏名",
    "年齢",
    "登園日",
    "登園時刻",
    "降園時刻",
    "短時間保育",
    "欠席",
    "欠席理由",
    "早朝保育",
    "延長保育",
    "備考",
]

STAFF_HEADERS: list[str] = [
    "職員ID",
    "氏名",
    "資格（主）",
    "資格（副）",
    "雇用形態",
    "週契約時間",
    "1日契約時間",
    "月間最小時間",
    "月間最大時間",
    "週最大出勤日数",
    "最大連続勤務日数",
    "最早始業",
    "最遅終業",
    "能力タグ",
    "36協定",
    "変形労働制",
    "備考",
]

PREFERENCES_HEADERS: list[str] = [
    "職員ID",
    "種別",
    "日付",
    "開始",
    "終了",
    "理由",
]


def children_csv_string(session: Session, start_date: date, end_date: date) -> str:
    """園児登降園計画 CSV 文字列（BOM付き UTF-8）を生成。"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(CHILDREN_HEADERS)

    # 期間内の全日付を生成
    from datetime import timedelta
    current = start_date
    all_days: list[date] = []
    while current <= end_date:
        all_days.append(current)
        current += timedelta(days=1)

    for day in all_days:
        kids = active_children(session, day)
        for child in kids:
            rec = session.exec(
                select(AttendanceRecord).where(
                    AttendanceRecord.child_id == child.id,
                    AttendanceRecord.attendance_date == day,
                )
            ).first()
            p_def = session.exec(
                select(ChildPlannedArrivalDefaults).where(
                    ChildPlannedArrivalDefaults.child_id == child.id,
                    (ChildPlannedArrivalDefaults.effective_to.is_(None))
                    | (ChildPlannedArrivalDefaults.effective_to >= day),
                    ChildPlannedArrivalDefaults.effective_from <= day,
                )
            ).first()
            cert = session.exec(
                select(ChildCareCertification).where(
                    ChildCareCertification.child_id == child.id,
                    ChildCareCertification.is_active == True,  # noqa: E712
                    ChildCareCertification.effective_from <= day,
                    (ChildCareCertification.effective_to.is_(None))
                    | (ChildCareCertification.effective_to >= day),
                )
            ).first()
            verif = session.exec(
                select(AttendanceVerification).where(
                    AttendanceVerification.child_id == child.id,
                    AttendanceVerification.target_date == day,
                )
            ).first()

            cp = build_child_plan(
                session,
                child,
                day,
                attendance_record=rec,
                planned_arrival_default=p_def,
                certification=cert,
                verification=verif,
            )
            if cp is None:
                continue

            # 年齢数値
            age_years = (day - child.birth_date).days // 365

            writer.writerow([
                cp.child_id,
                cp.name,
                str(age_years),
                day.isoformat(),
                cp.arrive.strftime("%H:%M") if cp.arrive else "08:00",
                cp.depart.strftime("%H:%M") if cp.depart else "18:00",
                "true" if cp.is_short_time else "false",
                "true" if cp.absent else "false",
                getattr(verif, "status", "") or "",
                "false",
                "false",
                "",
            ])

    return "\ufeff" + output.getvalue()


def staff_csv_string(session: Session) -> str:
    """職員マスタ CSV 文字列（BOM付き UTF-8）を生成。"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(STAFF_HEADERS)

    today = date.today()
    users = session.exec(
        select(User).where(User.is_active == True).order_by(User.staff_sort_order, User.display_name)  # noqa: E712
    ).all()

    for u in users:
        u_hex = u.id.hex if hasattr(u.id, "hex") else str(u.id)
        u_str = str(u.id)
        uids = [u_hex, u_str]

        quals = session.exec(
            select(StaffQualifications).where(
                StaffQualifications.staff_user_id.in_(uids),
                (StaffQualifications.effective_to.is_(None)) | (StaffQualifications.effective_to >= today),
            )
        ).all()
        contract = session.exec(
            select(StaffContracts).where(
                StaffContracts.staff_user_id.in_(uids),
                (StaffContracts.effective_to.is_(None)) | (StaffContracts.effective_to >= today),
            ).order_by(StaffContracts.effective_from.desc(), StaffContracts.id.desc())
        ).first()

        main_role = quals[0].role if quals else ""
        sub_role = quals[1].role if len(quals) > 1 else ""

        emp_type = contract.employment_type if contract else "正職員"
        weekly_h = str(contract.weekly_hours) if contract and contract.weekly_hours else "40.0"
        daily_h = str(contract.daily_hours) if contract and contract.daily_hours else "8.0"
        min_m_h = str(contract.min_monthly_hours) if contract and contract.min_monthly_hours else ""
        max_m_h = str(contract.max_monthly_hours) if contract and contract.max_monthly_hours else ""
        max_w_d = str(contract.max_weekly_days) if contract and contract.max_weekly_days else ""
        max_c_d = str(contract.max_consecutive_days) if contract and contract.max_consecutive_days else ""
        earliest = contract.earliest_start if contract and contract.earliest_start else "07:00"
        latest = contract.latest_end if contract and contract.latest_end else "19:00"
        has_36 = "true" if (contract is None or contract.has_36_agreement) else "false"
        variable = "true" if (contract and contract.variable_working_hours) else "false"

        writer.writerow([
            u_hex,
            u.display_name or u.email,
            main_role,
            sub_role,
            emp_type,
            weekly_h,
            daily_h,
            min_m_h,
            max_m_h,
            max_w_d,
            max_c_d,
            earliest,
            latest,
            "",
            has_36,
            variable,
            "",
        ])

    return "\ufeff" + output.getvalue()


def preferences_csv_string(session: Session, start_date: date, end_date: date) -> str:
    """希望休・有給 CSV 文字列（BOM付き UTF-8）を生成。"""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(PREFERENCES_HEADERS)

    # 1. 承認済み希望休
    unavails = session.exec(
        select(StaffShiftUnavailability).where(
            StaffShiftUnavailability.target_date >= start_date,
            StaffShiftUnavailability.target_date <= end_date,
            StaffShiftUnavailability.status == "approved",
        )
    ).all()
    for un in unavails:
        writer.writerow([
            un.staff_user_id,
            "出勤不可" if (not un.start_time and not un.end_time) else "希望休",
            un.target_date.isoformat(),
            un.start_time or "",
            un.end_time or "",
            un.reason or "",
        ])

    # 2. 承認済み有給
    paid_leaves = session.exec(
        select(StaffPaidLeaveRequest).where(
            StaffPaidLeaveRequest.target_date >= start_date,
            StaffPaidLeaveRequest.target_date <= end_date,
            StaffPaidLeaveRequest.status == "APPROVED",
        )
    ).all()
    for pl in paid_leaves:
        uid_hex = pl.staff_user_id.hex if hasattr(pl.staff_user_id, "hex") else str(pl.staff_user_id)
        writer.writerow([
            uid_hex,
            "出勤不可",
            pl.target_date.isoformat(),
            "",
            "",
            pl.reason or "有給休暇",
        ])

    return "\ufeff" + output.getvalue()

