"""請求・Zengin の回帰防止テスト。

延長保育料計算、全銀フォーマット出力が回帰しないことを検証する。
"""

from __future__ import annotations

from datetime import date, datetime

from extended_care_fee_service import (
    ChargeComputation,
    calculate_charge,
    validate_fee_rule,
)
from models import (
    AttendanceRecord,
    ExtendedCareFeeRule,
)
from zengin_service import (
    DEFAULT_RESULT_CODE_MAP,
    ParsedResultRecord,
    build_data_record,
    build_end_record,
    build_file_bytes,
    build_header_record,
    build_trailer_record,
    calculate_content_hash,
    create_customer_number,
    format_c,
    format_n,
    validate_billing_setting,
    validate_profile_for_zengin,
    validate_record,
    validate_zengin_c_chars,
)


# ---------------------------------------------------------------------------
# 延長保育料計算
# ---------------------------------------------------------------------------


def _make_rule(**overrides):
    base = dict(
        name="標準延長保育料",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        start_time="18:00",
        grace_minutes=5,
        rounding_minutes=15,
        unit_price=100,
        daily_cap_amount=1000,
        is_active=True,
        care_time_category=None,
    )
    base.update(overrides)
    return ExtendedCareFeeRule(**base)


def _make_record(
    *,
    check_in_at=None,
    check_out_at=None,
    attendance_date=date(2026, 11, 2),
    planned_pickup_time="18:30",
):
    return AttendanceRecord(
        child_id=1,
        attendance_date=attendance_date,
        check_in_at=check_in_at,
        check_out_at=check_out_at,
        planned_pickup_time=planned_pickup_time,
    )


def test_calculate_charge_within_grace_is_zero():
    """猶予時間内の降園は課金対象外（0円）であること。"""
    rule = _make_rule()
    record = _make_record(
        check_in_at=datetime(2026, 11, 2, 9, 0),
        check_out_at=datetime(2026, 11, 2, 18, 5),  # 18:00 + 5分猶予 = 残業0分
    )
    computed = calculate_charge(record, rule)
    assert isinstance(computed, ChargeComputation)
    assert computed.extended_minutes == 0
    assert computed.auto_amount == 0


def test_calculate_charge_beyond_grace_charges():
    """猶予時間を超過すると課金されること。"""
    rule = _make_rule()
    record = _make_record(
        check_in_at=datetime(2026, 11, 2, 9, 0),
        check_out_at=datetime(2026, 11, 2, 18, 20),  # 18:00 + 5分猶予 + 15分
    )
    computed = calculate_charge(record, rule)
    assert computed.extended_minutes == 15
    assert computed.billable_units == 1
    assert computed.auto_amount == 100


def test_calculate_charge_daily_cap():
    """日別上限額で金額が制限されること。"""
    rule = _make_rule(daily_cap_amount=50)
    record = _make_record(
        check_in_at=datetime(2026, 11, 2, 9, 0),
        check_out_at=datetime(2026, 11, 2, 20, 0),  # 2時間延長
    )
    computed = calculate_charge(record, rule)
    # 115分 → 8単位(120分) → 800円 → 上限50円
    assert computed.auto_amount == 50


def test_validate_fee_rule_valid():
    """正しい料金ルールはバリデーションエラーを返さないこと。"""
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, Session, create_engine

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        errors = validate_fee_rule(
            session,
            name="テストルール",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            start_time="18:00",
            grace_minutes=5,
            rounding_minutes=15,
            unit_price=100,
            daily_cap_amount=None,
            is_active=True,
        )
        assert errors == []


def test_validate_fee_rule_invalid_grace():
    """猶予時間が 0-120 範囲外の場合はエラーとなること。"""
    from sqlalchemy.pool import StaticPool
    from sqlmodel import SQLModel, Session, create_engine

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        errors = validate_fee_rule(
            session,
            name="テストルール",
            effective_from=date(2026, 1, 1),
            effective_to=None,
            start_time="18:00",
            grace_minutes=200,  # 120を超過
            rounding_minutes=15,
            unit_price=100,
            daily_cap_amount=None,
            is_active=True,
        )
        assert any("猶予時間" in e for e in errors)


# ---------------------------------------------------------------------------
# 全銀フォーマット：フォーマット関数
# ---------------------------------------------------------------------------


def test_format_n_zero_padding():
    """format_n はゼロパディングを行うこと。"""
    assert format_n("123", 5) == "00123"
    assert format_n(42, 4) == "0042"


def test_format_n_non_digit_rejected():
    """format_n は数字以外を拒否すること。"""
    try:
        format_n("abc", 5)
        assert False, "ZenginError が送出されるべき"
    except Exception:
        pass


def test_format_c_padding():
    """format_c は指定長でスペースパディングを行うこと。"""
    result = format_c("ABC", 10)
    assert len(result) == 10
    assert result.startswith("ABC")
    assert result.endswith("   ")


def test_validate_record_length():
    """validate_record は120バイトであることを検証すること。"""
    record = "1" + " " * 119
    try:
        validate_record(record)
    except Exception:
        assert False, "120バイトレコードは有効であるべき"


def test_validate_zengin_c_chars_allowed():
    """C項目許容文字が正しく検証されること。"""
    try:
        validate_zengin_c_chars("ABC 123 -./()")
    except Exception:
        assert False, "許容文字はエラーにならないべき"


def test_validate_zengin_c_chars_rejected():
    """C項目非許容文字が拒否されること。"""
    try:
        validate_zengin_c_chars("abc")
        assert False, "非許容文字はエラーになるべき"
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 全銀フォーマット：レコード構築
# ---------------------------------------------------------------------------


def test_build_header_record():
    """ヘッダーレコードが120バイトで構築されること。"""
    settings = {
        "file_encoding": "cp932",
        "code_type": "0",
        "collector_code": "1234567890",
        "collector_name_kana": "HOIKUEN",
        "withdrawal_bank_code": "0001",
        "withdrawal_bank_name_kana": "GINKOU",
        "withdrawal_branch_code": "001",
        "withdrawal_branch_name_kana": "SHITEN",
        "collector_account_type": "1",
        "collector_account_number": "1234567",
    }
    withdrawal_date = date(2026, 11, 5)
    record = build_header_record(settings, withdrawal_date)
    assert len(record.encode("cp932")) == 120
    assert record[0] == "1"


def test_build_data_record():
    """データレコードが120バイトで構築されること。"""
    from models import ZenginExportLine

    line = ZenginExportLine(
        zengin_export_id=1,
        billing_claim_id=1,
        family_id=1,
        customer_number="0010000000000000001",
        amount=5000,
        bank_snapshot={
            "bank_code": "0001",
            "bank_name_kana": "GINKOU",
            "branch_code": "001",
            "branch_name_kana": "SHITEN",
            "account_type": "1",
            "account_number": "1234567",
            "account_holder_kana": "TANAKA TARO",
            "new_code": "0",
            "customer_number": "0010000000000000001",
        },
    )
    record = build_data_record(line)
    assert len(record.encode("cp932")) == 120
    assert record[0] == "2"


def test_build_trailer_record():
    """トレーラーレコードが120バイトで構築されること。"""
    from models import ZenginExportLine

    lines = [
        ZenginExportLine(
            zengin_export_id=1,
            billing_claim_id=1,
            family_id=1,
            customer_number="0010000000000000001",
            amount=5000,
            bank_snapshot={},
        ),
        ZenginExportLine(
            zengin_export_id=1,
            billing_claim_id=2,
            family_id=2,
            customer_number="0020000000000000002",
            amount=3000,
            bank_snapshot={},
        ),
    ]
    record = build_trailer_record(lines)
    assert len(record.encode("cp932")) == 120
    assert record[0] == "8"


def test_build_end_record():
    """エンドレコードが120バイトで構築されること。"""
    record = build_end_record()
    assert len(record.encode("cp932")) == 120
    assert record[0] == "9"


def test_build_file_bytes():
    """build_file_bytes で CRLF 連結バイト列が得られること。"""
    records = [
        build_header_record(
            {
                "file_encoding": "cp932",
                "code_type": "0",
                "collector_code": "1234567890",
                "collector_name_kana": "HOIKUEN",
                "withdrawal_bank_code": "0001",
                "withdrawal_bank_name_kana": "GINKOU",
                "withdrawal_branch_code": "001",
                "withdrawal_branch_name_kana": "SHITEN",
                "collector_account_type": "1",
                "collector_account_number": "1234567",
            },
            date(2026, 11, 5),
        ),
        build_end_record(),
    ]
    data = build_file_bytes(records, "cp932", "CRLF")
    assert b"\r\n" in data
    assert len(data) == 244  # 2 records * (120 bytes + CRLF 2 bytes)


def test_calculate_content_hash():
    """コンテンツハッシュがSHA-256 hex であること。"""
    h = calculate_content_hash(b"test data")
    assert len(h) == 64
    assert all(c in "0123456789abcdef" for c in h)


def test_create_customer_number():
    """顧客番号が施設コード3桁+家族ID17桁で構成されること。"""
    cn = create_customer_number("001", 42)
    assert cn == "001" + "00000000000000042"
    assert len(cn) == 20


# ---------------------------------------------------------------------------
# 全銀フォーマット：検証
# ---------------------------------------------------------------------------


def test_validate_billing_setting_valid():
    """正しい請求設定はバリデーションを通過すること。"""
    from models import BillingSetting

    settings = BillingSetting(
        facility_name="HOIKU",
        collector_code="1234567890",
        collector_name_kana="HOIKUEN",
        withdrawal_bank_code="0001",
        withdrawal_bank_name_kana="GINKOU",
        withdrawal_branch_code="001",
        withdrawal_branch_name_kana="SHITEN",
        collector_account_type="1",
        collector_account_number="1234567",
        file_encoding="cp932",
        line_separator="CRLF",
    )
    try:
        validate_billing_setting(settings)
    except Exception:
        assert False, "正しい設定はエラーにならないべき"


def test_validate_profile_for_zengin_valid():
    """正しい家族課金プロファイルはバリデーションを通過すること。"""
    from models import (
        BillingPaymentMethod,
        DirectDebitStatus,
        FamilyBillingProfile,
    )

    profile = FamilyBillingProfile(
        family_id=1,
        bank_code="0001",
        bank_name_kana="GINKOU",
        branch_code="001",
        branch_name_kana="SHITEN",
        account_type="1",
        account_number="1234567",
        account_holder_kana="TANAKA TARO",
        customer_number="0010000000000000001",
        new_code="0",
        payment_method=BillingPaymentMethod.direct_debit,
        direct_debit_status=DirectDebitStatus.active,
    )
    try:
        validate_profile_for_zengin(profile)
    except Exception:
        assert False, "正しいプロファイルはエラーにならないべき"


def test_default_result_code_map():
    """結果コードマップが期待通りであること。"""
    assert DEFAULT_RESULT_CODE_MAP["0"] == ("paid", "振替済")
    assert DEFAULT_RESULT_CODE_MAP["1"] == ("failed", "資金不足")
    assert DEFAULT_RESULT_CODE_MAP["9"] == ("failed", "その他")


def test_parsed_result_record_status_key():
    """ParsedResultRecord の status_key が正しくマッピングされること。"""
    record = ParsedResultRecord(
        customer_number="0010000000000000001",
        amount=5000,
        result_code="0",
    )
    assert record.status_key == "paid"

    record_failed = ParsedResultRecord(
        customer_number="0020000000000000002",
        amount=3000,
        result_code="1",
    )
    assert record_failed.status_key == "failed"
