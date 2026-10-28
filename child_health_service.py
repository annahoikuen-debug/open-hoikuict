from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Iterable, Optional

from sqlmodel import Session, select

from models import (
    AllergenCategory,
    AllergySeverity,
    Child,
    ChildAllergy,
    ChildHealthProfile,
    ChildSex,
    HealthCheckRecord,
    HealthCheckType,
    NotificationDeliveryChannel,
    NotificationDeliveryStatus,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentNotification,
    ParentNotificationDelivery,
    ParentNotificationKind,
)
from parent_notification_service import queue_push_delivery
from time_utils import local_today, utc_now

GRAPH_CHECK_TYPES = {HealthCheckType.entrance, HealthCheckType.periodic}

# 厚生労働省 乳幼児身体発育標準曲線（2010）の概算参考値（目安）。
# 各エントリ: (か月齢, 平均値, 標準偏差)。0-72か月、線形補間で評価する。
GROWTH_STANDARDS: dict[ChildSex, dict[str, list[tuple[float, float, float]]]] = {
    ChildSex.male: {
        "height": [
            (0, 49.8, 4.5), (3, 60.9, 4.2), (6, 67.6, 4.0), (9, 72.0, 3.8),
            (12, 75.7, 3.7), (18, 81.7, 3.6), (24, 87.0, 3.5), (30, 91.0, 3.5),
            (36, 96.1, 3.5), (42, 100.8, 3.6), (48, 105.6, 3.7), (54, 109.8, 3.8),
            (60, 114.3, 4.0), (66, 118.0, 4.2), (72, 121.9, 4.4),
        ],
        "weight": [
            (0, 3.1, 0.8), (3, 6.3, 0.9), (6, 7.9, 1.0), (9, 8.9, 1.1),
            (12, 9.5, 1.1), (18, 10.9, 1.2), (24, 12.4, 1.3), (30, 13.3, 1.3),
            (36, 14.2, 1.4), (42, 15.3, 1.5), (48, 16.5, 1.6), (54, 17.4, 1.6),
            (60, 18.4, 1.7), (66, 19.3, 1.8), (72, 20.3, 1.9),
        ],
    },
    ChildSex.female: {
        "height": [
            (0, 49.1, 4.4), (3, 59.7, 4.1), (6, 65.7, 3.9), (9, 70.1, 3.7),
            (12, 74.0, 3.6), (18, 80.1, 3.5), (24, 85.6, 3.4), (30, 89.9, 3.4),
            (36, 95.0, 3.4), (42, 99.4, 3.5), (48, 104.3, 3.6), (54, 108.2, 3.7),
            (60, 112.9, 3.9), (66, 116.4, 4.1), (72, 120.4, 4.3),
        ],
        "weight": [
            (0, 3.0, 0.7), (3, 5.8, 0.8), (6, 7.3, 0.9), (9, 8.2, 1.0),
            (12, 8.9, 1.0), (18, 10.2, 1.1), (24, 11.8, 1.2), (30, 12.8, 1.2),
            (36, 13.9, 1.3), (42, 14.9, 1.4), (48, 16.0, 1.5), (54, 16.9, 1.5),
            (60, 17.8, 1.6), (66, 18.7, 1.7), (72, 19.7, 1.8),
        ],
    },
}


def _interpolate_standard(table: list[tuple[float, float, float]], months: float) -> tuple[float, float]:
    if months <= table[0][0]:
        return table[0][1], table[0][2]
    if months >= table[-1][0]:
        return table[-1][1], table[-1][2]
    for i in range(len(table) - 1):
        m0, mean0, sd0 = table[i]
        m1, mean1, sd1 = table[i + 1]
        if m0 <= months <= m1:
            t = (months - m0) / (m1 - m0) if m1 > m0 else 0.0
            return mean0 + (mean1 - mean0) * t, sd0 + (sd1 - sd0) * t
    return table[-1][1], table[-1][2]


def _growth_deviation_label(
    child: Child,
    attribute: str,
    value: float,
    measured_at: date,
) -> Optional[str]:
    if child.sex not in (ChildSex.male, ChildSex.female):
        return None
    months = (measured_at - child.birth_date).days / 30.44
    if months < 0 or months > 72:
        return None
    table = GROWTH_STANDARDS[child.sex][attribute]
    mean, sd = _interpolate_standard(table, months)
    if sd <= 0:
        return None
    z_score = (value - mean) / sd
    attr_label = "身長" if attribute == "height" else "体重"
    if z_score >= 2.0:
        return f"{attr_label}偏位（高／+2SD以上）"
    if z_score <= -2.0:
        return f"{attr_label}偏位（低／-2SD以下）"
    return None


def build_growth_deviation_labels(
    child: Optional[Child],
    records: Iterable[HealthCheckRecord],
) -> list[str]:
    labels: list[str] = []
    if child is None:
        return labels
    graph_records = [
        record
        for record in records
        if record.check_type in GRAPH_CHECK_TYPES
        and (record.height_cm is not None or record.weight_kg is not None)
    ]
    if not graph_records:
        return labels
    latest = max(graph_records, key=lambda record: record.checked_at)
    if latest.height_cm is not None:
        label = _growth_deviation_label(child, "height", latest.height_cm, latest.checked_at)
        if label:
            labels.append(label)
    if latest.weight_kg is not None:
        label = _growth_deviation_label(child, "weight", latest.weight_kg, latest.checked_at)
        if label:
            labels.append(label)
    return labels


def notify_fever_to_guardians(
    session: Session,
    *,
    child: Child,
    record: HealthCheckRecord,
    created_by_name: str,
    now: Optional[datetime] = None,
) -> list[ParentNotification]:
    if child.id is None:
        return []
    created_at = now or utc_now()
    expires_at = created_at + timedelta(days=7)
    parent_accounts = session.exec(
        select(ParentAccount)
        .join(ParentChildLink, ParentChildLink.parent_account_id == ParentAccount.id)
        .where(
            ParentChildLink.child_id == child.id,
            ParentAccount.status == ParentAccountStatus.active,
        )
        .order_by(ParentChildLink.is_primary_contact.desc(), ParentAccount.id)
    ).all()

    notifications: list[ParentNotification] = []
    for parent_account in parent_accounts:
        if parent_account.id is None:
            continue
        notification = ParentNotification(
            parent_account_id=parent_account.id,
            child_id=child.id,
            kind=ParentNotificationKind.fever_notification,
            title="【発熱のお知らせ】",
            body=f"{child.full_name} さんの体温が {record.temperature:.1f}℃ でした（{record.checked_at.isoformat()}記録）。",
            action_url=f"/parent-portal/children/{child.id}/health",
            source_type="health_check_record",
            source_id=str(record.id),
            created_by_name=created_by_name,
            created_at=created_at,
        )
        session.add(notification)
        session.flush()
        session.add(
            ParentNotificationDelivery(
                notification_id=notification.id,
                channel=NotificationDeliveryChannel.in_app,
                status=NotificationDeliveryStatus.delivered,
                attempted_at=created_at,
                delivered_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
        )
        queue_push_delivery(
            session,
            notification,
            now=created_at,
            expires_at=expires_at,
        )
        from parent_notification_email_service import queue_notification_email

        queue_notification_email(session, notification, expires_at)
        notifications.append(notification)

    return notifications


def _normalized_legacy_allergy_names(extra_data: object) -> list[str]:
    if not isinstance(extra_data, dict):
        return []
    raw_value = extra_data.get("allergy", [])
    if isinstance(raw_value, str):
        candidates = raw_value.replace("、", ",").split(",")
    elif isinstance(raw_value, list):
        candidates = raw_value
    else:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def _normalized_legacy_medical_notes(extra_data: object) -> Optional[str]:
    if not isinstance(extra_data, dict):
        return None
    value = str(extra_data.get("medical_notes", "") or "").strip()
    return value or None


def get_child_health_profile(session: Session, child_id: int) -> Optional[ChildHealthProfile]:
    return session.exec(
        select(ChildHealthProfile).where(ChildHealthProfile.child_id == child_id)
    ).first()


def get_or_create_child_health_profile(
    session: Session,
    child: Child,
    *,
    actor_name: Optional[str] = None,
) -> ChildHealthProfile:
    profile = get_child_health_profile(session, child.id)
    if profile is not None:
        return profile

    now = utc_now()
    profile = ChildHealthProfile(
        child_id=child.id,
        medical_history=_normalized_legacy_medical_notes(child.extra_data),
        created_by=actor_name,
        updated_by=actor_name,
        created_at=now,
        updated_at=now,
    )
    session.add(profile)
    session.flush()
    return profile


def load_child_allergies(
    session: Session,
    child_id: int,
    *,
    include_inactive: bool = True,
) -> list[ChildAllergy]:
    statement = (
        select(ChildAllergy)
        .where(ChildAllergy.child_id == child_id)
        .order_by(ChildAllergy.is_active.desc(), ChildAllergy.updated_at.desc(), ChildAllergy.id.desc())
    )
    if not include_inactive:
        statement = statement.where(ChildAllergy.is_active.is_(True))
    return session.exec(statement).all()


def load_health_check_records(session: Session, child_id: int) -> list[HealthCheckRecord]:
    return session.exec(
        select(HealthCheckRecord)
        .where(HealthCheckRecord.child_id == child_id)
        .order_by(HealthCheckRecord.checked_at.desc(), HealthCheckRecord.updated_at.desc(), HealthCheckRecord.id.desc())
    ).all()


def load_health_profiles_for_children(
    session: Session,
    child_ids: list[int],
) -> dict[int, ChildHealthProfile]:
    if not child_ids:
        return {}
    profiles = session.exec(
        select(ChildHealthProfile).where(ChildHealthProfile.child_id.in_(child_ids))
    ).all()
    return {profile.child_id: profile for profile in profiles}


def load_allergies_for_children(
    session: Session,
    child_ids: list[int],
    *,
    include_inactive: bool = True,
) -> dict[int, list[ChildAllergy]]:
    if not child_ids:
        return {}
    statement = select(ChildAllergy).where(ChildAllergy.child_id.in_(child_ids)).order_by(
        ChildAllergy.is_active.desc(),
        ChildAllergy.updated_at.desc(),
        ChildAllergy.id.desc(),
    )
    if not include_inactive:
        statement = statement.where(ChildAllergy.is_active.is_(True))
    allergies = session.exec(statement).all()
    grouped: dict[int, list[ChildAllergy]] = {}
    for allergy in allergies:
        grouped.setdefault(allergy.child_id, []).append(allergy)
    return grouped


def load_health_checks_for_children(
    session: Session,
    child_ids: list[int],
) -> dict[int, list[HealthCheckRecord]]:
    if not child_ids:
        return {}
    records = session.exec(
        select(HealthCheckRecord)
        .where(HealthCheckRecord.child_id.in_(child_ids))
        .order_by(
            HealthCheckRecord.checked_at.desc(),
            HealthCheckRecord.updated_at.desc(),
            HealthCheckRecord.id.desc(),
        )
    ).all()
    grouped: dict[int, list[HealthCheckRecord]] = {}
    for record in records:
        grouped.setdefault(record.child_id, []).append(record)
    return grouped


def sync_health_records_from_legacy_extra_data(
    session: Session,
    child: Child,
    *,
    actor_name: Optional[str] = None,
) -> bool:
    profile = get_or_create_child_health_profile(session, child, actor_name=actor_name)
    now = utc_now()
    changed = False

    medical_notes = _normalized_legacy_medical_notes(child.extra_data)
    if profile.medical_history != medical_notes:
        profile.medical_history = medical_notes
        profile.updated_by = actor_name
        profile.updated_at = now
        session.add(profile)
        changed = True

    desired_names = _normalized_legacy_allergy_names(child.extra_data)
    if desired_names:
        if not profile.has_allergy:
            profile.has_allergy = True
            profile.updated_by = actor_name
            profile.updated_at = now
            session.add(profile)
            changed = True
        existing_allergies = load_child_allergies(session, child.id, include_inactive=True)
        existing_by_name: dict[str, list[ChildAllergy]] = {}
        for allergy in existing_allergies:
            key = allergy.allergen_name.strip()
            existing_by_name.setdefault(key, []).append(allergy)

        for name in desired_names:
            matches = existing_by_name.get(name, [])
            if matches:
                active_match = next((item for item in matches if item.is_active), None)
                if active_match is None:
                    allergy = matches[0]
                    allergy.is_active = True
                    allergy.updated_by = actor_name
                    allergy.updated_at = now
                    session.add(allergy)
                    changed = True
                continue

            session.add(
                ChildAllergy(
                    child_id=child.id,
                    allergen_category=AllergenCategory.other_food,
                    allergen_name=name,
                    severity=AllergySeverity.mild,
                    diagnosis_confirmed=False,
                    is_active=True,
                    created_by=actor_name,
                    updated_by=actor_name,
                    created_at=now,
                    updated_at=now,
                )
            )
            changed = True

    if changed:
        session.flush()
    return changed


def sync_child_extra_data_from_health_records(
    session: Session,
    child: Child,
    *,
    profile: Optional[ChildHealthProfile] = None,
    allergies: Optional[Iterable[ChildAllergy]] = None,
) -> bool:
    profile = profile or get_child_health_profile(session, child.id)
    active_allergies = list(allergies) if allergies is not None else load_child_allergies(
        session,
        child.id,
        include_inactive=False,
    )
    allergy_names = [allergy.allergen_name.strip() for allergy in active_allergies if allergy.allergen_name.strip()]
    extra_data = child.extra_data if isinstance(child.extra_data, dict) else {}
    normalized_extra_data = {
        **extra_data,
        "allergy": allergy_names,
        "medical_notes": (profile.medical_history if profile else None) or "",
    }
    if child.extra_data == normalized_extra_data:
        return False

    child.extra_data = normalized_extra_data
    child.updated_at = utc_now()
    session.add(child)
    session.flush()
    return True


def build_health_check_chart_records(
    records: Iterable[HealthCheckRecord],
    *,
    range_key: str = "1y",
) -> list[HealthCheckRecord]:
    today = local_today()
    since_date = today - timedelta(days=365) if range_key == "1y" else None

    filtered = [
        record
        for record in records
        if record.check_type in GRAPH_CHECK_TYPES and (since_date is None or record.checked_at >= since_date)
    ]
    return sorted(filtered, key=lambda item: (item.checked_at, item.check_type.value, item.id or 0))


def build_measurement_chart_payload(records: Iterable[HealthCheckRecord]) -> dict[str, list[object]]:
    ordered = list(records)
    return {
        "labels": [record.checked_at.isoformat() for record in ordered],
        "height_values": [record.height_cm for record in ordered],
        "weight_values": [record.weight_kg for record in ordered],
        "check_types": [record.check_type.label for record in ordered],
    }


def latest_measurement_summary(records: Iterable[HealthCheckRecord], attribute_name: str) -> dict[str, Optional[object]]:
    values = [
        (record.checked_at, getattr(record, attribute_name))
        for record in records
        if getattr(record, attribute_name) is not None
    ]
    if not values:
        return {"date": None, "value": None, "delta": None}

    latest_date, latest_value = values[-1]
    previous_value = values[-2][1] if len(values) > 1 else None
    delta = latest_value - previous_value if previous_value is not None else None
    return {"date": latest_date, "value": latest_value, "delta": delta}


def latest_health_check(records: Iterable[HealthCheckRecord]) -> Optional[HealthCheckRecord]:
    ordered = sorted(records, key=lambda item: (item.checked_at, item.updated_at, item.id or 0), reverse=True)
    return ordered[0] if ordered else None


def health_check_is_stale(records: Iterable[HealthCheckRecord], *, max_age_days: int = 180) -> bool:
    latest_record = latest_health_check(
        record for record in records if record.check_type in GRAPH_CHECK_TYPES
    )
    if latest_record is None:
        return True
    return (local_today() - latest_record.checked_at).days > max_age_days


def expired_allergy_count(allergies: Iterable[ChildAllergy], *, today: Optional[date] = None) -> int:
    target_day = today or local_today()
    return sum(1 for allergy in allergies if allergy.valid_until is not None and allergy.valid_until < target_day)


def has_priority_management_items(profile: Optional[ChildHealthProfile]) -> bool:
    if profile is None:
        return False
    return any(
        (
            profile.has_allergy,
            profile.has_epipen,
            profile.has_anaphylaxis,
            profile.has_febrile_seizure,
            profile.has_nursemaids_elbow,
            profile.has_medication,
            bool((profile.other_management_items or "").strip()),
        )
    )


def build_health_attention_labels(
    *,
    profile: Optional[ChildHealthProfile],
    allergies: Iterable[ChildAllergy],
    check_records: Iterable[HealthCheckRecord],
    child: Optional[Child] = None,
    today: Optional[date] = None,
) -> list[str]:
    labels: list[str] = []
    latest_record = latest_health_check(check_records)

    if profile and profile.has_allergy:
        labels.append("アレルギー")
    if profile and profile.has_epipen:
        labels.append("エピペン")
    if profile and profile.has_anaphylaxis:
        labels.append("アナフィラキシー")
    if profile and profile.has_febrile_seizure:
        labels.append("熱性けいれん")
    if profile and profile.has_nursemaids_elbow:
        labels.append("肘内障")
    if profile and profile.has_medication:
        labels.append("与薬")
    if profile and (profile.other_management_items or "").strip():
        labels.append("その他管理事項")
    if expired_allergy_count(allergies, today=today):
        labels.append("アレルギー期限切れ")
    if latest_record and latest_record.requires_followup:
        labels.append("要フォロー")
    if health_check_is_stale(check_records):
        labels.append("健診要確認")
    daily_temperatures = [
        record
        for record in check_records
        if record.check_type == HealthCheckType.daily and record.temperature is not None
    ]
    if daily_temperatures:
        latest_daily = max(daily_temperatures, key=lambda record: record.checked_at)
        if latest_daily.temperature >= 37.5:
            labels.append(f"発熱（{latest_daily.temperature:.1f}℃ / {latest_daily.checked_at.isoformat()}）")
    labels.extend(build_growth_deviation_labels(child, check_records))

    return labels
