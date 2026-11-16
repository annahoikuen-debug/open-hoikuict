"""共通楽観的ロックユーティリティのテスト。"""

import pytest
from common.optimistic_lock import _validate_sql_identifier, claim_lock, ConcurrentUpdateError


def test_validate_sql_identifier_valid():
    _validate_sql_identifier("notices")
    _validate_sql_identifier("notice_id")
    _validate_sql_identifier("_table_123")


def test_validate_sql_identifier_invalid():
    with pytest.raises(ValueError, match="不正なSQL識別子"):
        _validate_sql_identifier("notices; DROP TABLE users;")

    with pytest.raises(ValueError, match="不正なSQL識別子"):
        _validate_sql_identifier("notices table")

    with pytest.raises(ValueError, match="不正なSQL識別子"):
        _validate_sql_identifier("123bad")

    with pytest.raises(ValueError, match="不正なSQL識別子"):
        _validate_sql_identifier("notices-dash")
