"""通知イベントハブ（改善案6）。

「お知らせ・アンケートなどすべての更新を自動通知する機能はありません」状態を
解消するため、園内の更新イベントを既存の通知配信基盤
（ParentNotification + ParentNotificationDelivery / parent_push_service）へ
一元的に流すハブ。

設計方針:
- 1イベント = 1関数。呼び出し側はハブの関数を呼ぶだけでよい
- 配信先の解決は既存の ParentChildLink / ParentAccount に任せる
- 同一 source に対する二重通知は冪等に排除する（source_type + source_id + kind）
- in_app は即時 delivered、push は既存 worker が処理する pending でキューイング
- 例外は握り潰さず呼び出し側に伝播させる（トランザクションは呼び出し側が commit）
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Sequence

from sqlmodel import Session, select

from models import (
    Child,
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
    ParentPushPreference,
)


class NotificationHubError(Exception):
    pass


def _linked_active_parents(
    session: Session,
    *,
    child_ids: Sequence[int] | None = None,
    classroom_ids: Sequence[int] | None = None,
) -> list[ParentAccount]:
    """対象園児／クラスに紐づく有効な保護者アカウントを返す。

    - child_ids が指定されていればその園児の保護者
    - 無ければ classroom_ids（指定があれば）に所属する園児の保護者
    - いずれも無ければ全有効保護者（全保護者向けお知らせ等）
    """
    query = (
        select(ParentAccount)
        .join(ParentChildLink, ParentChildLink.parent_account_id == ParentAccount.id)
        .where(ParentAccount.status == ParentAccountStatus.active)
        .distinct()
    )
    if child_ids:
        query = query.where(ParentChildLink.child_id.in_(child_ids))  # type: ignore[attr-defined]
    elif classroom_ids:
        classroom_children = session.exec(
            select(Child.id).where(Child.classroom_id.in_(classroom_ids))  # type: ignore[attr-defined]
        ).all()
        if not classroom_children:
            return []
        query = query.where(ParentChildLink.child_id.in_(classroom_children))  # type: ignore[attr-defined]
    return list(session.exec(query.order_by(ParentAccount.id)).all())


def _notification_exists(
    session: Session,
    *,
    parent_account_id: int,
    kind: ParentNotificationKind,
    source_type: str,
    source_id: str,
) -> bool:
    existing = session.exec(
        select(ParentNotification.id).where(
            ParentNotification.parent_account_id == parent_account_id,
            ParentNotification.kind == kind,
            ParentNotification.source_type == source_type,
            ParentNotification.source_id == source_id,
        )
    ).first()
    return existing is not None


# 通知種別と ParentPushPreference のミュート列の対応（改善案6 後続）。
# 値が None の種別はミュート設定の対象外（常に配信）。
_PREFERENCE_MUTE_COLUMNS: dict[ParentNotificationKind, str | None] = {
    ParentNotificationKind.closure_notice: "closure_notice_enabled",
    ParentNotificationKind.emergency_notice: "emergency_notice_enabled",
    ParentNotificationKind.punch_correction_notice: "punch_correction_notice_enabled",
    ParentNotificationKind.attendance_confirmation_request: "attendance_confirmation_enabled",
    ParentNotificationKind.notice_published: None,
    ParentNotificationKind.survey_published: None,
    ParentNotificationKind.fever_notification: None,
    ParentNotificationKind.push_test: None,
}


def _is_muted(session: Session, *, parent_account_id: int, kind: ParentNotificationKind) -> bool:
    """保護者ごとの通知種別ミュートを判定する（ParentPushPreference 流用）。"""
    column = _PREFERENCE_MUTE_COLUMNS.get(kind)
    if column is None:
        return False
    preference = session.exec(
        select(ParentPushPreference).where(ParentPushPreference.parent_account_id == parent_account_id)
    ).first()
    if preference is None:
        return False
    if kind is ParentNotificationKind.attendance_confirmation_request:
        return not preference.attendance_confirmation_enabled
    return not getattr(preference, column)


def _create_notification(
    session: Session,
    *,
    parent_account_id: int,
    child_id: int | None,
    kind: ParentNotificationKind,
    title: str,
    body: str,
    action_url: str | None,
    source_type: str,
    source_id: str,
    created_by_name: str | None,
    created_at: datetime,
    target_date: date | None = None,
) -> ParentNotification:
    notification = ParentNotification(
        parent_account_id=parent_account_id,
        child_id=child_id,
        kind=kind,
        title=title,
        body=body,
        action_url=action_url,
        target_date=target_date,
        source_type=source_type,
        source_id=source_id,
        created_by_name=created_by_name,
        created_at=created_at,
    )
    session.add(notification)
    session.flush()
    session.add(ParentNotificationDelivery(
        notification_id=notification.id,
        channel=NotificationDeliveryChannel.in_app,
        status=NotificationDeliveryStatus.delivered,
        attempted_at=created_at,
        delivered_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    ))
    # push は既存のワーカー経由。キューイング失敗でも in_app 配信は生きる。
    try:
        from parent_notification_service import queue_push_delivery
        queue_push_delivery(session, notification, now=created_at)
    except Exception:  # noqa: BLE001 - push キュー失敗は通知本体を阻害しない
        pass
    return notification


def notify_notice_published(
    session: Session,
    *,
    notice_id: int,
    title: str,
    target_classroom_ids: Sequence[int],
    target_child_ids: Sequence[int],
    created_by_name: str | None = None,
    now: datetime | None = None,
) -> list[ParentNotification]:
    """お知らせが公開されたときに、対象保護者へ in_app + push 通知を送る。"""
    from time_utils import utc_now

    created_at = now or utc_now()
    action_url = f"/parent-portal/notices?notice_id={notice_id}"
    body = f"新しいお知らせ「{title}」が公開されました。"

    parents = _linked_active_parents(
        session,
        child_ids=list(target_child_ids) or None,
        classroom_ids=list(target_classroom_ids) or None,
    )
    created: list[ParentNotification] = []
    for parent in parents:
        if parent.id is None:
            continue
        if _notification_exists(
            session, parent_account_id=parent.id,
            kind=ParentNotificationKind.notice_published,
            source_type="notice", source_id=str(notice_id),
        ):
            continue
        created.append(_create_notification(
            session,
            parent_account_id=parent.id,
            child_id=None,
            kind=ParentNotificationKind.notice_published,
            title="新しいお知らせ",
            body=body,
            action_url=action_url,
            source_type="notice",
            source_id=str(notice_id),
            created_by_name=created_by_name,
            created_at=created_at,
        ))
    return created


def notify_survey_published(
    session: Session,
    *,
    survey_id: int,
    title: str,
    closes_at: datetime | None = None,
    audience_child_ids: Sequence[int] | None = None,
    audience_classroom_ids: Sequence[int] | None = None,
    created_by_name: str | None = None,
    now: datetime | None = None,
) -> list[ParentNotification]:
    """保護者向けアンケートが公開されたときに、対象保護者へ通知を送る。"""
    from time_utils import utc_now

    created_at = now or utc_now()
    action_url = f"/parent-portal/surveys?survey_id={survey_id}"
    deadline = f"（{closes_at:%m/%d %H:%M}まで）" if closes_at else ""
    body = f"新しいアンケート「{title}」への回答をお願いします{deadline}。"

    parents = _linked_active_parents(
        session,
        child_ids=list(audience_child_ids) if audience_child_ids else None,
        classroom_ids=list(audience_classroom_ids) if audience_classroom_ids else None,
    )
    created: list[ParentNotification] = []
    for parent in parents:
        if parent.id is None:
            continue
        if _notification_exists(
            session, parent_account_id=parent.id,
            kind=ParentNotificationKind.survey_published,
            source_type="survey", source_id=str(survey_id),
        ):
            continue
        created.append(_create_notification(
            session,
            parent_account_id=parent.id,
            child_id=None,
            kind=ParentNotificationKind.survey_published,
            title="アンケートのお願い",
            body=body,
            action_url=action_url,
            source_type="survey",
            source_id=str(survey_id),
            created_by_name=created_by_name,
            created_at=created_at,
        ))
    return created


def notify_families(
    session: Session,
    *,
    kind: ParentNotificationKind,
    source_type: str,
    source_id: str,
    title: str,
    body: str,
    action_url: str | None = None,
    target_child_ids: Sequence[int] | None = None,
    target_classroom_ids: Sequence[int] | None = None,
    created_by_name: str | None = None,
    now: datetime | None = None,
    force_push: bool = False,
) -> list[ParentNotification]:
    """休園・緊急連絡・打刻訂正など、汎用的な家庭向け通知（改善案6 後続）。

    - kind は closure_notice / emergency_notice / punch_correction_notice を想定
    - emergency_notice は保護者の push ミュート設定を無視する（force_push=True 推奨）
    - ミュートされた保護者には in_app のみ配信し push を作らない
    """
    from time_utils import utc_now

    if kind not in {
        ParentNotificationKind.closure_notice,
        ParentNotificationKind.emergency_notice,
        ParentNotificationKind.punch_correction_notice,
    }:
        raise NotificationHubError(f"notify_families は {kind} をサポートしません")

    created_at = now or utc_now()
    parents = _linked_active_parents(
        session,
        child_ids=list(target_child_ids) if target_child_ids else None,
        classroom_ids=list(target_classroom_ids) if target_classroom_ids else None,
    )
    created: list[ParentNotification] = []
    for parent in parents:
        if parent.id is None:
            continue
        if _notification_exists(
            session, parent_account_id=parent.id, kind=kind,
            source_type=source_type, source_id=source_id,
        ):
            continue
        if _is_muted(session, parent_account_id=parent.id, kind=kind) and not force_push:
            # push は作らず in_app のみ（_create_notification を使わず手配信）
            notification = ParentNotification(
                parent_account_id=parent.id, child_id=None, kind=kind,
                title=title, body=body, action_url=action_url,
                source_type=source_type, source_id=source_id,
                created_by_name=created_by_name, created_at=created_at,
            )
            session.add(notification)
            session.flush()
            session.add(ParentNotificationDelivery(
                notification_id=notification.id,
                channel=NotificationDeliveryChannel.in_app,
                status=NotificationDeliveryStatus.delivered,
                attempted_at=created_at, delivered_at=created_at,
                created_at=created_at, updated_at=created_at,
            ))
            created.append(notification)
            continue
        created.append(_create_notification(
            session,
            parent_account_id=parent.id, child_id=None, kind=kind,
            title=title, body=body, action_url=action_url,
            source_type=source_type, source_id=source_id,
            created_by_name=created_by_name, created_at=created_at,
        ))
    return created
