from __future__ import annotations

import codecs
import csv
import io
from datetime import date, datetime, time
from urllib.parse import quote
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from csrf import CSRF_COOKIE_NAME, generate_csrf_token
from database import engine as app_engine, create_db_and_tables
from main import app
import uuid
from auth import Role
from models import User
from models.pims import PunchChild, PunchLog
import pims_service
from testing_helpers import authenticate_mock_staff

PIMS_TEST_ADMIN_ID = uuid.uuid4()


@pytest.fixture(autouse=True)
def setup_db():
    create_db_and_tables()
    with Session(app_engine) as session:
        # 専用の管理者ユーザーを作成
        admin = session.get(User, PIMS_TEST_ADMIN_ID)
        if not admin:
            admin = User(
                id=PIMS_TEST_ADMIN_ID,
                email="admin-pims@example.test",
                display_name="園長",
                staff_role="admin",
                can_manage_child_records=True,
                can_export_documents=True,
                is_active=True,
            )
            session.add(admin)
        # テストデータのクリーンアップ
        for log in session.exec(select(PunchLog)).all():
            session.delete(log)
        for child in session.exec(select(PunchChild)).all():
            session.delete(child)
        session.commit()
    yield
    with Session(app_engine) as session:
        for log in session.exec(select(PunchLog)).all():
            session.delete(log)
        for child in session.exec(select(PunchChild)).all():
            session.delete(child)
        admin = session.get(User, PIMS_TEST_ADMIN_ID)
        if admin:
            session.delete(admin)
        session.commit()


@pytest.fixture
def client():
    c = TestClient(app)
    authenticate_mock_staff(c, role=Role.ADMIN, user_id=PIMS_TEST_ADMIN_ID, can_manage_child_records=True)
    # まずGETを呼んでCSRFミドルウェアにクッキーを生成させる
    c.get("/toukouen")
    token = c.cookies.get(CSRF_COOKIE_NAME)
    if not token:
        token = generate_csrf_token()
        c.cookies.set(CSRF_COOKIE_NAME, token)
    c.headers.update({"X-CSRF-Token": token})
    return c


@pytest.fixture
def db_session():
    with Session(app_engine) as session:
        yield session


def test_f01_top_screen(client: TestClient, db_session: Session):
    """F-01: モード選択TOP画面の検証"""
    resp = client.get("/toukouen")
    assert resp.status_code == 200
    assert "登園" in resp.text
    assert "降園" in resp.text
    assert "欠席" in resp.text
    assert "コドモンCSV取込" in resp.text
    assert "ピムス用CSV出力" in resp.text


def test_f02_f03_select_screen(client: TestClient, db_session: Session):
    """F-02, F-03: 園児一覧・タッチ打刻画面およびQR入力の検証"""
    # 園児を作成
    child = PunchChild(
        child_id="TEST001",
        name="テスト 太郎",
        kana="テスト タロウ",
        birth_date=date(2020, 5, 10),
        class_name="さくら組",
        family_id=None,
        is_active=True,
    )
    db_session.add(child)
    db_session.commit()

    resp = client.get("/toukouen/select?mode=check_in")
    assert resp.status_code == 200
    assert "テスト 太郎" in resp.text
    assert "さくら組" in resp.text
    assert "qr-input" in resp.text
    assert "playSuccessBeep" in resp.text


def test_f04_sibling_matching(db_session: Session):
    """F-04: 世帯ID連動・兄弟一括判定の厳格化検証"""
    # 兄弟2名 (同一family_id)
    c1 = PunchChild(
        child_id="SIB01",
        name="佐藤 一郎",
        kana="サトウ イチロウ",
        class_name="ひよこ組",
        family_id="FAM_SATO_01",
        is_active=True,
    )
    c2 = PunchChild(
        child_id="SIB02",
        name="佐藤 二郎",
        kana="サトウ ジロウ",
        class_name="うさぎ組",
        family_id="FAM_SATO_01",
        is_active=True,
    )
    # 同姓だが family_id なし（単独世帯）
    c3 = PunchChild(
        child_id="SIB03",
        name="佐藤 三郎",
        kana="サトウ サブロウ",
        class_name="きりん組",
        family_id=None,
        is_active=True,
    )
    # 同姓だが 別の family_id
    c4 = PunchChild(
        child_id="SIB04",
        name="佐藤 四郎",
        kana="サトウ シロウ",
        class_name="きりん組",
        family_id="FAM_SATO_02",
        is_active=True,
    )
    db_session.add_all([c1, c2, c3, c4])
    db_session.commit()

    # c1 の兄弟は c2 のみ（c3, c4 は含まれない）
    sibs_c1 = pims_service.find_siblings(db_session, c1)
    assert len(sibs_c1) == 1
    assert sibs_c1[0].child_id == "SIB02"

    # c3 (family_idなし) の兄弟判定は空（苗字「佐藤」で誤判定しない）
    sibs_c3 = pims_service.find_siblings(db_session, c3)
    assert len(sibs_c3) == 0

    # c4 (単独世帯) の兄弟判定は空
    sibs_c4 = pims_service.find_siblings(db_session, c4)
    assert len(sibs_c4) == 0


def test_f05_f06_punch_and_daily_status(client: TestClient, db_session: Session):
    """F-05, F-06: 欠席登録および当日ログ連動ステータス管理の検証"""
    child = PunchChild(
        child_id="PUNCH_TEST_01",
        name="山田 花子",
        class_name="うさぎ組",
        is_active=True,
    )
    db_session.add(child)
    db_session.commit()

    today = date.today()

    # 1. 未打刻時 -> "未登園"
    st = pims_service.get_daily_child_states(db_session, today)
    assert st["PUNCH_TEST_01"]["status"] == "未登園"

    # 2. 登園打刻 -> "登園中"
    pims_service.record_punch(
        db_session,
        child_ids=["PUNCH_TEST_01"],
        punch_type="登園",
        punched_at=datetime.combine(today, time(8, 30)),
        send_email=False,
    )
    st = pims_service.get_daily_child_states(db_session, today)
    assert st["PUNCH_TEST_01"]["status"] == "登園中"
    assert st["PUNCH_TEST_01"]["check_in_time"] == "08:30"

    # 3. 降園打刻 -> "降園済"
    pims_service.record_punch(
        db_session,
        child_ids=["PUNCH_TEST_01"],
        punch_type="降園",
        punched_at=datetime.combine(today, time(17, 15)),
        send_email=False,
    )
    st = pims_service.get_daily_child_states(db_session, today)
    assert st["PUNCH_TEST_01"]["status"] == "降園済"
    assert st["PUNCH_TEST_01"]["check_out_time"] == "17:15"

    # 4. 別日 (明日) の判定 -> 昨日の降園/登園ログに関係なく全員 "未登園" からスタート
    tomorrow = date(today.year, today.month, today.day + 1 if today.day < 28 else 28)
    st_tomorrow = pims_service.get_daily_child_states(db_session, tomorrow)
    assert st_tomorrow["PUNCH_TEST_01"]["status"] == "未登園"

    # 5. 欠席打刻 (F-05) -> "欠席" (病欠等/都合/災害)
    pims_service.record_punch(
        db_session,
        child_ids=["PUNCH_TEST_01"],
        punch_type="欠席",
        absence_reason="病欠等",
        punched_at=datetime.combine(tomorrow, time(9, 0)),
        send_email=False,
    )
    st_abs = pims_service.get_daily_child_states(db_session, tomorrow)
    assert st_abs["PUNCH_TEST_01"]["status"] == "欠席"
    assert st_abs["PUNCH_TEST_01"]["detail"] == "病欠等"


def test_f08_sibling_punch_api(client: TestClient, db_session: Session):
    """F-08: 兄弟同時打刻APIの検証"""
    c1 = PunchChild(child_id="BRO1", name="兄弟 兄", parent_email="parent@example.com", is_active=True)
    c2 = PunchChild(child_id="BRO2", name="兄弟 弟", parent_email="parent@example.com", is_active=True)
    db_session.add_all([c1, c2])
    db_session.commit()

    token = client.cookies.get(CSRF_COOKIE_NAME) or ""
    resp = client.post(
        "/toukouen/punch",
        data={
            "child_ids": ["BRO1", "BRO2"],
            "punch_type": "登園",
            "csrf_token": token,
        },
        headers={"X-CSRF-Token": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "兄弟 兄・兄弟 弟" in data["message"]


def test_f09_codmon_csv_import(db_session: Session):
    """F-09: コドモン「公金管理システム連携.csv」インポート検証"""
    # 既存園児（フリガナ・生年月日空欄）
    c_existing = PunchChild(
        child_id="V001",
        name="中村 陽葵",  # スペースあり
        kana=None,
        birth_date=None,
        is_active=True,
    )
    db_session.add(c_existing)
    db_session.commit()

    # コドモンの公金管理システム連携.csvサンプル（スペースなし名前）
    # ヘッダー: 名前, 名前(かな), 生年月日, ベンダCD, 予備, 日付, 欠席理由, 登園時刻, 退園時刻
    csv_content = (
        "名前,名前(かな),生年月日,ベンダCD,予備,日付,欠席理由,登園時刻,退園時刻\n"
        "中村陽葵,ナカムラ　ヒマリ,2025/07/20,11,,2026/11/02,,08:30,16:59\n"
        "新規 太郎,シンキ タロウ,2024/01/15,99,,2026/11/02,病欠等,,\n"
    )
    content_bytes = codecs.BOM_UTF8 + csv_content.encode("utf-8")

    result = pims_service.import_codmon_csv(db_session, content_bytes)
    assert result["updated_children"] >= 1
    assert result["new_children"] >= 1
    assert result["new_logs"] >= 3  # 中村陽葵の登園・降園、新規太郎の欠席

    # 既存園児が補完されたか確認
    updated_c = db_session.get(PunchChild, "V001")
    assert updated_c.kana == "ナカムラ　ヒマリ"
    assert updated_c.birth_date == date(2025, 7, 20)

    # 新規児童が登録されたか確認
    new_c = db_session.exec(select(PunchChild).where(PunchChild.name == "新規 太郎")).first()
    assert new_c is not None
    assert new_c.kana == "シンキ タロウ"
    assert new_c.birth_date == date(2024, 1, 15)

    # ログが登録されたか確認
    logs = db_session.exec(select(PunchLog).where(PunchLog.child_id == "V001")).all()
    types = {l.punch_type for l in logs}
    assert "登園" in types
    assert "降園" in types


def test_f10_f11_pims_csv_export(db_session: Session):
    """F-10, F-11: ピムス用9列CSV出力および降園抜け自動補完（18:00）検証"""
    child = PunchChild(
        child_id="PIMS_CHILD_01",
        name="鈴木　一郎 ",  # 全角・半角スペース含む
        kana="スズキ　イチロウ ",
        birth_date=date(2021, 3, 5),
        is_active=True,
    )
    db_session.add(child)
    db_session.commit()

    # 2026年11月1日: 登園 08:30, 降園 16:30
    pims_service.record_punch(
        db_session,
        child_ids=["PIMS_CHILD_01"],
        punch_type="登園",
        punched_at=datetime(2026, 11, 1, 8, 30),
        send_email=False,
    )
    pims_service.record_punch(
        db_session,
        child_ids=["PIMS_CHILD_01"],
        punch_type="降園",
        punched_at=datetime(2026, 11, 1, 16, 30),
        send_email=False,
    )

    # 2026年11月2日: 登園 09:00 のみ（降園押し忘れ！F-11）
    pims_service.record_punch(
        db_session,
        child_ids=["PIMS_CHILD_01"],
        punch_type="登園",
        punched_at=datetime(2026, 11, 2, 9, 0),
        send_email=False,
    )

    # 2026年11月3日: 欠席（病欠等）
    pims_service.record_punch(
        db_session,
        child_ids=["PIMS_CHILD_01"],
        punch_type="欠席",
        absence_reason="病欠等",
        punched_at=datetime(2026, 11, 3, 9, 0),
        send_email=False,
    )

    # ピムスCSV出力
    csv_bytes, missing_checkouts = pims_service.export_pims_csv(db_session, 2026, 11)

    # 1. BOM付きUTF-8であること
    assert csv_bytes.startswith(codecs.BOM_UTF8)

    # 2. 改行コードがCRLFであること
    assert b"\r\n" in csv_bytes

    text = csv_bytes.decode("utf-8-sig")
    lines = text.split("\r\n")

    # ヘッダー検証 (固定9列)
    assert lines[0] == "氏名,氏名カナ,生年月日,未使用,未使用,日付,欠席理由,登園時刻,降園時刻"

    # F-11: 降園抜けが1件検知され、18:00が補完されていること
    assert len(missing_checkouts) >= 1
    missing_item = [m for m in missing_checkouts if m["date"] == "2026/11/02"][0]
    assert missing_item["child_name"] == "鈴木一郎"
    assert missing_item["check_in_time"] == "09:00"
    assert missing_item["auto_checkout_time"] == "18:00"

    # 行ごとの仕様検証:
    # 氏名・カナのスペース完全除去
    assert "鈴木 一郎" not in text
    assert "鈴木　一郎" not in text
    assert "鈴木一郎" in text
    assert "スズキイチロウ" in text

    # 各日の行をチェック
    found_day1 = False
    found_day2 = False
    found_day3 = False
    found_day4 = False

    reader = csv.reader(io.StringIO(text))
    _ = next(reader)
    for row in reader:
        if not row:
            continue
        if row[0] == "鈴木一郎" and row[5] == "2026/11/01":
            # 11月1日: 登園 08:30, 降園 16:30, 欠席理由は空欄（排他制御）
            assert row[6] == ""
            assert row[7] == "08:30"
            assert row[8] == "16:30"
            found_day1 = True
        elif row[0] == "鈴木一郎" and row[5] == "2026/11/02":
            # 11月2日: 登園 09:00, 降園は自動補完で 18:00, 欠席理由は空欄
            assert row[6] == ""
            assert row[7] == "09:00"
            assert row[8] == "18:00"
            found_day2 = True
        elif row[0] == "鈴木一郎" and row[5] == "2026/11/03":
            # 11月3日: 欠席 病欠等, 登降園は空欄
            assert row[6] == "病欠等"
            assert row[7] == ""
            assert row[8] == ""
            found_day3 = True
        elif row[0] == "鈴木一郎" and row[5] == "2026/11/04":
            # 11月4日: 実績なし（契約外日） -> 欠席理由・登降園ともに空欄
            assert row[6] == ""
            assert row[7] == ""
            assert row[8] == ""
            found_day4 = True

    assert found_day1
    assert found_day2
    assert found_day3
    assert found_day4

    # 打刻忘れCSV出力検証 (F-11)
    missing_csv = pims_service.export_missing_checkouts_csv(missing_checkouts, 2026, 11)
    assert missing_csv.startswith(codecs.BOM_UTF8)
    assert b"\r\n" in missing_csv
    missing_text = missing_csv.decode("utf-8-sig")
    assert "日付,児童名,登園時刻,補完降園時刻,状態" in missing_text
    assert "2026/11/02,鈴木一郎,09:00,18:00,自動補完" in missing_text


def test_f09_codmon_shift_jis_and_reasons(db_session: Session):
    """F-09: Shift_JIS エンコーディングおよび各欠席理由（都合・災害）の取込検証"""
    csv_text = (
        "名前,名前(かな),生年月日,ベンダCD,予備,日付,欠席理由,登園時刻,退園時刻\n"
        "松本 蓮,マツモト レン,2024/03/10,SJIS01,,2026/11/05,都合,,\n"
        "高橋 湊,タカハシ ミナト,2023/12/01,SJIS02,,2026/11/05,災害,,\n"
    )
    sjis_bytes = csv_text.encode("shift_jis")

    result = pims_service.import_codmon_csv(db_session, sjis_bytes)
    assert result["new_children"] == 2
    assert result["new_logs"] == 2

    # 欠席理由の確認
    log_tsugo = db_session.exec(select(PunchLog).where(PunchLog.child_id == "SJIS01")).first()
    assert log_tsugo is not None
    assert log_tsugo.punch_type == "欠席"
    assert log_tsugo.absence_reason == "都合"

    log_saigai = db_session.exec(select(PunchLog).where(PunchLog.child_id == "SJIS02")).first()
    assert log_saigai is not None
    assert log_saigai.punch_type == "欠席"
    assert log_saigai.absence_reason == "災害"


def test_f08_email_notification_mock(monkeypatch, db_session: Session):
    """F-08: 保護者メール連名送信の検証"""
    sent_emails = []

    def mock_send_mail(*, recipient: str, subject: str, body: str):
        sent_emails.append({"recipient": recipient, "subject": subject, "body": body})

    monkeypatch.setattr("pims_service.send_auth_mail", mock_send_mail)

    c1 = PunchChild(child_id="MAIL01", name="中村 陽葵", parent_email="parent@sample.jp", is_active=True)
    c2 = PunchChild(child_id="MAIL02", name="中村 葵", parent_email="parent@sample.jp", is_active=True)
    db_session.add_all([c1, c2])
    db_session.commit()

    pims_service.record_punch(
        db_session,
        child_ids=["MAIL01", "MAIL02"],
        punch_type="登園",
        punched_at=datetime(2026, 11, 2, 8, 30),
        send_email=True,
    )

    # 兄弟2名に対してメールは1通のみ送信されること
    assert len(sent_emails) == 1
    mail = sent_emails[0]
    assert mail["recipient"] == "parent@sample.jp"
    assert "登園" in mail["subject"]
    # 連名で記載されていること
    assert "中村 陽葵 様、中村 葵 様" in mail["body"]
    assert "08:30" in mail["body"]


def test_download_endpoints(client: TestClient, db_session: Session):
    """F-10, F-11: ダウンロードエンドポイントの検証"""
    child = PunchChild(
        child_id="DL01",
        name="伊藤 結菜",
        kana="イトウ ユイナ",
        birth_date=date(2022, 1, 1),
        is_active=True,
    )
    db_session.add(child)
    db_session.commit()

    # 登園のみ打刻（降園抜け）
    pims_service.record_punch(
        db_session,
        child_ids=["DL01"],
        punch_type="登園",
        punched_at=datetime(2026, 10, 5, 8, 45),
        send_email=False,
    )

    # ピムスCSVダウンロード
    resp = client.get("/toukouen/export/pims/download?year=2026&month=10")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "月次報告_児童表_202610.csv" in quote("月次報告_児童表_202610.csv") or "attachment" in resp.headers["content-disposition"]
    assert resp.content.startswith(codecs.BOM_UTF8)
    csv_text = resp.content.decode("utf-8-sig")
    assert "伊藤結菜" in csv_text
    assert "18:00" in csv_text  # 補完されていること

    # 降園打刻忘れ一覧CSVダウンロード
    resp_missing = client.get("/toukouen/export/missing-checkout/download?year=2026&month=10")
    assert resp_missing.status_code == 200
    assert resp_missing.headers["content-type"].startswith("text/csv")
    missing_text = resp_missing.content.decode("utf-8-sig")
    assert "伊藤結菜" in missing_text
    assert "08:45" in missing_text
    assert "18:00" in missing_text


def test_children_management_and_sync(client: TestClient, db_session: Session):
    """園児マスタ管理画面および同期の検証"""
    resp = client.get("/toukouen/children")
    assert resp.status_code == 200
    assert "園児・世帯マスタ管理" in resp.text

    # ログ一覧画面
    resp_logs = client.get("/toukouen/logs")
    assert resp_logs.status_code == 200
    assert "打刻トランザクションログ" in resp_logs.text


def test_proposal_1_time_auto_mode_and_switcher(client: TestClient, db_session: Session):
    """提案1: 時間帯連動モード自動判定 ＆ 大型モード切替スイッチャーの検証"""
    child = PunchChild(
        child_id="TIME01",
        name="時間 太郎",
        class_name="つき組",
        is_active=True,
    )
    db_session.add(child)
    db_session.commit()

    # modeパラメータ未指定でGETアクセス -> 自動判定されること
    resp = client.get("/toukouen/select")
    assert resp.status_code == 200
    assert "mode-switch-btn" in resp.text
    assert 'data-mode-btn="check_in"' in resp.text
    assert 'data-mode-btn="check_out"' in resp.text
    assert 'data-mode-btn="absence"' in resp.text
    assert "data-status=" in resp.text
    assert "card-action-label" in resp.text
    assert "btn-toast-undo" in resp.text
    assert "btn-toast-skip" in resp.text


def test_proposal_2_punch_response_and_undo_api(client: TestClient, db_session: Session):
    """提案2: 打刻レスポンスの拡張 (log_ids, updated_states) ＆ 即時Undo (取り消し) の検証"""
    child = PunchChild(
        child_id="UNDO01",
        name="取消 花子",
        class_name="ほし組",
        is_active=True,
    )
    db_session.add(child)
    db_session.commit()

    token = client.cookies.get(CSRF_COOKIE_NAME) or ""

    # 1. 登園打刻を実行
    punch_resp = client.post(
        "/toukouen/punch",
        data={
            "child_ids": ["UNDO01"],
            "punch_type": "登園",
            "csrf_token": token,
        },
        headers={"X-CSRF-Token": token},
    )
    assert punch_resp.status_code == 200
    p_data = punch_resp.json()
    assert p_data["success"] is True
    assert "log_ids" in p_data
    assert len(p_data["log_ids"]) == 1
    log_id = p_data["log_ids"][0]
    assert "updated_states" in p_data
    assert p_data["updated_states"]["UNDO01"]["status"] == "登園中"

    # DB上にもログが存在することを確認
    assert db_session.get(PunchLog, log_id) is not None

    # 2. Undo API で打刻を取り消し
    undo_resp = client.post(
        "/toukouen/undo",
        data={
            "log_ids": [log_id],
            "csrf_token": token,
        },
        headers={"X-CSRF-Token": token},
    )
    assert undo_resp.status_code == 200
    u_data = undo_resp.json()
    assert u_data["success"] is True
    assert "取り消しました" in u_data["message"]
    # 最新ステータスが未登園に戻っていること
    assert u_data["updated_states"]["UNDO01"]["status"] == "未登園"

    # DB上のログが物理削除されていること
    assert db_session.get(PunchLog, log_id) is None


def test_proposal_2_sibling_undo(client: TestClient, db_session: Session):
    """提案2: 兄弟同時打刻のUndo検証（複数log_ids一括取り消し）"""
    c1 = PunchChild(child_id="SIB_U1", name="兄弟 兄太", family_id="FAM_U", is_active=True)
    c2 = PunchChild(child_id="SIB_U2", name="兄弟 妹子", family_id="FAM_U", is_active=True)
    db_session.add_all([c1, c2])
    db_session.commit()

    token = client.cookies.get(CSRF_COOKIE_NAME) or ""

    # 兄弟打刻
    punch_resp = client.post(
        "/toukouen/punch",
        data={
            "child_ids": ["SIB_U1", "SIB_U2"],
            "punch_type": "登園",
            "csrf_token": token,
        },
        headers={"X-CSRF-Token": token},
    )
    assert punch_resp.status_code == 200
    p_data = punch_resp.json()
    assert len(p_data["log_ids"]) == 2

    # 兄弟一括Undo
    undo_resp = client.post(
        "/toukouen/undo",
        data={
            "log_ids": p_data["log_ids"],
            "csrf_token": token,
        },
        headers={"X-CSRF-Token": token},
    )
    assert undo_resp.status_code == 200
    u_data = undo_resp.json()
    assert u_data["success"] is True
    assert u_data["updated_states"]["SIB_U1"]["status"] == "未登園"
    assert u_data["updated_states"]["SIB_U2"]["status"] == "未登園"


def test_toukouen_admin_endpoints_require_staff_auth():
    """バックオフィス管理エンドポイントへのアクセスには職員ログインが必須であること。"""
    unauth_client = TestClient(app)
    # 園児マスタ管理
    resp = unauth_client.get("/toukouen/children")
    assert resp.status_code in {401, 303}

    # PIMS CSV ダウンロード
    resp_dl = unauth_client.get("/toukouen/export/pims/download?year=2026&month=10")
    assert resp_dl.status_code in {401, 303}

    # コドモン CSV 取込
    resp_imp = unauth_client.get("/toukouen/import/codmon")
    assert resp_imp.status_code in {401, 303}


