"""シフト詳細 UI (Timefold フロントエンド) の表示・結合テスト。"""

import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from database import engine
from main import app
from shift_schedule.db_models import ShiftPlanProposals, ShiftPlans, ShiftSolveJobs
from testing_helpers import Role, authenticate_mock_staff, configure_test_environment


@pytest.fixture(autouse=True)
def setup_test_env():
    configure_test_environment()


@pytest.fixture
def auth_client():
    client = TestClient(app)
    authenticate_mock_staff(client, role=Role.ADMIN)
    return client


@pytest.fixture
def ui_test_plan():
    with Session(engine) as session:
        plan = ShiftPlans(
            target_month="2026-11",
            status="draft",
            staffing_standard_key="福岡市",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        # 提案 (Pending Proposal)
        prop = ShiftPlanProposals(
            plan_id=plan.id,
            job_id=1,
            status="pending",
            hard_score=0,
            soft_score=-12.5,
            diff_summary='{"added": 2, "modified": 1, "deleted": 0}',
            proposal_cells="[]",
        )
        session.add(prop)
        session.commit()

        yield plan

        # クリーンアップ
        session.delete(prop)
        session.delete(plan)
        session.commit()


def test_plan_detail_html_contains_timefold_ui_components(auth_client, ui_test_plan):
    """シフト詳細画面にリアルタイム進捗、差分レビュー、再計画モーダル、重み設定モーダルが正しく含まれていること。"""
    response = auth_client.get(f"/shifts/plans/{ui_test_plan.id}")

    assert response.status_code == 200
    html = response.text

    # 1. ヘッダーとバッジ
    assert "Timefold MILP Engine" in html
    assert "制約重み設定" in html
    assert "突発欠勤再計画" in html

    # 2. 差分レビューパネル (Pending Proposal)
    assert "再計画提案の差分レビュー" in html
    assert "この変更を適用する" in html

    # 3. リアルタイム進捗パネル
    assert 'id="realtimeProgressPanel"' in html
    assert 'id="progressBarFill"' in html
    assert 'id="cancelJobBtn"' in html

    # 4. 突発欠勤モーダル
    assert 'id="replanModal"' in html
    assert "突発欠勤リアルタイム再計画" in html
    assert 'id="executeReplanBtn"' in html

    # 5. 園別制約重み設定モーダル
    assert 'id="weightsModal"' in html
    assert "施設固有の制約重み設定" in html
    assert 'id="saveWeightsBtn"' in html


def test_facility_constraint_weights_api(auth_client):
    """制約重み API (GET/PUT) が正常に応答すること。"""
    response = auth_client.get("/shifts/facilities/1/constraint-weights")

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 20

    # 制約IDの存在確認
    c_ids = [item["constraint_id"] for item in data]
    assert "SHORTFALL_STAFF" in c_ids
    assert "BREAK_INSUFFICIENT" in c_ids
    assert "SPLIT_SHIFT" in c_ids
