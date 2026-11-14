"""シフトプランルーター。

GET/POST /shifts/plans - プラン一覧・作成
GET /shifts/plans/{id} - プラン詳細
POST /shifts/plans/{id}/solve - 求解ジョブ発行
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select

from auth import require_can_edit
from ..contracts import PlanStatus
from ..db_models import ShiftPlans, ShiftSolveJobs
from ..services.solve_jobs import schedule_solve, solver_available
from ..store import ShiftRepository, ShiftRepositoryDep

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])
logger = logging.getLogger(__name__)


@router.get("/plans", response_class=HTMLResponse)
def plans_list(
    request: Request,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> HTMLResponse:
    plans = repo.session.exec(select(ShiftPlans).order_by(ShiftPlans.target_month.desc())).all()
    from template_utils import create_templates

    templates = create_templates()
    return templates.TemplateResponse(
        request,
        "shift_schedule/plans_list.html",
        {
            "request": request,
            "plans": plans,
            "solver_available": solver_available(),
            "cbc_available": solver_available(),
        },
    )


@router.post("/plans", dependencies=[Depends(require_can_edit)])
def plans_create(
    target_month: str = Form(...),
    staffing_standard_key: str = Form("fukuoka_city"),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    existing = repo.get_plan_by_month(target_month)
    if existing is not None:
        return RedirectResponse(url=f"/shifts/plans/{existing.id}", status_code=303)

    plan = ShiftPlans(
        target_month=target_month,
        status=PlanStatus.DRAFT,
        staffing_standard_key=staffing_standard_key,
    )
    repo.create_plan(plan)
    # DBコミット後のIDを取得するため再取得
    created = repo.get_plan_by_month(target_month)
    return RedirectResponse(url=f"/shifts/plans/{created.id}", status_code=303)


@router.get("/plans/{plan_id}", response_class=HTMLResponse)
def plans_detail(
    plan_id: int,
    request: Request,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> HTMLResponse:
    plan = repo.get_plan(plan_id)
    if plan is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Plan not found")

    cells = repo.list_plan_cells(plan_id)
    violations = repo.list_violations(plan_id)
    audits = repo.list_audits(plan_id)
    jobs = repo.session.exec(
        select(ShiftSolveJobs).where(ShiftSolveJobs.plan_id == plan_id).order_by(ShiftSolveJobs.requested_at.desc())
    ).all()

    # 配置割れギャップ検査（今日以降またはプラン月最初の日のギャップチェック）
    gap_warnings = []
    if cells:
        from ..services.gap_detector import detect_day_gap

        target_dates = sorted({c.target_date for c in cells})
        for td in target_dates[:3]:  # 最大3日分プレビュー
            try:
                gap_warnings.extend(detect_day_gap(repo.session, plan_id, td))
            except Exception:
                logger.exception("detect_day_gap failed for plan %s on %s", plan_id, td)

    # 微調整③: 不足枠（BLOCKER）に対する「処方箋（ヘルプ提案）」の生成
    prescriptions = []
    shortfall_violations = [v for v in violations if v.severity == "BLOCKER" and "SHORTFALL" in v.code]
    if shortfall_violations:
        from models import User
        users = repo.session.exec(select(User).where(User.is_active == True)).all()  # noqa: E712
        seen_targets = set()
        for sv in shortfall_violations:
            key = (sv.target_date, sv.slot_label)
            if key in seen_targets:
                continue
            seen_targets.add(key)
            day_cells = [c for c in cells if c.target_date == sv.target_date and c.cell_state in ("WORK", "specified", "pinned")]
            working_user_ids = {str(c.staff_user_id) for c in day_cells}
            
            candidate_names = []
            for u in users:
                if str(u.id) not in working_user_ids and u.id.hex not in working_user_ids:
                    candidate_names.append(u.display_name or u.email)
                if len(candidate_names) >= 2:
                    break
            
            candidate_text = "、".join(candidate_names) if candidate_names else "常勤の残業延長または応援派遣"
            prescriptions.append({
                "date": sv.target_date,
                "slot": sv.slot_label,
                "code": sv.code,
                "message": sv.message,
                "suggested_helpers": candidate_text,
            })
            if len(prescriptions) >= 4:
                break

    # スロット選択肢の動的生成（既存セル + 勤務パターン + 既定）
    from ..db_models import ShiftDutyPatterns
    duty_patterns = repo.session.exec(select(ShiftDutyPatterns)).all()
    dynamic_slots = set()
    for c in cells:
        if c.slot_label and c.slot_label != "OFF":
            dynamic_slots.add(c.slot_label)
    for dp in duty_patterns:
        dynamic_slots.add(f"{dp.start_time}-{dp.end_time}")
        if dp.name:
            dynamic_slots.add(dp.name)
    slot_options = sorted(dynamic_slots)

    # 職員名マッピング (UUID hex/str -> display_name)
    from models import User
    all_users = repo.session.exec(select(User)).all()
    staff_names: dict[str, str] = {}
    for u in all_users:
        name = u.display_name or u.email
        staff_names[str(u.id)] = name
        staff_names[u.id.hex] = name

    from template_utils import create_templates

    templates = create_templates()
    return templates.TemplateResponse(
        request,
        "shift_schedule/plan_detail.html",
        {
            "request": request,
            "plan": plan,
            "cells": cells,
            "violations": violations,
            "audits": audits,
            "jobs": jobs,
            "gap_warnings": gap_warnings,
            "prescriptions": prescriptions,
            "slot_options": slot_options,
            "staff_names": staff_names,
            "solver_available": solver_available(),
            "cbc_available": solver_available(),
        },
    )


@router.post("/plans/{plan_id}/solve", dependencies=[Depends(require_can_edit)])
def plans_solve(
    plan_id: int,
    request: Request,
    time_limit_sec: int = Form(30),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    plan = repo.get_plan(plan_id)
    if plan is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Plan not found")

    # 承認済みプランは再求解不可
    if plan.status == PlanStatus.APPROVED:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail="Approved plan cannot be re-solved")

    if not solver_available():
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="シフト最適化ソルバー (HiGHS / CBC) がサーバー上で利用できません。管理者に環境設定を確認してください。",
        )

    # 認証職員情報の解決
    from auth import get_optional_current_staff_user
    from audit_logger import record_audit_event

    staff = get_optional_current_staff_user(request)
    staff_id_str = staff.staff_id if staff else None
    actor_user_id = str(staff.user_id) if staff and staff.user_id else staff_id_str

    numeric_user_id = None
    if staff and staff.user_id:
        try:
            numeric_user_id = int(str(staff.user_id))
        except (ValueError, TypeError):
            numeric_user_id = staff.user_id.int % (2**31 - 1)

    job_id = schedule_solve(
        plan_id=plan_id,
        target_month=plan.target_month,
        staffing_standard_key=plan.staffing_standard_key,
        requested_by_user_id=numeric_user_id,
        time_limit_sec=time_limit_sec,
    )

    # 監査ログを記録
    record_audit_event(
        actor_user_id=actor_user_id or "anonymous",
        actor_role=staff.role.value if staff and hasattr(staff.role, "value") else (str(staff.role) if staff else None),
        target_resource="shift_plan",
        resource_id=plan_id,
        action="solve_requested",
        ip_address=request.client.host if request.client else None,
        detail={
            "target_month": plan.target_month,
            "job_id": job_id,
            "staffing_standard_key": plan.staffing_standard_key,
            "time_limit_sec": time_limit_sec,
        },
    )

    return RedirectResponse(url=f"/shifts/plans/{plan_id}", status_code=303)


@router.get("/plans/{plan_id}/status")
def plans_status(
    plan_id: int,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
):
    plan = repo.get_plan(plan_id)
    if plan is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Plan not found")

    latest_job = repo.session.exec(
        select(ShiftSolveJobs).where(ShiftSolveJobs.plan_id == plan_id).order_by(ShiftSolveJobs.requested_at.desc())
    ).first()

    return {
        "plan_id": plan_id,
        "status": plan.status,
        "job_status": latest_job.status if latest_job else None,
        "error_message": latest_job.error_message if latest_job else None,
        "finished_at": latest_job.finished_at.isoformat() if latest_job and latest_job.finished_at else None,
    }


@router.post("/plans/{plan_id}/approve", dependencies=[Depends(require_can_edit)])
def plans_approve(
    plan_id: int,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    plan = repo.get_plan(plan_id)
    if plan is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Plan not found")

    violations = repo.list_violations(plan_id)
    blockers = [v for v in violations if v.severity == "BLOCKER"]
    if blockers:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=409,
            detail=f"BLOCKER 違反が {len(blockers)} 件残っているため承認できません。労基法・配置基準違反を解消してください。",
        )

    plan.status = PlanStatus.APPROVED
    repo.save_plan(plan)
    return RedirectResponse(url=f"/shifts/plans/{plan_id}", status_code=303)


# ---------------------------------------------------------------------------
# Timefold 思想に基づくリアルタイムジョブ制御 & 差分レビュー API
# ---------------------------------------------------------------------------

@router.get("/solve-jobs/{job_id}/progress")
def get_solve_job_progress(job_id: int):
    """ジョブの求解進捗（フェーズ、進捗率%、暫定スコア）を取得する。"""
    from ..services.solver_manager import solver_manager
    return solver_manager.get_progress(job_id)


@router.post("/solve-jobs/{job_id}/cancel", dependencies=[Depends(require_can_edit)])
def cancel_solve_job(job_id: int):
    """実行中または待機中の求解ジョブを協調的に中断する。"""
    from ..services.solver_manager import solver_manager
    success = solver_manager.cancel_job(job_id)
    return {"job_id": job_id, "cancelled": success}


@router.get("/plans/{plan_id}/proposals/latest")
def get_latest_plan_proposal(
    plan_id: int,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
):
    """直近の求解提案と現行シフトの差分（Diff）を取得する。"""
    import json
    from ..db_models import ShiftPlanProposals

    proposal = repo.session.exec(
        select(ShiftPlanProposals)
        .where(ShiftPlanProposals.plan_id == plan_id)
        .order_by(ShiftPlanProposals.created_at.desc())
    ).first()

    if not proposal:
        return {"proposal": None}

    diff_data = {}
    if proposal.diff_summary:
        try:
            diff_data = json.loads(proposal.diff_summary)
        except Exception:
            pass

    return {
        "proposal_id": proposal.id,
        "job_id": proposal.job_id,
        "status": proposal.status,
        "hard_score": proposal.hard_score,
        "soft_score": proposal.soft_score,
        "diff": diff_data,
        "created_at": proposal.created_at.isoformat() if proposal.created_at else None,
    }


@router.post("/plans/{plan_id}/proposals/{proposal_id}/apply", dependencies=[Depends(require_can_edit)])
def apply_plan_proposal(
    plan_id: int,
    proposal_id: int,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
):
    """提案されたシフト差分を承認し、本番セルへコミット反映する。"""
    from ..services.diff_review import apply_proposal

    try:
        applied_count = apply_proposal(repo.session, proposal_id)
        return {"success": True, "applied_count": applied_count}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/plans/{plan_id}/proposals/{proposal_id}/reject", dependencies=[Depends(require_can_edit)])
def reject_plan_proposal(
    plan_id: int,
    proposal_id: int,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
):
    """提案されたシフトを破棄する。"""
    from ..services.diff_review import reject_proposal

    try:
        reject_proposal(repo.session, proposal_id)
        return {"success": True, "rejected": True}
    except Exception as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))

