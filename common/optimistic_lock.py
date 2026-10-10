"""共通楽観的ロックユーティリティ。

``plan_docs/store.py`` の ``_claim_lock`` および
``routers/notices.py`` の ``_claim_notice_lock`` を汎用化したモジュール。

使い方::

    from common.optimistic_lock import claim_lock, ConcurrentUpdateError

    # シンプルな TEXT UPDATE（notices 用）
    claim_lock(
        session,
        table_name="notices",
        id_col="id",
        id_val=notice_id,
        expected_version=lock_version,
    )

    # ORM UPDATE（plan_docs 用）
    claim_lock_orm(
        session,
        model_class=PlanDocumentHeadRow,
        where_col="document_id",
        id_val=document_id,
        expected_version=expected_lock_version,
    )
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlmodel import Session

from time_utils import utc_now


class ConcurrentUpdateError(RuntimeError):
    """楽観的ロックバージョン不一致時に送出する例外。

    同じメッセージで他ドメインのローカル定義と互換性を持つ。
    """

    DEFAULT_MESSAGE = "他の職員が先に更新しました。画面を再読み込みしてください。"

    def __init__(self, message: str = DEFAULT_MESSAGE) -> None:
        super().__init__(message)


def claim_lock(
    session: Session,
    *,
    table_name: str,
    id_col: str,
    id_val: int | str,
    expected_version: int,
    extra_updates: dict[str, Any] | None = None,
    message: str = ConcurrentUpdateError.DEFAULT_MESSAGE,
) -> None:
    """``UPDATE ... WHERE id = :id AND lock_version = :v`` を実行し、
    ``rowcount != 1`` なら :exc:`ConcurrentUpdateError` を送出する。

    Args:
        session: SQLModel セッション。
        table_name: 対象テーブル名（SQL インジェクション対策としてリテラル文字列を渡すこと）。
        id_col: 主キー列名（同上）。
        id_val: 主キー値。
        expected_version: クライアントが持つ現在の lock_version。
        extra_updates: ``lock_version`` / ``updated_at`` 以外に SET する列と値の dict。
        message: ConcurrentUpdateError に渡すメッセージ。

    Raises:
        ConcurrentUpdateError: ``rowcount != 1`` のとき（ロールバック済み）。
    """
    now = utc_now()
    set_pairs = "lock_version = lock_version + 1, updated_at = :updated_at"
    params: dict[str, Any] = {
        "updated_at": now,
        "id_val": id_val,
        "expected_version": expected_version,
    }
    if extra_updates:
        extra_parts = []
        for k, v in extra_updates.items():
            param_key = f"_extra_{k}"
            extra_parts.append(f"{k} = :{param_key}")
            params[param_key] = v
        set_pairs = f"{set_pairs}, " + ", ".join(extra_parts)

    sql = (
        f"UPDATE {table_name} "
        f"SET {set_pairs} "
        f"WHERE {id_col} = :id_val AND lock_version = :expected_version"
    )
    result = session.execute(text(sql), params)
    if result.rowcount != 1:
        session.rollback()
        raise ConcurrentUpdateError(message)
    session.expire_all()


def claim_lock_orm(
    session: Session,
    *,
    model_class: type,
    where_col: str,
    id_val: int | str,
    expected_version: int,
    extra_updates: dict[str, Any] | None = None,
    message: str = ConcurrentUpdateError.DEFAULT_MESSAGE,
) -> None:
    """SQLAlchemy ORM の ``update()`` で楽観的ロックを実施する。

    ``plan_docs/store.py`` の ``_claim_lock`` と同等の動作。

    Args:
        session: SQLModel セッション。
        model_class: 対象 ORM モデルクラス。
        where_col: ロック対象の WHERE 列名。
        id_val: WHERE 列の値。
        expected_version: クライアントが持つ現在の lock_version。
        extra_updates: ``lock_version`` / ``updated_at`` 以外に SET する値の dict。
        message: ConcurrentUpdateError に渡すメッセージ。

    Raises:
        ConcurrentUpdateError: ``rowcount != 1`` のとき（ロールバック済み）。
    """
    from sqlalchemy import update as sql_update  # 遅延インポートでサーキュラー回避

    now = utc_now()
    values: dict[str, Any] = {"lock_version": expected_version + 1, "updated_at": now}
    if extra_updates:
        values.update(extra_updates)

    id_filter = getattr(model_class, where_col) == id_val
    version_filter = model_class.lock_version == expected_version  # type: ignore[attr-defined]

    result = session.execute(
        sql_update(model_class).where(id_filter, version_filter).values(**values)
    )
    if result.rowcount != 1:
        session.rollback()
        raise ConcurrentUpdateError(message)
    session.expire_all()
