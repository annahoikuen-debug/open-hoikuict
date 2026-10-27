"""シフトプランルーター。

GET/POST /shifts/plans - プラン一覧・作成
GET /shifts/plans/{id} - プラン詳細
POST /shifts/plans/{id}/solve - 求解ジョブ発行
"""

from __future__ import annotations


from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select

from ..contracts import PlanStatus
from ..db_models import ShiftPlans, ShiftSolveJobs
from ..services.solve_jobs import cbc_available, schedule_solve
from ..store import ShiftRepository, ShiftRepositoryDep

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])


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
            "cbc_available": cbc_available(),
        },
    )


@router.post("/plans")
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
        from .services.gap_detector import detect_day_gap

        target_dates = sorted({c.target_date for c in cells})
        for td in target_dates[:3]:  # 最大3日分プレビュー
            gap_warnings.extend(detect_day_gap(repo.session, plan_id, td))

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
            "cbc_available": cbc_available(),
        },
    )


@router.post("/plans/{plan_id}/solve")
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

    if not cbc_available():
        from fastapi import HTTPException

        raise HTTPException(
            status_code=400,
            detail="シフト最適化ソルバー (CBC) がサーバー上で利用できません。管理者に環境設定を確認してください。",
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


@router.post("/plans/{plan_id}/approve")
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
