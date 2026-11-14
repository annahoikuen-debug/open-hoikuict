"""施設別制約重み設定 (Runtime Constraint Weights) の結合テスト。"""

import pytest
from sqlmodel import Session, select

from database import engine
from shift_schedule.db_models import ShiftFacilityConstraintWeights, ShiftPlanningAudits
from shift_schedule.services.weights import (
    build_runtime_objective_weights,
    get_facility_constraint_weights,
    update_facility_constraint_weights,
)


@pytest.fixture
def clean_weights():
    facility_id = 9999  # テスト用独立 facility_id
    with Session(engine) as session:
        # 事前クリーンアップ
        old_w = session.exec(
            select(ShiftFacilityConstraintWeights).where(
                ShiftFacilityConstraintWeights.facility_id == facility_id
            )
        ).all()
        for w in old_w:
            session.delete(w)
        session.commit()

        yield facility_id

        # 事後クリーンアップ
        old_w = session.exec(
            select(ShiftFacilityConstraintWeights).where(
                ShiftFacilityConstraintWeights.facility_id == facility_id
            )
        ).all()
        for w in old_w:
            session.delete(w)
        session.commit()


def test_default_runtime_weights(clean_weights):
    """DB に未設定の場合、デフォルトの ObjectiveWeights が返される。"""
    facility_id = clean_weights
    with Session(engine) as session:
        weights = build_runtime_objective_weights(session, facility_id=facility_id)
        assert weights is not None
        assert weights.shortfall_penalty == 1000.0
        assert weights.split_duty_penalty == 5000.0
        assert weights.break_deficit_penalty == 6000.0


def test_db_weights_override_and_disable(clean_weights):
    """DB にカスタム重みを設定した場合、その値が反映され、無効化時は 0.0 になる。"""
    facility_id = clean_weights
    with Session(engine) as session:
        # カスタム設定を追加
        w1 = ShiftFacilityConstraintWeights(
            facility_id=facility_id,
            constraint_id="SHORTFALL_STAFF",
            weight=9999.0,
            is_enabled=True,
        )
        w2 = ShiftFacilityConstraintWeights(
            facility_id=facility_id,
            constraint_id="OVERSTAFF",
            weight=0.0,
            is_enabled=False,  # 無効化
        )
        session.add(w1)
        session.add(w2)
        session.commit()

        weights = build_runtime_objective_weights(session, facility_id=facility_id)
        assert weights.shortfall_penalty == 9999.0
        assert weights.overstaff_penalty == 0.0


def test_get_and_update_facility_weights(clean_weights):
    """全21制約の一覧取得、一括更新、および監査ログ記録の動作検証。"""
    facility_id = clean_weights
    with Session(engine) as session:
        # 初期状態: 21制約すべてが取得できる
        all_weights = get_facility_constraint_weights(session, facility_id=facility_id)
        assert len(all_weights) >= 20
        c_map = {item["constraint_id"]: item for item in all_weights}
        assert "SHORTFALL_STAFF" in c_map
        assert "BREAK_INSUFFICIENT" in c_map

        # 更新
        updates = [
            {"constraint_id": "OVERSTAFF", "weight": 2.5, "is_enabled": True},
            {"constraint_id": "FAIRNESS_SPREAD_EARLY", "weight": 50.0, "is_enabled": False},
        ]
        res = update_facility_constraint_weights(
            session=session,
            facility_id=facility_id,
            updates=updates,
            user_id="1",
        )
        updated_map = {item["constraint_id"]: item for item in res}
        assert updated_map["OVERSTAFF"]["current_weight"] == 2.5
        assert updated_map["OVERSTAFF"]["is_enabled"] is True
        assert updated_map["FAIRNESS_SPREAD_EARLY"]["is_enabled"] is False

        # 監査ログが記録されていること
        audit = session.exec(
            select(ShiftPlanningAudits).where(
                ShiftPlanningAudits.action == "UPDATE_CONSTRAINT_WEIGHTS",
                ShiftPlanningAudits.actor_user_id == 1,
            )
        ).first()
        assert audit is not None
        assert f"施設 {facility_id}" in audit.summary
