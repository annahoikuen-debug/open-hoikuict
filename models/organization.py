"""組織および施設データモデル（Phase 4: マルチテナント・法人組織階層）。

社会福祉法人や運営企業などの「法人（Organization）」と、その傘下に属する
各「施設・園（Facility）」の階層関係を定義する。
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import Field, Relationship, SQLModel

from models.core import utc_now

# 後方互換性および単一園環境用デフォルト識別子
DEFAULT_ORGANIZATION_ID = UUID("00000000-0000-0000-0000-000000000001")
DEFAULT_FACILITY_ID = UUID("00000000-0000-0000-0000-000000000002")


class Organization(SQLModel, table=True):
    """法人（テナント最上位エンティティ）。"""

    __tablename__ = "organizations"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True, description="法人名（例: 社会福祉法人ひかり会）")
    code: str = Field(unique=True, index=True, description="法人コード（例: HIKARI）")
    description: Optional[str] = Field(default=None, description="法人備考")
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Facility(SQLModel, table=True):
    """施設・園（法人傘下の各拠点）。"""

    __tablename__ = "facilities"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    organization_id: UUID = Field(
        default=DEFAULT_ORGANIZATION_ID,
        foreign_key="organizations.id",
        index=True,
        description="所属法人ID",
    )
    name: str = Field(index=True, description="施設名（例: ひかり保育園）")
    code: str = Field(index=True, description="施設コード（例: HIKARI-01）")
    facility_type: str = Field(default="licensed_nursery", description="施設種別（認可、小規模、企業主導型など）")
    postal_code: Optional[str] = Field(default=None, max_length=8)
    address: Optional[str] = Field(default=None)
    phone_number: Optional[str] = Field(default=None, max_length=20)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


def get_default_organization() -> Organization:
    """単一園またはマイグレーション用デフォルト法人インスタンスを返す。"""
    return Organization(
        id=DEFAULT_ORGANIZATION_ID,
        name=os.getenv("HOIKUICT_DEFAULT_ORG_NAME", "デフォルト法人"),
        code="DEFAULT-ORG",
        description="システム自動生成の既定法人",
    )


def get_default_facility() -> Facility:
    """単一園またはマイグレーション用デフォルト施設インスタンスを返す。"""
    return Facility(
        id=DEFAULT_FACILITY_ID,
        organization_id=DEFAULT_ORGANIZATION_ID,
        name=os.getenv("HOIKUICT_DEFAULT_FACILITY_NAME", "デフォルト保育園"),
        code="DEFAULT-FACILITY",
    )
