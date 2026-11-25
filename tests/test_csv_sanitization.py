from common.csv_utils import sanitize_csv_cell


def test_sanitize_csv_cell_plain_text():
    assert sanitize_csv_cell("normal text") == "normal text"
    assert sanitize_csv_cell("田中 太郎") == "田中 太郎"
    assert sanitize_csv_cell("") == ""
    assert sanitize_csv_cell(None) is None
    assert sanitize_csv_cell(123) == 123
    assert sanitize_csv_cell(45.6) == 45.6


def test_sanitize_csv_cell_numeric_with_signs():
    # Valid numeric strings with signs should be preserved
    assert sanitize_csv_cell("-100") == "-100"
    assert sanitize_csv_cell("+42") == "+42"
    assert sanitize_csv_cell("-3.14") == "-3.14"
    assert sanitize_csv_cell(" +50 ") == " +50 "


def test_sanitize_csv_cell_formula_injection():
    # Dangerous formula prefixes must be escaped with a leading quote
    assert sanitize_csv_cell("=1+1") == "'=1+1"
    assert sanitize_csv_cell("=cmd|'/C calc'!A0") == "'=cmd|'/C calc'!A0"
    assert sanitize_csv_cell("+cmd|'/C calc'!A0") == "'+cmd|'/C calc'!A0"
    assert sanitize_csv_cell("-cmd|'/C calc'!A0") == "'-cmd|'/C calc'!A0"
    assert sanitize_csv_cell("@SUM(A1:A10)") == "'@SUM(A1:A10)"
    assert sanitize_csv_cell("\t=SUM(A1:A10)") == "'\t=SUM(A1:A10)"
    assert sanitize_csv_cell("   =SUM(A1:A10)") == "'   =SUM(A1:A10)"
    assert sanitize_csv_cell("=HYPERLINK(\"http://evil.com\", \"Click\")") == "'=HYPERLINK(\"http://evil.com\", \"Click\")"


def test_export_csv_builders_sanitize_formula_injection():
    """CSVエクスポートビルダーが数式インジェクション文字を無害化すること。"""
    import csv
    import io
    from datetime import date
    from data_transfer_service import build_csv_content
    from extended_care_fee_service import (
        ExtendedCareMonthlyOverview,
        ExtendedCareMonthlySummary,
        build_monthly_csv,
    )

    raw_bytes = build_csv_content([["名前", "メモ"], ["=CMD('calc')", "@SUM(A1:A2)"], ["+1+2", "\t=evil"]])
    rows = list(csv.reader(io.StringIO(raw_bytes.decode("utf-8-sig"))))
    assert rows[1] == ["'=CMD('calc')", "'@SUM(A1:A2)"]
    assert rows[2] == ["'+1+2", "'\t=evil"]

    overview = ExtendedCareMonthlyOverview(
        month="2026-11",
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 30),
        summaries=[
            ExtendedCareMonthlySummary(
                child_id=1,
                child_name="=EVIL()",
                child_name_kana="テスト",
                classroom_name="+危険組",
                classroom_sort_order=1,
            )
        ],
        warnings=[],
        total_extended_days=0,
        total_extended_minutes=0,
        total_auto_amount=0,
        total_adjustment_amount=0,
        total_final_amount=0,
        total_unconfirmed_count=0,
    )
    monthly_rows = list(csv.reader(io.StringIO(build_monthly_csv(overview).decode("utf-8-sig"))))
    assert "'=EVIL()" in monthly_rows[1]
    assert "'+危険組" in monthly_rows[1]
