"""テナント・組織コンテキスト管理（Phase 4: マルチテナント・法人組織階層）。

FastAPI リクエストスコープやバックグラウンドタスクにおいて、現在アクセス中の
法人ID（Organization ID）および施設ID（Facility ID）を ContextVar で安全に分離・管理する。
コンテキスト未設定時は単一園環境用デフォルト識別子へ自動フォールバックし、後方互換性を保証する。
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Generator, Optional
from uuid import UUID

from models.organization import DEFAULT_FACILITY_ID, DEFAULT_ORGANIZATION_ID

_current_organization_id: contextvars.ContextVar[Optional[UUID]] = contextvars.ContextVar(
    "current_organization_id", default=None
)
_current_facility_id: contextvars.ContextVar[Optional[UUID]] = contextvars.ContextVar(
    "current_facility_id", default=None
)


def get_current_organization_id() -> UUID:
    """現在のアクティブな法人IDを取得する。未指定時はデフォルト法人IDを返す。"""
    org_id = _current_organization_id.get()
    return org_id if org_id is not None else DEFAULT_ORGANIZATION_ID


def get_current_facility_id() -> UUID:
    """現在のアクティブな施設IDを取得する。未指定時はデフォルト施設IDを返す。"""
    fac_id = _current_facility_id.get()
    return fac_id if fac_id is not None else DEFAULT_FACILITY_ID


def set_tenant_context(
    organization_id: Optional[UUID] = None,
    facility_id: Optional[UUID] = None,
) -> tuple[contextvars.Token[Optional[UUID]], contextvars.Token[Optional[UUID]]]:
    """コンテキスト変数を設定し、復元用トークンを返す。"""
    t_org = _current_organization_id.set(organization_id)
    t_fac = _current_facility_id.set(facility_id)
    return t_org, t_fac


def reset_tenant_context(
    tokens: tuple[contextvars.Token[Optional[UUID]], contextvars.Token[Optional[UUID]]]
) -> None:
    """コンテキスト変数をトークンに基づき元に戻す。"""
    t_org, t_fac = tokens
    _current_organization_id.reset(t_org)
    _current_facility_id.reset(t_fac)


@contextmanager
def tenant_scope(
    organization_id: Optional[UUID] = None,
    facility_id: Optional[UUID] = None,
) -> Generator[None, None, None]:
    """指定した法人・施設スコープで処理を実行するコンテキストマネージャ。"""
    tokens = set_tenant_context(organization_id, facility_id)
    try:
        yield
    finally:
        reset_tenant_context(tokens)


class TenantContext:
    """オブジェクト指向スタイルでスコープを扱うヘルパー。"""

    def __init__(
        self,
        organization_id: Optional[UUID] = None,
        facility_id: Optional[UUID] = None,
    ) -> None:
        self.organization_id = organization_id
        self.facility_id = facility_id
        self._tokens: Optional[
            tuple[contextvars.Token[Optional[UUID]], contextvars.Token[Optional[UUID]]]
        ] = None

    def __enter__(self) -> TenantContext:
        self._tokens = set_tenant_context(self.organization_id, self.facility_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._tokens is not None:
            reset_tenant_context(self._tokens)
            self._tokens = None
