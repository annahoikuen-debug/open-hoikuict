"""Parent portal billing and claim receipt routes."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from database import get_session
from facility_settings_service import is_parent_billing_enabled
from parent_billing_service import (
    get_parent_billing_claims_list,
    get_parent_claim_detail,
    get_parent_realtime_extended_care_summary,
)

router = APIRouter()


@router.get("/billing", response_class=HTMLResponse)
def parent_billing_index(
    request: Request,
    year_month: Optional[str] = Query(default=None),
    tab: Optional[str] = Query(default="realtime"),
    session: Session = Depends(get_session),
):
    from routers.parent_portal import _get_parent_account, templates

    if not is_parent_billing_enabled(session):
        raise HTTPException(status_code=404, detail="Not Found")

    current_parent_user = _get_parent_account(request, session)
    if not current_parent_user:
        return RedirectResponse(url="/parent-portal/login", status_code=303)

    realtime_summary = get_parent_realtime_extended_care_summary(
        session,
        family_id=current_parent_user.family_id,
        year_month=year_month,
    )
    claims = get_parent_billing_claims_list(
        session,
        family_id=current_parent_user.family_id,
    )

    return templates.TemplateResponse(
        request,
        "parent_portal/billing.html",
        {
            "request": request,
            "current_parent_user": current_parent_user,
            "parent_portal_mode": True,
            "realtime_summary": realtime_summary,
            "claims": claims,
            "active_tab": tab,
            "target_year_month": realtime_summary["year_month"],
        },
    )


@router.get("/billing/claims/{claim_id}", response_class=HTMLResponse)
def parent_billing_claim_detail_view(
    request: Request,
    claim_id: int,
    session: Session = Depends(get_session),
):
    from routers.parent_portal import _get_parent_account, templates

    if not is_parent_billing_enabled(session):
        raise HTTPException(status_code=404, detail="Not Found")

    current_parent_user = _get_parent_account(request, session)
    if not current_parent_user:
        return RedirectResponse(url="/parent-portal/login", status_code=303)

    claim_detail = get_parent_claim_detail(
        session,
        family_id=current_parent_user.family_id,
        claim_id=claim_id,
    )
    if not claim_detail:
        raise HTTPException(status_code=404, detail="請求明細が見つかりません")

    return templates.TemplateResponse(
        request,
        "parent_portal/billing_claim_detail.html",
        {
            "request": request,
            "current_parent_user": current_parent_user,
            "parent_portal_mode": True,
            "claim": claim_detail,
        },
    )
