from datetime import date, datetime
from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select, SQLModel

from attendance_correction_service import cancel_punch, correction_revision
from models import (
    AttendanceRecord,
    Child,
    ChildStatus,
    Family,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    PasswordCredential,
    ParentNotification,
    ParentNotificationKind,
    User,
)


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    try:
        yield engine
    finally:
        engine.dispose()


def _seed(engine):
    with Session(engine) as session:
        actor = User(
            email="staff@example.test",
            display_name="検証担当",
            staff_role="admin",
        )
        family = Family(family_name="検証家", home_address="旧住所")
        child = Child(
            last_name="検証",
            first_name="葵",
            last_name_kana="ケンショウ",
            first_name_kana="アオイ",
            birth_date=date(2021, 5, 4),
            enrollment_date=date(2026, 4, 1),
            status=ChildStatus.enrolled,
            family_id=None,
            classroom_id=None,
            registration_verification_name="ケンショウ アオイ",
            registration_verification_name_type="kana",
        )
        parent = ParentAccount(
            display_name="保護者 花",
            email="parent@example.test",
            status=ParentAccountStatus.active,
        )
        session.add_all([actor, family, child, parent])
        session.flush()
        session.add(ParentChildLink(parent_account_id=parent.id, child_id=child.id))
        session.add(
            PasswordCredential(
                principal_type="parent",
                parent_account_id=parent.id,
                login_id="parent@example.test",
                login_id_normalized="parent@example.test",
                password_hash="x",
                hash_scheme="argon2id",
                credential_version=1,
            )
        )
        record = AttendanceRecord(
            child_id=child.id,
            attendance_date=date(2026, 11, 5),
            check_in_at=datetime(2026, 11, 5, 8, 30),
            check_out_at=datetime(2026, 11, 5, 17, 0),
        )
        session.add(record)
        session.commit()
        return dict(
            actor=SimpleNamespace(user_id=actor.id, name="検証担当"),
            parent_id=parent.id,
            record_id=record.id,
        )


def test_cancel_punch_notifies_child_parents(engine):
    ids = _seed(engine)
    with Session(engine) as session:
        record = session.get(AttendanceRecord, ids["record_id"])
        cancel_punch(
            session,
            record,
            operation="check_out",
            reason="打刻ミスのため取消",
            revision=correction_revision(record),
            actor=ids["actor"],
        )
    with Session(engine) as session:
        notifs = session.exec(
            select(ParentNotification).where(
                ParentNotification.kind == ParentNotificationKind.punch_correction_notice,
                ParentNotification.source_type == "attendance_correction",
            )
        ).all()
        assert len(notifs) == 1
        assert notifs[0].parent_account_id == ids["parent_id"]
        assert "11月5日" in notifs[0].body
        assert notifs[0].action_url is None
