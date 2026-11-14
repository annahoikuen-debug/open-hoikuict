"""施設別の制約重み設定サービス (Timefold: Runtime Constraint Weights)。

ShiftFacilityConstraintWeights テーブルに保存された園固有の重み・有効無効フラグを
NuShift の ObjectiveWeights に動的注入し、What-if 調整や園ごとの最適化ポリシーを可能にする。
"""

from __future__ import annotations

import logging
from typing import Any
from sqlmodel import Session, select

from shiftai.constraints import ConstraintRegistry
from shiftai.domain import ObjectiveWeights
from shift_schedule.db_models import ShiftFacilityConstraintWeights, ShiftPlanningAudits

logger = logging.getLogger(__name__)

# 制約IDと ObjectiveWeights 属性のマッピング
CONSTRAINT_ID_TO_WEIGHT_ATTR: dict[str, str] = {
    "SHORTFALL_STAFF": "shortfall_penalty",
    "OVERSTAFF": "overstaff_penalty",
    "WORK_ON_UNAVAILABLE": "preference_miss_penalty",
    "PREF_PREFERRED_DAY": "preference_match_bonus",
    "AVOID_EARLY_CONFLICT": "early_shift_penalty",
    "AVOID_LATE_CONFLICT": "late_shift_penalty",
    "BREAK_OVERLAP": "break_conflict_penalty",
    "BREAK_INSUFFICIENT": "break_deficit_penalty",
    "SPLIT_SHIFT": "split_duty_penalty",
    "CONSECUTIVE_DAYS": "consecutive_day_penalty",
    "HOLIDAY_TARGET_DIFF": "hours_imbalance_penalty",
    "FAIRNESS_SPREAD_EARLY": "fairness_early_penalty",
    "FAIRNESS_SPREAD_LATE": "fairness_late_penalty",
    "FAIRNESS_SPREAD_SATURDAY": "fairness_saturday_penalty",
    "BREAK_FRAGMENTED": "break_edge_penalty",
    "REST_HOURS_SHORT": "rest_violation_penalty",
    "DAILY_HOURS_EXCEEDED": "max_shift_length_penalty",
}


def build_runtime_objective_weights(session: Session, facility_id: int = 1) -> ObjectiveWeights:
    """DB に保存された施設別制約重みから ObjectiveWeights を生成する。

    設定が存在しない制約は ConstraintRegistry の default_weight または
    ObjectiveWeights のデフォルト値が使用される。
    """
    weights = ObjectiveWeights(split_duty_penalty=5000.0)

    try:
        stmt = select(ShiftFacilityConstraintWeights).where(
            ShiftFacilityConstraintWeights.facility_id == facility_id
        )
        db_weights = session.exec(stmt).all()
        weight_map = {w.constraint_id: w for w in db_weights}

        for cid, attr_name in CONSTRAINT_ID_TO_WEIGHT_ATTR.items():
            if not hasattr(weights, attr_name):
                continue

            if cid in weight_map:
                w_record = weight_map[cid]
                if not w_record.is_enabled:
                    # 無効化されている場合は重みを 0 に設定（無視）
                    setattr(weights, attr_name, 0.0)
                else:
                    setattr(weights, attr_name, float(w_record.weight))
            else:
                # DB 未登録の場合は ConstraintRegistry のデフォルト値を確認
                cdef = ConstraintRegistry.get(cid)
                if cdef is not None:
                    # 属性の初期値をそのまま維持、または cdef.default_weight を適用
                    pass

    except Exception as e:
        logger.warning(
            "施設 %s の制約重み取得中にエラーが発生したため、デフォルト重みを使用します: %s",
            facility_id,
            e,
        )

    return weights


def get_facility_constraint_weights(session: Session, facility_id: int = 1) -> list[dict[str, Any]]:
    """施設の全21制約の重み設定一覧を取得する（DB値 + 未設定のデフォルト値フォールバック）。"""
    stmt = select(ShiftFacilityConstraintWeights).where(
        ShiftFacilityConstraintWeights.facility_id == facility_id
    )
    db_weights = session.exec(stmt).all()
    weight_map = {w.constraint_id: w for w in db_weights}

    result = []
    for cdef in ConstraintRegistry.all():
        db_record = weight_map.get(cdef.id)
        effective_weight = db_record.weight if db_record else cdef.default_weight
        effective_enabled = db_record.is_enabled if db_record else True

        result.append({
            "constraint_id": cdef.id,
            "name": cdef.name,
            "description": cdef.description,
            "category": cdef.category.value if hasattr(cdef.category, "value") else str(cdef.category),
            "is_hard": cdef.is_hard,
            "configurable": cdef.configurable,
            "default_weight": cdef.default_weight,
            "current_weight": effective_weight,
            "is_enabled": effective_enabled,
        })

    return result


def update_facility_constraint_weights(
    session: Session,
    facility_id: int,
    updates: list[dict[str, Any]],
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    """施設の制約重みを一括更新し、監査ログを記録する。"""
    stmt = select(ShiftFacilityConstraintWeights).where(
        ShiftFacilityConstraintWeights.facility_id == facility_id
    )
    existing_weights = {w.constraint_id: w for w in session.exec(stmt).all()}

    updated_count = 0
    for item in updates:
        cid = item.get("constraint_id")
        if not cid:
            continue
        cdef = ConstraintRegistry.get(cid)
        if not cdef:
            continue

        weight_val = float(item.get("weight", cdef.default_weight))
        enabled_val = bool(item.get("is_enabled", True))

        if cid in existing_weights:
            record = existing_weights[cid]
            record.weight = weight_val
            record.is_enabled = enabled_val
            session.add(record)
        else:
            record = ShiftFacilityConstraintWeights(
                facility_id=facility_id,
                constraint_id=cid,
                weight=weight_val,
                is_enabled=enabled_val,
            )
            session.add(record)
        updated_count += 1

    # 監査ログを記録
    actor_id: int | None = None
    if user_id is not None:
        try:
            actor_id = int(user_id)
        except (ValueError, TypeError):
            actor_id = None

    audit = ShiftPlanningAudits(
        actor_user_id=actor_id,
        action="UPDATE_CONSTRAINT_WEIGHTS",
        summary=f"施設 {facility_id} の制約重み設定を更新しました ({updated_count} 件)",
    )
    session.add(audit)
    session.commit()

    return get_facility_constraint_weights(session, facility_id)
