"""Timefold 思想に基づく差分レビュー・提案適用サービス (Diff Review & Plan Proposals)。

求解結果を即座に本番テーブルへ上書きせず、差分（ADDED, REMOVED, MODIFIED）を抽出して
現場管理者が承認（Accept）または破棄（Reject）できる安全なワークフローを提供する。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import date
from typing import Any, Optional

from sqlmodel import Session, delete, select

from shift_schedule.db_models import ShiftPlanCells, ShiftPlanProposals, ShiftPlans
from time_utils import utc_now


def compute_plan_diff(
    existing_cells: Sequence[ShiftPlanCells],
    proposal_cells: Sequence[ShiftPlanCells],
) -> dict[str, Any]:
    """既存シフトセルと求解提案セルを突合し、変更差分を詳細に計算する。"""
    existing_map: dict[tuple[str, str, str], str] = {
        (str(c.staff_user_id), str(c.target_date), str(c.slot_label)): c.cell_state
        for c in existing_cells
    }
    proposal_map: dict[tuple[str, str, str], str] = {
        (str(c.staff_user_id), str(c.target_date), str(c.slot_label)): c.cell_state
        for c in proposal_cells
    }

    all_keys = set(existing_map.keys()) | set(proposal_map.keys())

    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    modified: list[dict[str, Any]] = []
    unchanged_count = 0
    affected_staff: set[str] = set()

    for sid, dt_str, slot in sorted(all_keys):
        old_state = existing_map.get((sid, dt_str, slot), "OFF")
        new_state = proposal_map.get((sid, dt_str, slot), "OFF")

        if old_state == new_state:
            unchanged_count += 1
            continue

        affected_staff.add(sid)
        item = {
            "staff_user_id": sid,
            "target_date": dt_str,
            "slot_label": slot,
            "old_state": old_state,
            "new_state": new_state,
        }

        if old_state in ("OFF", "unspecified") and new_state in ("WORK", "BREAK", "specified"):
            added.append(item)
        elif old_state in ("WORK", "BREAK", "specified") and new_state in ("OFF", "unspecified"):
            removed.append(item)
        else:
            modified.append(item)

    summary = {
        "added_count": len(added),
        "removed_count": len(removed),
        "modified_count": len(modified),
        "unchanged_count": unchanged_count,
        "total_proposals": len(proposal_cells),
        "affected_staff_count": len(affected_staff),
        "affected_staff_ids": sorted(affected_staff),
    }

    return {
        "summary": summary,
        "added": added,
        "removed": removed,
        "modified": modified,
    }


def create_proposal(
    session: Session,
    plan_id: int,
    job_id: int,
    proposal_cells: Sequence[ShiftPlanCells],
    score_dict: Optional[dict[str, Any]] = None,
) -> ShiftPlanProposals:
    """求解結果から差分を計算し、ShiftPlanProposals として永続化する。"""
    # 既存セルを取得
    existing_cells = session.exec(
        select(ShiftPlanCells).where(ShiftPlanCells.plan_id == plan_id)
    ).all()

    diff_result = compute_plan_diff(existing_cells, proposal_cells)

    hard_score = 0
    soft_score = 0.0
    if score_dict:
        hard_score = score_dict.get("hard_score", 0)
        soft_score = score_dict.get("soft_score", 0.0)

    # セルデータを JSON シリアライズ可能な辞書リストに変換
    cells_payload = [
        {
            "staff_user_id": str(c.staff_user_id),
            "target_date": c.target_date.isoformat() if isinstance(c.target_date, date) else str(c.target_date),
            "slot_label": c.slot_label,
            "cell_state": c.cell_state,
            "is_pinned": c.is_pinned,
        }
        for c in proposal_cells
    ]

    proposal = ShiftPlanProposals(
        plan_id=plan_id,
        job_id=job_id,
        status="pending",
        hard_score=hard_score,
        soft_score=soft_score,
        score_explanation=json.dumps(score_dict or {}, ensure_ascii=False),
        diff_summary=json.dumps(diff_result, ensure_ascii=False),
        proposal_cells=json.dumps(cells_payload, ensure_ascii=False),
        created_at=utc_now(),
    )
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def apply_proposal(session: Session, proposal_id: int) -> int:
    """保留中の提案（Pending Proposal）を承認し、本番の ShiftPlanCells にコミットする。"""
    proposal = session.exec(
        select(ShiftPlanProposals).where(ShiftPlanProposals.id == proposal_id)
    ).first()
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")
    if proposal.status != "pending":
        raise ValueError(f"Proposal {proposal_id} has already been {proposal.status}")

    plan = session.exec(select(ShiftPlans).where(ShiftPlans.id == proposal.plan_id)).first()
    if not plan:
        raise ValueError(f"Plan {proposal.plan_id} not found")

    cells_data = json.loads(proposal.proposal_cells)

    # ピン留めされたセル以外の既存セルを削除して置き換え
    pinned_cells = session.exec(
        select(ShiftPlanCells).where(
            ShiftPlanCells.plan_id == proposal.plan_id,
            ShiftPlanCells.is_pinned.is_(True),
        )
    ).all()
    pinned_keys = {
        (str(c.staff_user_id), str(c.target_date), str(c.slot_label))
        for c in pinned_cells
    }

    # 未固定セルをクリア
    session.exec(
        delete(ShiftPlanCells).where(
            ShiftPlanCells.plan_id == proposal.plan_id,
            ShiftPlanCells.is_pinned.is_(False),
        )
    )

    applied_count = 0
    from datetime import datetime as dtt
    for c_dict in cells_data:
        key = (c_dict["staff_user_id"], c_dict["target_date"], c_dict["slot_label"])
        if key in pinned_keys:
            continue  # 手動固定セルは保護

        t_date = (
            dtt.strptime(c_dict["target_date"], "%Y-%m-%d").date()
            if isinstance(c_dict["target_date"], str)
            else c_dict["target_date"]
        )
        new_cell = ShiftPlanCells(
            plan_id=proposal.plan_id,
            staff_user_id=c_dict["staff_user_id"],
            target_date=t_date,
            slot_label=c_dict["slot_label"],
            cell_state=c_dict["cell_state"],
            is_pinned=c_dict.get("is_pinned", False),
        )
        session.add(new_cell)
        applied_count += 1

    proposal.status = "accepted"
    plan.status = "generated"
    plan.updated_at = utc_now()
    session.add(proposal)
    session.add(plan)
    session.commit()
    return applied_count


def reject_proposal(session: Session, proposal_id: int) -> None:
    """保留中の提案（Pending Proposal）を破棄（Reject）する。"""
    proposal = session.exec(
        select(ShiftPlanProposals).where(ShiftPlanProposals.id == proposal_id)
    ).first()
    if not proposal:
        raise ValueError(f"Proposal {proposal_id} not found")
    if proposal.status != "pending":
        raise ValueError(f"Proposal {proposal_id} is not pending ({proposal.status})")

    proposal.status = "rejected"
    session.add(proposal)
    session.commit()
