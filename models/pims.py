from __future__ import annotations

from datetime import date, datetime
from typing import Optional
import uuid
from sqlmodel import SQLModel, Field


class PunchChild(SQLModel, table=True):
    """登降園・ピムス連携システム 園児マスタテーブル"""
    __tablename__ = "punch_children"

    child_id: str = Field(primary_key=True, max_length=64, description="園児ID（QR値、出席番号、自動採番ID）")
    name: str = Field(max_length=100, nullable=False, description="漢字氏名")
    kana: Optional[str] = Field(default=None, max_length=100, description="名前(かな)")
    birth_date: Optional[date] = Field(default=None, description="生年月日")
    class_name: str = Field(default="未設定", max_length=50, nullable=False, description="所属クラス（タブ表示用）")
    family_id: Optional[str] = Field(default=None, max_length=64, index=True, description="世帯ID（兄弟判定キー）")
    parent_email: Optional[str] = Field(default=None, max_length=255, description="保護者メール")
    sort_order: Optional[int] = Field(default=0, description="表示順")
    is_active: bool = Field(default=True, nullable=False, description="有効フラグ")


class PunchLog(SQLModel, table=True):
    """登降園・ピムス連携システム 打刻・出欠トランザクションテーブル"""
    __tablename__ = "punch_logs"

    log_id: str = Field(default_factory=lambda: str(uuid.uuid4()), primary_key=True, max_length=64, description="ログID")
    child_id: str = Field(foreign_key="punch_children.child_id", index=True, max_length=64, description="園児ID")
    punched_at: datetime = Field(nullable=False, index=True, description="打刻日時（JST）")
    punch_type: str = Field(max_length=20, nullable=False, description="区分: 登園 / 降園 / 欠席")
    absence_reason: Optional[str] = Field(default=None, max_length=20, description="欠席事由: 病欠等 / 都合 / 災害 / NULL")
    is_auto_filled: bool = Field(default=False, nullable=False, description="押し忘れ自動補完フラグ")

