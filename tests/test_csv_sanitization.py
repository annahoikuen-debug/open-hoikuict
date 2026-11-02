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
