from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Any
from uuid import uuid4

from sqlmodel import Session, select

from time_utils import utc_now
from .models import ChildRecordSettingVersion


PRESET_LABELS = {
    "simple": "シンプル",
    "standard": "標準",
    "detailed": "しっかり",
}

AGE_RULES = (
    ("age_0", "0歳児", 3),
    ("age_1", "1歳児", 3),
    ("age_2", "2歳児", 3),
    ("age_3", "3歳児", 3),
    ("age_4", "4歳児", 3),
    ("final_year", "最終年度児", 3),
)

FIELD_DEFINITIONS = (
    {
        "key": "observed_on",
        "label": "観察日・出来事の日",
        "input_type": "date",
        "system": True,
        "description": "実際に子どもの姿を見た日を記録します。",
    },
    {
        "key": "child_state",
        "label": "子どもの姿",
        "input_type": "long_text",
        "system": True,
        "description": "解釈だけでなく、言葉や行動などの具体的な姿を記録します。",
    },
    {
        "key": "caregiver_support",
        "label": "保育者の関わり",
        "input_type": "long_text",
        "description": "行った援助や環境の工夫、そのときの反応を記録します。",
    },
    {
        "key": "reflection",
        "label": "気付き・振り返り",
        "input_type": "long_text",
        "description": "記録から読み取れる育ちや気付きを記録します。",
    },
    {
        "key": "next_focus",
        "label": "次に意識したいこと",
        "input_type": "long_text",
        "description": "次に見守りたい姿や試したい関わりを記録します。",
    },
    {
        "key": "family_note",
        "label": "家庭との共有・連携",
        "input_type": "long_text",
        "description": "家庭から得た情報や共有したい内容を必要な範囲で記録します。",
    },
    {
        "key": "categories",
        "label": "記録区分",
        "input_type": "multi_select",
        "description": "後から探しやすくするための区分です。",
    },
    {
        "key": "perspective_tags",
        "label": "領域・視点",
        "input_type": "multi_select",
        "description": "該当する領域や視点を任意で選択します。",
    },
    {
        "key": "sensitivity",
        "label": "取扱区分",
        "input_type": "single_select",
        "system": True,
        "description": "閲覧範囲を制限する必要がある場合に設定します。",
    },
)

CATEGORY_OPTIONS = (
    "日常の姿",
    "成長・変化",
    "興味・遊び",
    "友達との関わり",
    "生活習慣",
    "健康・発達",
    "家庭との共有",
    "保育者の援助と反応",
    "配慮事項",
    "引継ぎ事項",
)

PERSPECTIVE_OPTIONS = (
    "健やかに伸び伸びと育つ",
    "身近な人と気持ちが通じ合う",
    "身近なものと関わり感性が育つ",
    "健康",
    "人間関係",
    "環境",
    "言葉",
    "表現",
)


def _enabled_keys(preset_key: str) -> set[str]:
    if preset_key == "simple":
        return {"observed_on", "child_state", "sensitivity"}
    if preset_key == "detailed":
        return {item["key"] for item in FIELD_DEFINITIONS}
    return {
        "observed_on",
        "child_state",
        "caregiver_support",
        "reflection",
        "next_focus",
        "categories",
        "perspective_tags",
        "sensitivity",
    }


def default_config(preset_key: str = "standard") -> dict[str, Any]:
    preset_key = preset_key if preset_key in PRESET_LABELS else "standard"
    enabled = _enabled_keys(preset_key)
    fields = []
    for order, definition in enumerate(FIELD_DEFINITIONS, start=1):
        item = deepcopy(definition)
        item.update(
            {
                "enabled": item["key"] in enabled,
                "required": item["key"] in {"observed_on", "child_state"},
                "order": order * 10,
            }
        )
        fields.append(item)
    return {
        "schema_version": "1",
        "preset_key": preset_key,
        "access_policy": {
            "progress_record_view_scope": "all_staff",
        },
        "age_rules": {
            key: {
                "child_progress_record": {
                    "schedule_type": "interval_months",
                    "interval_months": interval,
                    "anchor_month": 4,
                    "due_offset_days": 10,
                    "requires_approval": True,
                },
                "individual_plan": {
                    "schedule_type": "monthly" if key in {"age_0", "age_1", "age_2"} else "manual",
                    "requires_approval": True,
                },
            }
            for key, _, interval in AGE_RULES
        },
        "record_types": {"observation_log": {"fields": fields}},
        "categories": list(CATEGORY_OPTIONS),
        "perspective_tags": list(PERSPECTIVE_OPTIONS),
    }


def active_setting(session: Session, on_date: date | None = None) -> ChildRecordSettingVersion | None:
    target = on_date or date.today()
    return session.exec(
        select(ChildRecordSettingVersion)
        .where(
            ChildRecordSettingVersion.status == "active",
            ChildRecordSettingVersion.effective_from <= target,
        )
        .order_by(
            ChildRecordSettingVersion.effective_from.desc(),
            ChildRecordSettingVersion.version_no.desc(),
        )
    ).first()


def effective_config(session: Session, on_date: date | None = None) -> tuple[dict[str, Any], int | None]:
    setting = active_setting(session, on_date)
    if setting is None:
        return default_config(), None
    return deepcopy(setting.config or default_config(setting.preset_key)), setting.id


def field_map(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    fields = config.get("record_types", {}).get("observation_log", {}).get("fields", [])
    return {str(item.get("key")): item for item in fields if item.get("key")}


def enabled_fields(config: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        (item for item in field_map(config).values() if item.get("enabled")),
        key=lambda item: int(item.get("order") or 0),
    )


def new_custom_field_key() -> str:
    """Generate a stable UUID-based key for a custom field.

    Returns a key formatted as `cf_<uuid4>` that persists across label changes.
    """
    return f"cf_{uuid4()}"


def update_custom_field_definitions(
    existing_fields: list[dict[str, Any]],
    new_definitions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Update custom field definitions while preserving existing UUID4 keys.

    If an incoming field already has a valid key matching an existing field,
    its key is maintained even when its label or order changes.
    If the key is missing or new, a new `cf_<uuid4>` key is assigned.
    """
    existing_by_key = {item["key"]: item for item in existing_fields if item.get("key")}
    updated: list[dict[str, Any]] = []
    for item in new_definitions:
        entry = deepcopy(item)
        key = entry.get("key")
        if not key or key not in existing_by_key:
            # Check if key starts with cf_, otherwise generate
            if not (key and key.startswith("cf_")):
                key = new_custom_field_key()
            entry["key"] = key
        entry.setdefault("custom", True)
        updated.append(entry)
    return updated


def save_child_record_settings_version(
    session: Session,
    new_config: dict[str, Any],
    actor_id: str | None = None,
    effective_from: date | None = None,
    preset_key: str | None = None,
) -> ChildRecordSettingVersion:
    """Save a new version of child record settings.

    Automatically increments version_no and commits the record.
    """
    latest_setting = session.exec(
        select(ChildRecordSettingVersion)
        .order_by(ChildRecordSettingVersion.version_no.desc())
    ).first()
    version_no = (latest_setting.version_no + 1) if latest_setting else 1
    next_lock_version = (latest_setting.lock_version + 1) if latest_setting else 1
    target_date = effective_from or date.today()

    # Retire same date active versions if needed
    same_date_rows = session.exec(
        select(ChildRecordSettingVersion).where(
            ChildRecordSettingVersion.status == "active",
            ChildRecordSettingVersion.effective_from == target_date,
        )
    ).all()
    for row in same_date_rows:
        row.status = "retired"
        session.add(row)

    setting = ChildRecordSettingVersion(
        version_no=version_no,
        status="active",
        preset_key=preset_key or new_config.get("preset_key", "standard"),
        effective_from=target_date,
        config=new_config,
        created_by=str(actor_id) if actor_id else None,
        activated_by=str(actor_id) if actor_id else None,
        activated_at=utc_now(),
        lock_version=next_lock_version,
    )
    session.add(setting)
    session.commit()
    session.refresh(setting)
    return setting
