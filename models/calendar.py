"""Domain models extracted from models/core.py."""

from datetime import datetime
from enum import Enum
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, CheckConstraint, Index, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from time_utils import utc_now

if TYPE_CHECKING:
    from models.core import Child, Family, User  # noqa: F401


class EventSeriesMemberTargetType(str, Enum):
    event = "event"
    survey = "survey"
    meeting_note = "meeting_note"


class CalendarMemberRole(str, Enum):
    owner = "owner"
    editor = "editor"
    viewer = "viewer"

    @property
    def label(self) -> str:
        return {
            self.owner: "管理者",
            self.editor: "編集可",
            self.viewer: "閲覧のみ",
        }[self]


class CalendarType(str, Enum):
    staff_personal = "staff_personal"
    facility_shared = "facility_shared"

    @property
    def label(self) -> str:
        return {
            self.staff_personal: "個人カレンダー",
            self.facility_shared: "施設共用カレンダー",
        }[self]


class RecurrenceFrequency(str, Enum):
    daily = "daily"
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"

    @property
    def label(self) -> str:
        return {
            self.daily: "毎日",
            self.weekly: "毎週",
            self.monthly: "毎月",
            self.yearly: "毎年",
        }[self]


class EventKind(str, Enum):
    single = "single"
    series_master = "series_master"


class EventVisibility(str, Enum):
    normal = "normal"
    private = "private"

    @property
    def label(self) -> str:
        return {
            self.normal: "通常",
            self.private: "非公開",
        }[self]


class EventLifecycleStatus(str, Enum):
    confirmed = "confirmed"
    cancelled = "cancelled"


class ReminderMethod(str, Enum):
    in_app = "in_app"


class CalendarActivityKind(str, Enum):
    calendar_created = "calendar_created"
    calendar_updated = "calendar_updated"
    share_synced = "share_synced"
    event_created = "event_created"
    event_updated = "event_updated"
    event_deleted = "event_deleted"
    event_moved = "event_moved"
    event_resized = "event_resized"


class EventSeries(SQLModel, table=True):
    __tablename__ = "event_series"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=100, index=True)
    description: Optional[str] = None
    is_active: bool = Field(default=True, index=True)
    created_by_user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class EventSeriesMember(SQLModel, table=True):
    __tablename__ = "event_series_members"
    __table_args__ = (
        UniqueConstraint("target_type", "target_id", name="uq_series_member_target"),
        Index("ix_series_members_series_year", "series_id", "fiscal_year"),
        CheckConstraint(
            "fiscal_year BETWEEN 1900 AND 2100",
            name="ck_series_member_fiscal_year",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    series_id: int = Field(foreign_key="event_series.id", index=True)
    target_type: EventSeriesMemberTargetType = Field(index=True)
    target_id: str = Field(index=True)
    fiscal_year: int = Field(index=True)
    created_by_user_id: Optional[uuid.UUID] = Field(default=None, foreign_key="users.id")
    created_by: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)


class Calendar(SQLModel, table=True):
    __tablename__ = "calendars"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    owner_user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    name: str = Field(max_length=100)
    calendar_type: CalendarType = Field(default=CalendarType.staff_personal)
    color: str = Field(default="#2563EB", max_length=16)
    description: Optional[str] = Field(default=None)
    is_primary: bool = Field(default=False)
    is_archived: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CalendarMember(SQLModel, table=True):
    __tablename__ = "calendar_members"
    __table_args__ = (UniqueConstraint("calendar_id", "user_id", name="uq_calendar_member"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    calendar_id: uuid.UUID = Field(foreign_key="calendars.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    role: CalendarMemberRole = Field(default=CalendarMemberRole.viewer)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CalendarUserPreference(SQLModel, table=True):
    __tablename__ = "calendar_user_preferences"
    __table_args__ = (UniqueConstraint("calendar_id", "user_id", name="uq_calendar_user_preference"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    calendar_id: uuid.UUID = Field(foreign_key="calendars.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    is_visible: bool = Field(default=True)
    display_order: int = Field(default=0)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CalendarActivityLog(SQLModel, table=True):
    __tablename__ = "calendar_activity_logs"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    calendar_id: uuid.UUID = Field(foreign_key="calendars.id", index=True)
    actor_user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    actor_name: str = Field(max_length=100)
    action: CalendarActivityKind = Field(index=True)
    summary: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=utc_now, index=True)


class RecurrenceRule(SQLModel, table=True):
    __tablename__ = "recurrence_rules"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    freq: RecurrenceFrequency = Field(default=RecurrenceFrequency.weekly)
    interval: int = Field(default=1)
    by_weekday: Optional[str] = Field(default=None, max_length=32)
    by_month_day: Optional[str] = Field(default=None, max_length=32)
    count: Optional[int] = Field(default=None)
    until_at: Optional[datetime] = Field(default=None)
    timezone: str = Field(default="Asia/Tokyo", max_length=64)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    calendar_id: uuid.UUID = Field(foreign_key="calendars.id", index=True)
    created_by_user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    kind: EventKind = Field(default=EventKind.single)
    title: str = Field(max_length=200)
    description: Optional[str] = Field(default=None)
    location: Optional[str] = Field(default=None, max_length=255)
    start_at: datetime = Field(index=True)
    end_at: datetime = Field(index=True)
    timezone: str = Field(default="Asia/Tokyo", max_length=64)
    is_all_day: bool = Field(default=False)
    visibility: EventVisibility = Field(default=EventVisibility.normal)
    status: EventLifecycleStatus = Field(default=EventLifecycleStatus.confirmed)
    recurrence_rule_id: Optional[uuid.UUID] = Field(default=None, foreign_key="recurrence_rules.id")
    split_from_event_id: Optional[uuid.UUID] = Field(default=None, foreign_key="events.id")
    split_from_original_start_at: Optional[datetime] = Field(default=None)
    is_deleted: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class CalendarImportSource(SQLModel, table=True):
    __tablename__ = "calendar_import_sources"
    __table_args__ = (UniqueConstraint("calendar_id", "source_key", name="uq_calendar_import_source"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    calendar_id: uuid.UUID = Field(foreign_key="calendars.id", index=True)
    source_key: str = Field(max_length=64)
    event_id: uuid.UUID = Field(foreign_key="events.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)


class CalendarImportBatch(SQLModel, table=True):
    __tablename__ = "calendar_import_batches"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    calendar_id: uuid.UUID = Field(foreign_key="calendars.id", index=True)
    items: list[dict] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    expires_at: datetime = Field(index=True)
    used_at: Optional[datetime] = None


class EventOverride(SQLModel, table=True):
    __tablename__ = "event_overrides"
    __table_args__ = (UniqueConstraint("series_event_id", "original_start_at", name="uq_event_override"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    series_event_id: uuid.UUID = Field(foreign_key="events.id", index=True)
    original_start_at: datetime = Field(index=True)
    title: Optional[str] = Field(default=None, max_length=200)
    description: Optional[str] = Field(default=None)
    location: Optional[str] = Field(default=None, max_length=255)
    start_at: Optional[datetime] = Field(default=None)
    end_at: Optional[datetime] = Field(default=None)
    timezone: Optional[str] = Field(default=None, max_length=64)
    is_all_day: Optional[bool] = Field(default=None)
    visibility: Optional[EventVisibility] = Field(default=None)
    is_cancelled: bool = Field(default=False)
    created_by_user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class Reminder(SQLModel, table=True):
    __tablename__ = "reminders"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "user_id",
            "method",
            "minutes_before",
            name="uq_event_user_reminder",
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    event_id: uuid.UUID = Field(foreign_key="events.id", index=True)
    user_id: uuid.UUID = Field(foreign_key="users.id", index=True)
    method: ReminderMethod = Field(default=ReminderMethod.in_app)
    minutes_before: int = Field(default=10)
    is_deleted: bool = Field(default=False, index=True)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
