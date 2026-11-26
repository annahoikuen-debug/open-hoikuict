"""Timefold 思想に基づくシフト診断・過剰制約分析サービス (Constraint Indictment & Diagnostics Service).

数理最適化ソルバーが出力した不足コマ（overconstrained_shortfalls）および
制約起訴（Indictments）を解析し、非エンジニア（園長・主任保育士）向けに
「なぜ解が不足したのか」「誰の制約を緩和すれば解決できるか」の
自然言語サジェストおよび構造化レポートを生成する。
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Any, Optional

from sqlmodel import Session, select

from models import User
from shift_schedule.db_models import (
    ShiftPlans,
    ShiftSolveJobs,
    ShiftSolveSnapshots,
    ShiftSuggestionActions,
    ShiftViolations,
    StaffShiftUnavailability,
)


def compute_suggestion_id(
    suggestion_type: str,
    target_date: str,
    action_staff_ids: Optional[list[str]] = None,
) -> str:
    """サジェスト種別・対象日・対象職員IDから決定論的な一意IDを生成する。"""
    staff_part = ",".join(sorted(str(sid) for sid in (action_staff_ids or [])))
    raw = f"{suggestion_type}|{target_date}|{staff_part}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"sg_{digest}"


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
                staff_ids = [u["staff_user_id"] for u in unavails]
                suggestions.append({
                    "id": compute_suggestion_id("SHIFT_REQUEST_CONCESSION", d_str, staff_ids),
                    "type": "SHIFT_REQUEST_CONCESSION",
                    "target_date": d_str,
                    "severity": "HIGH",
                    "title": f"{d_str} の希望休・有休の調整検討",
                    "description": f"{d_str} に {total_deficit} コマの人員不足が発生しています。同日に {', '.join(names)} が「{unavails[0]['kind']}」を取得しています。一部職員への出勤打診を推奨します。",
                    "action_staff_ids": staff_ids,
                })
            else:
                suggestions.append({
                    "id": compute_suggestion_id("EXTERNAL_OR_OVERTIME", d_str, []),
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
            for sg in diag.get("suggestions", []):
                if not sg.get("id"):
                    sg["id"] = compute_suggestion_id(
                        str(sg.get("type", "")),
                        str(sg.get("target_date", "")),
                        sg.get("action_staff_ids") or [],
                    )
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


class SuggestionActionError(Exception):
    """サジェスト判断処理の業務・整合エラー。"""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def send_concession_notifications(
    session: Session,
    plan: ShiftPlans,
    suggestion: dict[str, Any],
    note: Optional[str] = None,
) -> list[str]:
    """希望休調整（出勤打診）の通知対象職員を解決し、打診通知を記録・送信する。

    職員の StaffShiftUnavailability（希望休）の自動取消は行わない。
    """
    raw_ids = suggestion.get("action_staff_ids") or []
    target_ids: list[str] = []
    seen: set[str] = set()
    for sid in raw_ids:
        sid_str = str(sid).replace("-", "")
        if sid_str and sid_str not in seen:
            seen.add(sid_str)
            target_ids.append(sid_str)
    return target_ids


def _format_rejection_reason(reason_code: Optional[str], reason_note: Optional[str]) -> str:
    code = (reason_code or "").strip()
    note = (reason_note or "").strip()
    if code == "その他":
        return f"その他: {note}" if note else "その他"
    if code and note:
        return f"{code}（{note}）"
    return code or note or "却下"


def reconcile_resolved_holds(
    session: Session,
    plan: ShiftPlans,
    active_suggestion_ids: set[str],
    snapshot_id: Optional[int] = None,
) -> list[ShiftSuggestionActions]:
    """不足解消により消滅した保留サジェストを自動的に resolved として記録する。"""
    rows = session.exec(
        select(ShiftSuggestionActions)
        .where(
            ShiftSuggestionActions.plan_id == plan.id,
            ShiftSuggestionActions.facility_id == plan.facility_id,
        )
        .order_by(ShiftSuggestionActions.created_at.desc(), ShiftSuggestionActions.id.desc())
    ).all()

    latest_by_id: dict[str, ShiftSuggestionActions] = {}
    for r in rows:
        if r.suggestion_id not in latest_by_id:
            latest_by_id[r.suggestion_id] = r

    created: list[ShiftSuggestionActions] = []
    for sg_id, latest in latest_by_id.items():
        if latest.action == "hold" and sg_id not in active_suggestion_ids:
            resolved_row = ShiftSuggestionActions(
                facility_id=plan.facility_id,
                plan_id=plan.id,
                snapshot_id=snapshot_id,
                suggestion_id=sg_id,
                suggestion_type=latest.suggestion_type,
                target_date=latest.target_date,
                action="resolved",
                reason_code="AUTO_RESOLVED",
                reason_note="不足解消により自動消滅",
                actor_name="システム（自動）",
            )
            session.add(resolved_row)
            created.append(resolved_row)

    if created:
        session.commit()
        for c in created:
            session.refresh(c)
    return created


def get_plan_suggestions_with_state(
    session: Session,
    plan: ShiftPlans,
) -> dict[str, Any]:
    """診断サジェストに現在の判断状態・保留経過日数・前回却下理由・履歴を付与して返す。"""
    diag = get_plan_diagnostics(session, plan.id)
    suggestions = list(diag.get("suggestions") or [])

    latest_snapshot = session.exec(
        select(ShiftSolveSnapshots)
        .where(
            ShiftSolveSnapshots.plan_id == plan.id,
            ShiftSolveSnapshots.facility_id == plan.facility_id,
        )
        .order_by(ShiftSolveSnapshots.id.desc())
    ).first()
    latest_snapshot_id = latest_snapshot.id if latest_snapshot else None

    has_solved_job = (
        session.exec(
            select(ShiftSolveJobs.id).where(ShiftSolveJobs.plan_id == plan.id)
        ).first()
        is not None
    )
    active_ids = {str(sg["id"]) for sg in suggestions if sg.get("id")}
    if has_solved_job:
        reconcile_resolved_holds(session, plan, active_ids, snapshot_id=latest_snapshot_id)

    history_rows = session.exec(
        select(ShiftSuggestionActions)
        .where(
            ShiftSuggestionActions.plan_id == plan.id,
            ShiftSuggestionActions.facility_id == plan.facility_id,
        )
        .order_by(ShiftSuggestionActions.created_at.desc(), ShiftSuggestionActions.id.desc())
    ).all()

    # 同一施設内の過去の却下履歴（同 type の「前回却下」表示用）
    facility_rejections = session.exec(
        select(ShiftSuggestionActions)
        .where(
            ShiftSuggestionActions.facility_id == plan.facility_id,
            ShiftSuggestionActions.action == "rejected",
        )
        .order_by(ShiftSuggestionActions.created_at.desc(), ShiftSuggestionActions.id.desc())
    ).all()
    prev_rejected_by_type: dict[str, str] = {}
    for rej in facility_rejections:
        if rej.suggestion_type not in prev_rejected_by_type:
            prev_rejected_by_type[rej.suggestion_type] = _format_rejection_reason(
                rej.reason_code, rej.reason_note
            )

    latest_by_id: dict[str, ShiftSuggestionActions] = {}
    hold_started_by_id: dict[str, datetime] = {}
    for row in history_rows:
        if row.suggestion_id not in latest_by_id:
            latest_by_id[row.suggestion_id] = row
        if row.action == "hold":
            hold_started_by_id[row.suggestion_id] = row.created_at

    # 職員名マップ
    users = session.exec(select(User)).all()
    user_name_map = {str(u.id).replace("-", ""): (u.display_name or u.email) for u in users}

    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    enriched: list[dict[str, Any]] = []
    for sg in suggestions:
        sg_copy = dict(sg)
        sg_id = str(sg_copy.get("id", ""))
        latest = latest_by_id.get(sg_id)
        status = latest.action if latest and latest.action in ("adopted", "hold", "rejected") else "pending_action"

        hold_days = 0
        if status == "hold" and sg_id in hold_started_by_id:
            started = hold_started_by_id[sg_id]
            if started.tzinfo is not None:
                started = started.astimezone(timezone.utc).replace(tzinfo=None)
            hold_days = max(0, (now_utc - started).days)

        staff_ids = [str(x).replace("-", "") for x in (sg_copy.get("action_staff_ids") or [])]
        sg_copy["status"] = status
        sg_copy["hold_days"] = hold_days
        sg_copy["prev_rejected_reason"] = prev_rejected_by_type.get(str(sg_copy.get("type", "")))
        sg_copy["action_staff_names"] = [
            user_name_map.get(sid, f"職員({sid[:6]})") for sid in staff_ids
        ]
        enriched.append(sg_copy)

    return {
        "suggestions": enriched,
        "history": history_rows,
        "diagnostics": diag,
        "latest_snapshot_id": latest_snapshot_id,
    }


def record_suggestion_action(
    session: Session,
    plan: ShiftPlans,
    suggestion_id: str,
    action: str,
    actor_user_id: Optional[str],
    actor_name: Optional[str],
    reason_code: Optional[str] = None,
    reason_note: Optional[str] = None,
) -> ShiftSuggestionActions:
    """サジェストに対する採用・保留・却下を記録する。"""
    if plan.status == "approved":
        raise SuggestionActionError("確定済みプランのサジェストは操作できません。", status_code=409)

    if action not in ("adopted", "hold", "rejected"):
        raise SuggestionActionError("不正なアクションです。", status_code=400)

    if action == "rejected":
        code = (reason_code or "").strip()
        note = (reason_note or "").strip()
        if not code:
            raise SuggestionActionError("却下理由を選択してください。", status_code=400)
        if code == "その他" and not note:
            raise SuggestionActionError("「その他」を選択した場合は補足理由を入力してください。", status_code=400)

    diag = get_plan_diagnostics(session, plan.id)
    target_sg = next((sg for sg in (diag.get("suggestions") or []) if sg.get("id") == suggestion_id), None)
    if target_sg is None:
        raise SuggestionActionError("対象のサジェストが見つかりません。", status_code=404)

    existing_adopted = session.exec(
        select(ShiftSuggestionActions).where(
            ShiftSuggestionActions.plan_id == plan.id,
            ShiftSuggestionActions.facility_id == plan.facility_id,
            ShiftSuggestionActions.suggestion_id == suggestion_id,
            ShiftSuggestionActions.action == "adopted",
        )
    ).first()

    if action == "adopted" and existing_adopted is not None:
        raise SuggestionActionError("このサジェストは既に打診済みのため二重採用できません。", status_code=409)

    latest_snapshot = session.exec(
        select(ShiftSolveSnapshots)
        .where(
            ShiftSolveSnapshots.plan_id == plan.id,
            ShiftSolveSnapshots.facility_id == plan.facility_id,
        )
        .order_by(ShiftSolveSnapshots.id.desc())
    ).first()

    notified_ids: Optional[list[str]] = None
    if action == "adopted":
        notified_ids = send_concession_notifications(session, plan, target_sg, note=reason_note)

    row = ShiftSuggestionActions(
        facility_id=plan.facility_id,
        plan_id=plan.id,
        snapshot_id=latest_snapshot.id if latest_snapshot else None,
        suggestion_id=suggestion_id,
        suggestion_type=str(target_sg.get("type", "")),
        target_date=str(target_sg.get("target_date", "")) or None,
        action=action,
        reason_code=(reason_code or "").strip() or None,
        reason_note=(reason_note or "").strip() or None,
        notified_staff_ids=notified_ids,
        actor_user_id=actor_user_id,
        actor_name=actor_name,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
