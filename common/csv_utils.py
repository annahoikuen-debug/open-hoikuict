"""CSV 安全出力ユーティリティ。

CSV Formula Injection (CWE-1236) を防止するため、
セル文字列の先頭が `=`, `+`, `-`, `@`, `\t`, `\r` などの数式記号で始まる場合、
先頭にシングルクォート `'` を付与して無害化する。
"""

from __future__ import annotations

import re
from typing import Any

# 先頭の空白類に続く数式トリガー記号
_CSV_FORMULA_PREFIX = re.compile(r"^[\s]*[=+\-@\t\r]")
_CSV_QUOTE_PREFIX = "'"


def sanitize_csv_cell(value: Any) -> Any:
    """CSV セル値が数式として解釈されないよう無害化する。

    - 数値（int, float）や None、真偽値はそのまま返す。
    - 文字列が `-1` や `+2.5` など単純な数値として解釈できる場合はそのまま残す。
    - 数式記号で始まり、数値でない文字列は先頭に `'` を付与する。
    """
    if not isinstance(value, str):
        return value
    if not value or not _CSV_FORMULA_PREFIX.match(value):
        return value
    # 数値リテラル（例: "-100", "+5.2", " -3 "）は安全なのでそのまま通す
    cleaned = value.replace(",", "").strip()
    try:
        float(cleaned)
        return value
    except ValueError:
        pass
    return _CSV_QUOTE_PREFIX + value

