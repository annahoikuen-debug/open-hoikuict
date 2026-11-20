"""オフライン打刻・冪等性同期検証テスト (Phase 5.1 / 回帰防止).

本テストスイートが保証する不変条件:
1. 同一の `idempotency_key` を持った登園打刻リクエストが複数回送信されても、
   レコードは 1 件のみ生成され、二重登録や 409 Conflict エラーにならないこと。
2. 降園打刻でも同様に同一キーによる二重打刻が防止されること。
"""

from __future__ import annotations

import datetime as dt
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from csrf import CSRF_COOKIE_NAME, generate_csrf_token
from database import create_db_and_tables, engine
from main import app
from models.core import AttendanceRecord, Child, ChildSex, ChildStatus, Family
from testing_helpers import authenticate_mock_staff


@pytest.fixture
def client() -> TestClient:
    c = TestClient(app)
    authenticate_mock_staff(c)
    token = generate_csrf_token()
    c.cookies.set(CSRF_COOKIE_NAME, token)
    c.headers.update({"X-CSRF-Token": token})
    return c


def test_同一idempotency_keyによる登園打刻の冪等性(client: TestClient) -> None:
    """同一 idempotency_key で登園打刻を 3 回連続送信しても 1 件のみ登録されること。"""
    create_db_and_tables()

    day_str = dt.date.today().isoformat()
    child_id = None

    with Session(engine) as session:
        family = Family(family_name="冪等テスト家", contact_phone="090-0000-0000")
        session.add(family)
        session.flush()

        child = Child(
            family_id=family.id,
            first_name="太郎",
            last_name="冪等",
            first_name_kana="タロウ",
            last_name_kana="ベキトウ",
            birth_date=dt.date(2022, 1, 1),
            enrollment_date=dt.date(2024, 4, 1),
            sex=ChildSex.male,
            status=ChildStatus.enrolled,
        )
        session.add(child)
        session.commit()
        child_id = child.id

    idempotency_key = f"test_kiosk_{uuid4().hex}"

    # 1 回目送信
    resp1 = client.post(
        f"/attendance/{child_id}/check-in",
        data={"date": day_str, "idempotency_key": idempotency_key},
        follow_redirects=False,
    )
    assert resp1.status_code == 303, resp1.text

    # 2 回目送信（ネットワーク再送・オフライン同期を模擬）
    resp2 = client.post(
        f"/attendance/{child_id}/check-in",
        data={"date": day_str, "idempotency_key": idempotency_key},
        follow_redirects=False,
    )
    assert resp2.status_code == 303, resp2.text

    # 3 回目送信
    resp3 = client.post(
        f"/attendance/{child_id}/check-in",
        data={"date": day_str, "idempotency_key": idempotency_key},
        follow_redirects=False,
    )
    assert resp3.status_code == 303, resp3.text

    # DB 内のレコード件数検証
    with Session(engine) as session:
        records = session.exec(
            select(AttendanceRecord).where(
                AttendanceRecord.child_id == child_id,
                AttendanceRecord.attendance_date == dt.date.today(),
            )
        ).all()
        assert len(records) == 1, f"打刻レコードが重複登録されています: {len(records)} 件"
        assert records[0].idempotency_key == idempotency_key
        assert records[0].check_in_at is not None
        assert records[0].check_out_at is None


def test_同一idempotency_keyによる降園打刻の冪等性(client: TestClient) -> None:
    """同一 idempotency_key で降園打刻を 3 回連続送信しても 1 回のみ反映されること。"""
    create_db_and_tables()

    day_str = dt.date.today().isoformat()
    child_id = None

    with Session(engine) as session:
        family = Family(family_name="降園テスト家", contact_phone="090-1111-2222")
        session.add(family)
        session.flush()

        child = Child(
            family_id=family.id,
            first_name="花子",
            last_name="降園",
            first_name_kana="ハナコ",
            last_name_kana="コウエン",
            birth_date=dt.date(2022, 2, 2),
            enrollment_date=dt.date(2024, 4, 1),
            sex=ChildSex.female,
            status=ChildStatus.enrolled,
        )
        session.add(child)
        session.flush()

        # 登園済みのレコードを作成
        rec = AttendanceRecord(
            child_id=child.id,
            attendance_date=dt.date.today(),
            check_in_at=dt.datetime.now(),
            lock_version=1,
        )
        session.add(rec)
        session.commit()
        child_id = child.id

    out_key = f"test_out_{uuid4().hex}"

    # 降園打刻 1回目
    resp1 = client.post(
        f"/attendance/{child_id}/check-out",
        data={"date": day_str, "idempotency_key": out_key},
        follow_redirects=False,
    )
    assert resp1.status_code == 303, resp1.text

    # 降園打刻 2回目（再送）
    resp2 = client.post(
        f"/attendance/{child_id}/check-out",
        data={"date": day_str, "idempotency_key": out_key},
        follow_redirects=False,
    )
    assert resp2.status_code == 303, resp2.text

    # DB 検証
    with Session(engine) as session:
        records = session.exec(
            select(AttendanceRecord).where(
                AttendanceRecord.child_id == child_id,
                AttendanceRecord.attendance_date == dt.date.today(),
            )
        ).all()
        assert len(records) == 1
        assert records[0].check_out_at is not None
        assert records[0].idempotency_key == out_key
