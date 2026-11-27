"""Dialect-aware write locking helpers for SQLite and PostgreSQL."""

from __future__ import annotations

from sqlmodel import Session


def acquire_write_lock(session: Session) -> None:
    """Acquire an immediate write lock on SQLite when not already in a transaction.

    On PostgreSQL or other MVCC backends, row-level locking (e.g. ``with_for_update``)
    handles concurrency without escalating to a database-wide write lock.
    """
    bind = session.get_bind()
    if bind is None or bind.dialect.name != "sqlite":
        return
    conn = session.connection()
    if not conn.in_transaction():
        conn.exec_driver_sql("BEGIN IMMEDIATE")
