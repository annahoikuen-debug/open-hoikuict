from datetime import date, time
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool
import pytest

from models import (
    CareTimeCategory,
    Child,
    ChildCareCertification,
    ChildSex,
    ChildStatus,
)
from shift_schedule.bridge import build_child_plan


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def test_build_child_plan_short_time_certification(session: Session):
    child = Child(
        id=1,
        last_name="園児",
        first_name="太郎",
        last_name_kana="エンジ",
        first_name_kana="タロウ",
        birth_date=date(2021, 5, 1),
        sex=ChildSex.male,
        enrollment_date=date(2024, 4, 1),
        status=ChildStatus.enrolled,
    )
    session.add(child)
    session.commit()
    session.refresh(child)

    cert_short = ChildCareCertification(
        child_id=child.id,
        care_time_category=CareTimeCategory.short,
        effective_from=date(2024, 4, 1),
        effective_to=None,
        is_active=True,
    )
    session.add(cert_short)
    session.commit()
    session.refresh(cert_short)

    target_date = date(2024, 5, 1)

    # certification を渡す
    plan_short = build_child_plan(
        session,
        child,
        target_date,
        planned_arrival_default=None,
        certification=cert_short,
    )
    assert plan_short is not None
    assert plan_short.is_short_time is True

    # 認定なしの場合
    plan_standard = build_child_plan(
        session,
        child,
        target_date,
        planned_arrival_default=None,
        certification=None,
    )
    assert plan_standard is not None
    assert plan_standard.is_short_time is False


def test_build_child_plan_absent_verification(session: Session):
    from models import AttendanceVerification, AttendanceVerificationStatus

    child = Child(
        id=2,
        last_name="欠席",
        first_name="花子",
        last_name_kana="ケッセキ",
        first_name_kana="ハナコ",
        birth_date=date(2021, 6, 1),
        sex=ChildSex.female,
        enrollment_date=date(2024, 4, 1),
        status=ChildStatus.enrolled,
    )
    session.add(child)
    session.commit()
    session.refresh(child)

    target_date = date(2024, 5, 2)
    verif_sick = AttendanceVerification(
        child_id=child.id,
        target_date=target_date,
        status=AttendanceVerificationStatus.sick_absent,
    )
    session.add(verif_sick)
    session.commit()
    session.refresh(verif_sick)

    plan_absent = build_child_plan(
        session,
        child,
        target_date,
        planned_arrival_default=None,
        verification=verif_sick,
    )
    assert plan_absent is not None
    assert plan_absent.absent is True

    verif_present = AttendanceVerification(
        child_id=child.id,
        target_date=target_date,
        status=AttendanceVerificationStatus.present,
    )
    plan_present = build_child_plan(
        session,
        child,
        target_date,
        planned_arrival_default=None,
        verification=verif_present,
    )
    assert plan_present is not None
    assert plan_present.absent is False


def test_build_child_plan_planned_check_in_time(session: Session):
    from models import AttendanceRecord

    child = Child(
        id=3,
        last_name="予定",
        first_name="次郎",
        last_name_kana="ヨテイ",
        first_name_kana="ジロウ",
        birth_date=date(2021, 7, 1),
        sex=ChildSex.male,
        enrollment_date=date(2024, 4, 1),
        status=ChildStatus.enrolled,
    )
    session.add(child)
    session.commit()
    session.refresh(child)

    target_date = date(2024, 5, 3)
    rec = AttendanceRecord(
        child_id=child.id,
        attendance_date=target_date,
        check_in_at=None,
        planned_check_in_time="08:45",
        planned_pickup_time="17:00",
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)

    plan = build_child_plan(
        session,
        child,
        target_date,
        attendance_record=rec,
        planned_arrival_default=None,
    )
    assert plan is not None
    assert plan.arrive == time(8, 45)
    assert plan.depart == time(17, 0)


def test_active_children_filter(session: Session):
    from shift_schedule.bridge import active_children

    # 在籍児（基準日時点で在籍）
    child_enrolled = Child(
        id=10,
        last_name="在籍",
        first_name="太郎",
        last_name_kana="ザイセキ",
        first_name_kana="タロウ",
        birth_date=date(2021, 1, 1),
        sex=ChildSex.male,
        enrollment_date=date(2024, 4, 1),
        withdrawal_date=None,
        status=ChildStatus.enrolled,
    )
    # 退園児（statusがwithdrawn）
    child_withdrawn_status = Child(
        id=11,
        last_name="退園",
        first_name="次郎",
        last_name_kana="タイエン",
        first_name_kana="ジロウ",
        birth_date=date(2021, 1, 1),
        sex=ChildSex.male,
        enrollment_date=date(2024, 4, 1),
        withdrawal_date=date(2024, 4, 30),
        status=ChildStatus.withdrawn,
    )
    # 途中退園（statusはenrolledだが対象日時点で退園日を超過）
    child_withdrawn_date = Child(
        id=12,
        last_name="途中",
        first_name="三郎",
        last_name_kana="トチュウ",
        first_name_kana="サブロウ",
        birth_date=date(2021, 1, 1),
        sex=ChildSex.male,
        enrollment_date=date(2024, 4, 1),
        withdrawal_date=date(2024, 5, 10),
        status=ChildStatus.enrolled,
    )
    # 未来入園（対象日より後に入園）
    child_future = Child(
        id=13,
        last_name="未来",
        first_name="四郎",
        last_name_kana="ミライ",
        first_name_kana="シロウ",
        birth_date=date(2021, 1, 1),
        sex=ChildSex.male,
        enrollment_date=date(2024, 6, 1),
        withdrawal_date=None,
        status=ChildStatus.enrolled,
    )
    session.add_all([child_enrolled, child_withdrawn_status, child_withdrawn_date, child_future])
    session.commit()

    # 2024-05-01 時点
    active_may1 = active_children(session, date(2024, 5, 1))
    active_ids_may1 = {c.id for c in active_may1}
    assert 10 in active_ids_may1
    assert 12 in active_ids_may1  # 5/10退園なので5/1時点では在籍
    assert 11 not in active_ids_may1  # status=withdrawn
    assert 13 not in active_ids_may1  # 入園前

    # 2024-05-15 時点
    active_may15 = active_children(session, date(2024, 5, 15))
    active_ids_may15 = {c.id for c in active_may15}
    assert 10 in active_ids_may15
    assert 12 not in active_ids_may15  # withdrawal_date <= 2024-05-15


def test_closed_days_and_holidays_in_requirements(session: Session):
    from shiftai.domain import AgeClass, ChildPlan
    from shiftai.standards import build_requirements
    from shift_schedule.db_models import ShiftFacilityClosedDays

    # 5/1: 通常日, 5/3: closed(休園日), 5/6: holiday(祝日)
    d1 = date(2024, 5, 1)
    d_closed = date(2024, 5, 3)
    d_holiday = date(2024, 5, 6)
    days = [d1, d_closed, d_holiday]

    child_plan1 = ChildPlan(
        child_id="c1",
        name="園児1",
        day=d1,
        age_class=AgeClass.AGE_1,
        arrive=time(8, 0),
        depart=time(17, 0),
    )
    child_plan_closed = ChildPlan(
        child_id="c1",
        name="園児1",
        day=d_closed,
        age_class=AgeClass.AGE_1,
        arrive=time(8, 0),
        depart=time(17, 0),
    )
    child_plan_holiday = ChildPlan(
        child_id="c1",
        name="園児1",
        day=d_holiday,
        age_class=AgeClass.AGE_1,
        arrive=time(8, 0),
        depart=time(17, 0),
    )

    closed_row = ShiftFacilityClosedDays(setting_id=1, target_date=d_closed, kind="closed")
    holiday_row = ShiftFacilityClosedDays(setting_id=1, target_date=d_holiday, kind="holiday")
    session.add_all([closed_row, holiday_row])
    session.commit()

    rows = session.exec(
        select(ShiftFacilityClosedDays).where(ShiftFacilityClosedDays.target_date.in_(days))
    ).all()
    closed_dates = [r.target_date for r in rows if r.kind == "closed"]
    holiday_dates = [r.target_date for r in rows if r.kind == "holiday"]

    from shiftai.local_rules import build_standard
    standard = build_standard("全国基準（厚労省）")
    req_table = build_requirements(
        [child_plan1, child_plan_closed, child_plan_holiday],
        days,
        standard,
        day_open=time(7, 30),
        day_close=time(18, 30),
        closed_days=closed_dates,
        holiday_dates=holiday_dates,
    )

    # closed の日は rows が空（需要なし）
    assert len(req_table.for_day(d_closed)) == 0
    # 通常日はスロットが存在する
    assert len(req_table.for_day(d1)) > 0
    # 祝日はスロットが存在し、basis に '祝日' が含まれ is_binding が False
    holiday_rows = req_table.for_day(d_holiday)
    assert len(holiday_rows) > 0
    assert any("祝日" in r.basis and not r.is_binding for r in holiday_rows)


def test_build_staff_member_with_36_and_variable(session: Session):
    from models import User
    from shift_schedule.bridge import build_staff_member
    from shift_schedule.db_models import StaffContracts, StaffQualifications
    from uuid import uuid4

    uid = uuid4()
    u = User(
        id=uid,
        email="test_36@example.com",
        display_name="36協定テスト職員",
        role="staff",
        is_active=True,
    )
    session.add(u)

    q = StaffQualifications(
        staff_user_id=uid.hex,
        role="保育士",
        effective_from=date(2026, 4, 1),
    )
    session.add(q)

    c = StaffContracts(
        staff_user_id=uid.hex,
        employment_type="正職員",
        weekly_hours=40.0,
        daily_hours=8.0,
        can_work_holiday=True,
        overtime_allowed=False,
        has_36_agreement=False,
        variable_working_hours=True,
        effective_from=date(2026, 4, 1),
    )
    session.add(c)
    session.commit()

    sm = build_staff_member(session, u)
    assert sm is not None
    assert sm.contract.overtime_allowed is False
    assert sm.contract.has_36_agreement is False
    assert sm.contract.variable_working_hours is True





