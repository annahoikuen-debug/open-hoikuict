"""お知らせ（Notice）領域のモデル。

`models.py` から領域別に切り出した第1弾（改善案7 / 15ステップ計画 Step 13）。
公開名は `models/__init__.py` 経由で `from models import X` として引き続き使える。
"""
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, List, Optional

from sqlmodel import Field, Relationship, SQLModel, UniqueConstraint

from time_utils import utc_now

if TYPE_CHECKING:  # 領域別分割モジュールとの循環 import を避ける（文字列注釈用）
    from models.core import ParentAccount  # noqa: F401


class NoticeStatus(str, Enum):
    draft = "draft"
    pending_approval = "pending_approval"
    published = "published"

    @property
    def label(self) -> str:
        return {
            self.draft: "下書き",
            self.pending_approval: "承認待ち",
            self.published: "公開中",
        }[self]


class NoticePriority(str, Enum):
    normal = "normal"
    high = "high"

    @property
    def label(self) -> str:
        return {
            self.normal: "通常",
            self.high: "重要",
        }[self]


class NoticeTargetType(str, Enum):
    all = "all"
    classroom = "classroom"
    child = "child"

    @property
    def label(self) -> str:
        return {
            self.all: "全保護者",
            self.classroom: "クラス",
            self.child: "園児",
        }[self]


class Notice(SQLModel, table=True):
    __tablename__ = "notices"

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    body: str
    body_html: Optional[str] = None
    priority: NoticePriority = Field(default=NoticePriority.normal)
    status: NoticeStatus = Field(default=NoticeStatus.draft)
    publish_start_at: Optional[datetime] = None
    publish_end_at: Optional[datetime] = None
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    lock_version: int = Field(default=1)

    targets: List["NoticeTarget"] = Relationship(back_populates="notice")
    reads: List["NoticeRead"] = Relationship(back_populates="notice")
    attachments: List["NoticeAttachment"] = Relationship(back_populates="notice")
    workflow_actions: List["NoticeWorkflowAction"] = Relationship(back_populates="notice")


class NoticeAttachment(SQLModel, table=True):
    __tablename__ = "notice_attachments"

    id: Optional[int] = Field(default=None, primary_key=True)
    notice_id: int = Field(foreign_key="notices.id", index=True)
    original_filename: str
    storage_path: str
    content_type: str
    file_size: int = Field(default=0)
    is_image: bool = Field(default=False)
    display_size: str = Field(default="medium", max_length=16)
    display_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)

    notice: Optional[Notice] = Relationship(back_populates="attachments")


class NoticeWorkflowAction(SQLModel, table=True):
    __tablename__ = "notice_workflow_actions"

    id: Optional[int] = Field(default=None, primary_key=True)
    notice_id: int = Field(foreign_key="notices.id", index=True)
    action: str = Field(index=True, max_length=32)
    actor_ref: Optional[str] = Field(default=None, max_length=64)
    actor_name: str = Field(max_length=100)
    comment: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now, index=True)

    notice: Optional[Notice] = Relationship(back_populates="workflow_actions")

    @property
    def action_label(self) -> str:
        return {
            "submitted": "承認申請",
            "approved": "承認・公開",
            "rejected": "差戻し",
            "cancelled": "申請取消",
            "unpublished": "公開停止・下書き化",
        }.get(self.action, self.action)


class NoticeTarget(SQLModel, table=True):
    __tablename__ = "notice_targets"

    id: Optional[int] = Field(default=None, primary_key=True)
    notice_id: int = Field(foreign_key="notices.id", index=True)
    target_type: NoticeTargetType = Field(default=NoticeTargetType.all)
    target_value: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)

    notice: Optional[Notice] = Relationship(back_populates="targets")


class NoticeRead(SQLModel, table=True):
    __tablename__ = "notice_reads"
    __table_args__ = (UniqueConstraint("notice_id", "parent_account_id", name="uq_notice_parent_read"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    notice_id: int = Field(foreign_key="notices.id", index=True)
    parent_account_id: int = Field(foreign_key="parent_accounts.id", index=True)
    read_at: datetime = Field(default_factory=utc_now)

    notice: Optional[Notice] = Relationship(back_populates="reads")
    parent_account: Optional["ParentAccount"] = Relationship(back_populates="notice_reads")
