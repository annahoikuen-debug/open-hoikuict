"""Timefold 思想に基づくシフト診断・過剰制約分析サービス (Constraint Indictment & Diagnostics Service).

数理最適化ソルバーが出力した不足コマ（overconstrained_shortfalls）および
制約起訴（Indictments）を解析し、非エンジニア（園長・主任保育士）向けに
「なぜ解が不足したのか」「誰の制約を緩和すれば解決できるか」の
自然言語サジェストおよび構造化レポートを生成する。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from typing import Any, Optional

from sqlmodel import Session, select

from models import User
from shift_schedule.db_models import (
    ShiftSolveJobs,
    ShiftViolations,
    StaffShiftUnavailability,
)


def generate_diagnostics_report(
    result: Any,
    context: Any,
    session: Optional[Session] = None,
) -> dict[str, Any]:
    """求解結果（SolveResult）から構造化診断サジェストレポートを生成する。"""
    shortfalls = getattr(result, "overconstrained_shortfalls", []) or []
    score = getattr(result, "score", None)
    indictments = getattr(score, "indictments", {}) if score else {}

    # 1. 不足コマ（Shortfalls）の集計
    shortfall_summary: list[dict[str, Any]] = []
    shortfall_dates: set[date] = set()

    for sf in shortfalls:
        d = sf.get("day")
        if isinstance(d, str):
            try:
                d = date.fromisoformat(d)
            except ValueError:
                pass
        if isinstance(d, date):
            shortfall_dates.add(d)

        shortfall_summary.append({
            "day": d.isoformat() if isinstance(d, date) else str(d),
            "slot": sf.get("slot") or sf.get("slot_label", ""),
            "needed": sf.get("needed", 0),
            "assigned": sf.get("assigned", 0),
            "deficit": sf.get("deficit", 1),
            "class_name": sf.get("class_name", "全体"),
        })

    # 2. 制約起訴（Constraint Indictment）の集計
    staff_penalties: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"hard_count": 0, "soft_total": 0.0, "violations": []}
    )

    for (sid, _d_key), ind in indictments.items():
        sid_str = str(sid)
        staff_penalties[sid_str]["hard_count"] += getattr(ind, "hard_penalty_count", 0)
        staff_penalties[sid_str]["soft_total"] += getattr(ind, "soft_penalty_total", 0.0)
        v_list = getattr(ind, "violations", [])
        for v in v_list:
            if v not in staff_penalties[sid_str]["violations"]:
                staff_penalties[sid_str]["violations"].append(v)

    # 3. 不足日における職員の不在要因（希望休・契約時間外等）の分析
    user_name_map: dict[str, str] = {}
    if session:
        users = session.exec(select(User)).all()
        for u in users:
            uid_str = str(u.id).replace("-", "")
            user_name_map[uid_str] = u.display_name or u.email

    suggestions: list[dict[str, Any]] = []

    if shortfall_dates and session:
        # 不足日に希望休や不在を出している職員を抽出
        unavail_rows = session.exec(
            select(StaffShiftUnavailability).where(
                StaffShiftUnavailability.target_date.in_(list(shortfall_dates)),
                StaffShiftUnavailability.status == "approved",
            )
        ).all()

        unavail_by_date = defaultdict(list)
        for un in unavail_rows:
            sid_clean = str(un.staff_user_id).replace("-", "")
            name = user_name_map.get(sid_clean, f"職員({sid_clean[:6]})")
            unavail_by_date[un.target_date].append({
                "staff_user_id": sid_clean,
                "name": name,
                "kind": un.kind,
                "reason": un.reason,
            })

        for d in sorted(shortfall_dates):
            d_str = d.isoformat()
            d_shortfalls = [sf for sf in shortfall_summary if sf["day"] == d_str]
            total_deficit = sum(sf["deficit"] for sf in d_shortfalls)
            unavails = unavail_by_date.get(d, [])

            if unavails:
                names = [u["name"] for u in unavails]
                suggestions.append({
                    "type": "SHIFT_REQUEST_CONCESSION",
                    "target_date": d_str,
                    "severity": "HIGH",
                    "title": f"{d_str} の希望休・有休の調整検討",
                    "description": f"{d_str} に {total_deficit} コマの人員不足が発生しています。同日に {', '.join(names)} が「{unavails[0]['kind']}」を取得しています。一部職員への出勤打診を推奨します。",
                    "action_staff_ids": [u["staff_user_id"] for u in unavails],
                })
            else:
                suggestions.append({
                    "type": "EXTERNAL_OR_OVERTIME",
                    "target_date": d_str,
                    "severity": "MEDIUM",
                    "title": f"{d_str} のパート延長または応援要請",
                    "description": f"{d_str} に {total_deficit} コマの人員不足が発生しています。在籍パート職員の勤務時間延長（契約変更）またはフリー保育士・派遣応援の配置を検討してください。",
                    "action_staff_ids": [],
                })

    # 4. 全体サマリ文の構築
    is_fully_feasible = len(shortfall_summary) == 0 and (score.is_feasible if score else True)
    if is_fully_feasible:
        summary_text = "すべての法令配置基準およびハード制約が充足された安全なシフトです。"
    else:
        summary_text = (
            f"法令配置基準の不足スロットが {len(shortfall_summary)} 箇所検出されました。"
            f"過剰制約計画（Overconstrained Planning）により、不足ペナルティを最小化した暫定解を保持しています。"
            f"以下のサジェストを確認し、希望休の緩和または人員応援を検討してください。"
        )

    # 上位ペナルティ職員のリスト化
    top_indicted_staff = sorted(
        [
            {
                "staff_user_id": sid,
                "name": user_name_map.get(sid, f"職員({sid[:6]})"),
                "hard_penalty_count": data["hard_count"],
                "soft_penalty_total": round(data["soft_total"], 2),
                "violations": data["violations"][:5],
            }
            for sid, data in staff_penalties.items()
            if data["hard_count"] > 0 or data["soft_total"] > 10.0
        ],
        key=lambda x: (x["hard_penalty_count"], x["soft_penalty_total"]),
        reverse=True,
    )[:5]

    return {
        "is_feasible": is_fully_feasible,
        "summary": summary_text,
        "total_shortfall_slots": len(shortfall_summary),
        "shortfalls": shortfall_summary,
        "suggestions": suggestions,
        "top_indicted_staff": top_indicted_staff,
    }


def enrich_solve_job_with_diagnostics(
    session: Session,
    job: ShiftSolveJobs,
    result: Any,
    context: Any,
    plan_id: int,
) -> dict[str, Any]:
    """求解ジョブに診断レポートを組み込み、必要な BLOCKER / WARNING 違反レコードを永続化する。"""
    diagnostics = generate_diagnostics_report(result, context, session)

    # 重大な不足スロット（Shortfall）がある場合、ShiftViolations に BLOCKER として追加
    for sf in diagnostics.get("shortfalls", []):
        try:
            d_val = date.fromisoformat(sf["day"])
        except (ValueError, TypeError):
            d_val = None

        violation = ShiftViolations(
            plan_id=plan_id,
            job_id=job.id,
            code="OVERCONSTRAINED_SHORTFALL",
            severity="BLOCKER",
            target_date=d_val,
            slot_label=sf.get("slot"),
            message=f"配置基準不足: {sf.get('slot')} で {sf.get('deficit')} 名不足しています（必要: {sf.get('needed')}名 / 配置: {sf.get('assigned')}名）。",
        )
        session.add(violation)

    return diagnostics


def get_plan_diagnostics(session: Session, plan_id: int) -> dict[str, Any]:
    """プランIDに関連する最新の診断レポートを取得する。"""
    import json

    latest_job = session.exec(
        select(ShiftSolveJobs)
        .where(ShiftSolveJobs.plan_id == plan_id)
        .order_by(ShiftSolveJobs.id.desc())
    ).first()

    if not latest_job or not latest_job.stats:
        return {
            "is_feasible": True,
            "summary": "診断データはまだ生成されていません。",
            "total_shortfall_slots": 0,
            "shortfalls": [],
            "suggestions": [],
            "top_indicted_staff": [],
        }

    try:
        stats = json.loads(latest_job.stats)
        diag = stats.get("diagnostics")
        if diag:
            return diag
    except Exception:
        pass

    return {
        "is_feasible": True,
        "summary": "診断データは登録されていません。",
        "total_shortfall_slots": 0,
        "shortfalls": [],
        "suggestions": [],
        "top_indicted_staff": [],
    }
