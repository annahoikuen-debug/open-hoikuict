"""職員マスタ管理ルーター。

GET /shifts/staff - 職員マスタ一覧
POST /shifts/staff/{staff_user_id}/qualifications - 資格登録
POST /shifts/staff/{staff_user_id}/contract - 雇用契約登録
POST /shifts/staff/{staff_user_id}/preferences - シフト希望（早番・遅番避け）登録
POST /shifts/staff/import - CSV 一括取込
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import select

from audit_logger import record_audit_event
from auth import get_optional_current_staff_user, require_can_edit
from models import User
from shiftai.domain import EmploymentType, Role
from ..db_models import StaffContracts, StaffQualifications, StaffShiftPreferences
from ..store import ShiftRepository, ShiftRepositoryDep

router = APIRouter(prefix="/shifts", tags=["shift_schedule"])


def _extract_actor(request: Request) -> tuple[str, Optional[str]]:
    staff = get_optional_current_staff_user(request)
    staff_id_str = staff.staff_id if staff else None
    actor_id = str(staff.user_id) if staff and staff.user_id else staff_id_str
    role_str = staff.role.value if staff and hasattr(staff.role, "value") else (str(staff.role) if staff else None)
    return actor_id or "anonymous", role_str


@router.get("/staff", response_class=HTMLResponse, dependencies=[Depends(require_can_edit)])
def staff_master_list(
    request: Request,
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> HTMLResponse:
    today = date.today()
    users = repo.session.exec(
        select(User).where(User.is_active == True).order_by(User.staff_sort_order, User.display_name)  # noqa: E712
    ).all()

    quals = repo.session.exec(
        select(StaffQualifications).where(
            (StaffQualifications.effective_to.is_(None)) | (StaffQualifications.effective_to >= today)
        )
    ).all()
    qual_map: dict[str, list[StaffQualifications]] = {}
    for q in quals:
        qual_map.setdefault(q.staff_user_id, []).append(q)

    contracts = repo.session.exec(
        select(StaffContracts).where(
            (StaffContracts.effective_to.is_(None)) | (StaffContracts.effective_to >= today)
        )
    ).all()
    contract_map: dict[str, StaffContracts] = {c.staff_user_id: c for c in contracts}

    prefs = repo.session.exec(select(StaffShiftPreferences)).all()
    pref_map: dict[str, StaffShiftPreferences] = {p.staff_user_id: p for p in prefs}

    staff_data = []
    for u in users:
        u_hex = u.id.hex if hasattr(u.id, "hex") else str(u.id)
        u_str = str(u.id)
        u_quals = qual_map.get(u_hex) or qual_map.get(u_str) or []
        u_contract = contract_map.get(u_hex) or contract_map.get(u_str)
        u_pref = pref_map.get(u_hex) or pref_map.get(u_str)

        staff_data.append({
            "user": u,
            "user_id_hex": u_hex,
            "qualifications": u_quals,
            "contract": u_contract,
            "preference": u_pref,
            "has_qual": len(u_quals) > 0,
            "has_contract": u_contract is not None,
        })

    from template_utils import create_templates
    templates = create_templates()
    return templates.TemplateResponse(
        request,
        "shift_schedule/staff_master.html",
        {
            "request": request,
            "staff_list": staff_data,
            "role_options": [r.value for r in Role],
            "employment_options": [e.value for e in EmploymentType],
        },
    )


@router.post("/staff/{staff_user_id}/qualifications", dependencies=[Depends(require_can_edit)])
def staff_save_qualification(
    staff_user_id: str,
    request: Request,
    role: str = Form(...),
    effective_from: str = Form(...),
    effective_to: Optional[str] = Form(None),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    valid_roles = [r.value for r in Role]
    if role not in valid_roles:
        raise HTTPException(status_code=400, detail=f"不正な資格です: {role}。選択肢: {', '.join(valid_roles)}")

    eff_from_date = date.fromisoformat(effective_from)
    eff_to_date = date.fromisoformat(effective_to) if effective_to else None

    # staff_user_id は hex または UUID
    try:
        clean_uid = UUID(staff_user_id).hex
    except Exception:
        clean_uid = staff_user_id

    qual = StaffQualifications(
        staff_user_id=clean_uid,
        role=role,
        effective_from=eff_from_date,
        effective_to=eff_to_date,
    )
    repo.session.add(qual)
    repo.session.commit()

    actor_id, actor_role = _extract_actor(request)
    record_audit_event(
        actor_user_id=actor_id,
        actor_role=actor_role,
        target_resource="staff_qualifications",
        resource_id=qual.id,
        action="qualification_created",
        ip_address=request.client.host if request.client else None,
        detail={"staff_user_id": clean_uid, "role": role, "effective_from": effective_from},
    )
    return RedirectResponse(url="/shifts/staff", status_code=303)


@router.post("/staff/{staff_user_id}/contract", dependencies=[Depends(require_can_edit)])
def staff_save_contract(
    staff_user_id: str,
    request: Request,
    employment_type: str = Form("正職員"),
    weekly_hours: Optional[float] = Form(None),
    daily_hours: Optional[float] = Form(None),
    earliest_start: Optional[str] = Form(None),
    latest_end: Optional[str] = Form(None),
    can_work_holiday: bool = Form(False),
    overtime_allowed: bool = Form(False),
    has_36_agreement: bool = Form(True),
    variable_working_hours: bool = Form(False),
    effective_from: str = Form(...),
    effective_to: Optional[str] = Form(None),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    if weekly_hours is not None and weekly_hours <= 0:
        raise HTTPException(status_code=400, detail="週所定時間は0より大きい数値を入力してください。")

    try:
        clean_uid = UUID(staff_user_id).hex
    except Exception:
        clean_uid = staff_user_id

    eff_from_date = date.fromisoformat(effective_from)
    eff_to_date = date.fromisoformat(effective_to) if effective_to else None

    # 既存有効契約をクローズまたは置換
    existing = repo.session.exec(
        select(StaffContracts).where(
            StaffContracts.staff_user_id == clean_uid,
            (StaffContracts.effective_to.is_(None)) | (StaffContracts.effective_to >= eff_from_date),
        )
    ).all()
    for ex in existing:
        ex.effective_to = eff_from_date
        repo.session.add(ex)

    contract = StaffContracts(
        staff_user_id=clean_uid,
        employment_type=employment_type,
        weekly_hours=weekly_hours,
        daily_hours=daily_hours,
        earliest_start=earliest_start or None,
        latest_end=latest_end or None,
        can_work_holiday=can_work_holiday,
        overtime_allowed=overtime_allowed,
        has_36_agreement=has_36_agreement,
        variable_working_hours=variable_working_hours,
        effective_from=eff_from_date,
        effective_to=eff_to_date,
    )
    repo.session.add(contract)
    repo.session.commit()

    actor_id, actor_role = _extract_actor(request)
    record_audit_event(
        actor_user_id=actor_id,
        actor_role=actor_role,
        target_resource="staff_contracts",
        resource_id=contract.id,
        action="contract_saved",
        ip_address=request.client.host if request.client else None,
        detail={"staff_user_id": clean_uid, "employment_type": employment_type},
    )
    return RedirectResponse(url="/shifts/staff", status_code=303)


@router.post("/staff/{staff_user_id}/preferences", dependencies=[Depends(require_can_edit)])
def staff_save_preference(
    staff_user_id: str,
    request: Request,
    avoid_early: bool = Form(False),
    avoid_late: bool = Form(False),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    try:
        clean_uid = UUID(staff_user_id).hex
    except Exception:
        clean_uid = staff_user_id

    pref = repo.session.exec(
        select(StaffShiftPreferences).where(StaffShiftPreferences.staff_user_id == clean_uid)
    ).first()
    if pref is None:
        pref = StaffShiftPreferences(
            staff_user_id=clean_uid,
            avoid_early=avoid_early,
            avoid_late=avoid_late,
        )
    else:
        pref.avoid_early = avoid_early
        pref.avoid_late = avoid_late
    repo.session.add(pref)
    repo.session.commit()
    return RedirectResponse(url="/shifts/staff", status_code=303)


@router.post("/staff/import", dependencies=[Depends(require_can_edit)])
async def staff_import_csv(
    request: Request,
    file: UploadFile = File(...),
    repo: ShiftRepository = Depends(ShiftRepositoryDep),
) -> RedirectResponse:
    from ..services.staff_master_import import import_staff_master_csv

    content = await file.read()
    message = import_staff_master_csv(repo.session, content)
    # 結果メッセージを flash または query param で伝達
    return RedirectResponse(url="/shifts/staff?msg=" + message, status_code=303)
