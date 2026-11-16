"""兄弟割引・多子軽減の出生順位自動判定サービス (P8-6)。

同一家族（family_id）に属する在園児を生年月日順（年長者順）に評価し、
第1子（全額）、第2子（半額減免）、第3子以降（全額無償）の
出生順位および軽減率を動的に算出します。
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

from sqlmodel import Session, select

from models import Child, ChildStatus


def _get_month_date_range(target_month: str) -> tuple[date, date]:
    """'YYYY-MM' 形式から月の開始日と終了日を返す。"""
    parts = target_month.split("-")
    year = int(parts[0])
    month = int(parts[1])
    first_day = date(year, month, 1)
    last_day = date(year, month, monthrange(year, month)[1])
    return first_day, last_day


def evaluate_family_sibling_ranks(
    session: Session, family_id: int, target_month: str
) -> list[dict[str, Any]]:
    """指定月の同一世帯内の在園児を抽出し、出生順位（第1子・第2子・第3子以降）を判定する。"""
    month_start, month_end = _get_month_date_range(target_month)

    # 同一家族内の園児
    children = session.exec(
        select(Child).where(
            Child.family_id == family_id,
            Child.status == ChildStatus.enrolled,
        )
    ).all()

    # 指定月に在園しているか判定
    active_children: list[Child] = []
    for c in children:
        if c.enrollment_date and c.enrollment_date > month_end:
            continue
        if c.withdrawal_date and c.withdrawal_date < month_start:
            continue
        active_children.append(c)

    # 生年月日（年長者順）でソート
    active_children.sort(key=lambda child: (child.birth_date or date.max, child.id or 0))

    results: list[dict[str, Any]] = []
    total_active = len(active_children)

    for rank_idx, child in enumerate(active_children, start=1):
        if total_active <= 1:
            # 単身在園の場合は通常（免除なし）
            results.append({
                "child_id": child.id,
                "child_name": child.full_name,
                "birth_date": child.birth_date.isoformat() if child.birth_date else "",
                "rank": 1,
                "rank_label": "単身在園（対象外）",
                "discount_type": "none",
                "discount_percentage": 0,
                "reason": "同月在園兄弟なし",
            })
        elif rank_idx == 1:
            results.append({
                "child_id": child.id,
                "child_name": child.full_name,
                "birth_date": child.birth_date.isoformat() if child.birth_date else "",
                "rank": 1,
                "rank_label": "第1子（基準児）",
                "discount_type": "none",
                "discount_percentage": 0,
                "reason": "多子軽減 基準児（全額）",
            })
        elif rank_idx == 2:
            results.append({
                "child_id": child.id,
                "child_name": child.full_name,
                "birth_date": child.birth_date.isoformat() if child.birth_date else "",
                "rank": 2,
                "rank_label": "第2子",
                "discount_type": "percentage",
                "discount_percentage": 50,
                "reason": "多子軽減 第2子（50%免除）",
            })
        else:
            results.append({
                "child_id": child.id,
                "child_name": child.full_name,
                "birth_date": child.birth_date.isoformat() if child.birth_date else "",
                "rank": rank_idx,
                "rank_label": f"第{rank_idx}子",
                "discount_type": "full",
                "discount_percentage": 100,
                "reason": f"多子軽減 第{rank_idx}子以降（全額無償）",
            })

    return results


def calculate_sibling_discount_for_child(
    session: Session, child_id: int, target_month: str
) -> dict[str, Any]:
    """特定の園児に対する兄弟割引・軽減情報を取得する。"""
    child = session.get(Child, child_id)
    if not child or not child.family_id:
        return {
            "child_id": child_id,
            "rank": 1,
            "rank_label": "家族未設定",
            "discount_type": "none",
            "discount_percentage": 0,
            "reason": "",
        }

    family_evals = evaluate_family_sibling_ranks(session, child.family_id, target_month)
    for item in family_evals:
        if item["child_id"] == child_id:
            return item

    return {
        "child_id": child_id,
        "rank": 1,
        "rank_label": "在園外",
        "discount_type": "none",
        "discount_percentage": 0,
        "reason": "",
    }
