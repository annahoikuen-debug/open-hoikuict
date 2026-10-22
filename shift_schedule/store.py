"""Shift schedule repository layer.

Provides the ``ShiftRepository`` protocol and its SQLModel implementation,
plus optimistic-lock helpers shared with the routers and services.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Protocol

from fastapi import Depends
from sqlmodel import Session, select

from common.optimistic_lock import claim_lock_orm
from database import get_session

from .db_models import (
    ShiftFacilitySettings,
    ShiftPlans,
    ShiftPlanCells,
    ShiftPlanningAudits,
    ShiftSolveJobs,
    ShiftViolations,
)


class ShiftRepository(Protocol):
    def facility_settings(self) -> ShiftFacilitySettings | None: ...

    def save_facility_settings(self, settings: ShiftFacilitySettings) -> None: ...

    def create_plan(self, plan: ShiftPlans) -> ShiftPlans: ...
    def get_plan(self, plan_id: int) -> ShiftPlans | None: ...
    def get_plan_by_month(self, target_month: str) -> ShiftPlans | None: ...
    def save_plan(self, plan: ShiftPlans) -> None: ...

    def create_plan_cell(self, cell: ShiftPlanCells) -> ShiftPlanCells: ...
    def get_plan_cell(self, plan_id: int, staff_user_id: Any, target_date: date) -> ShiftPlanCells | None: ...
    def list_plan_cells(self, plan_id: int) -> list[ShiftPlanCells]: ...
    def save_plan_cell(self, cell: ShiftPlanCells) -> None: ...

    def create_solve_job(self, job: ShiftSolveJobs) -> ShiftSolveJobs: ...
    def get_job(self, job_id: int) -> ShiftSolveJobs | None: ...
    def save_job(self, job: ShiftSolveJobs) -> None: ...

    def create_violation(self, violation: ShiftViolations) -> None: ...
    def list_violations(self, plan_id: int) -> list[ShiftViolations]: ...

    def create_audit(self, audit: ShiftPlanningAudits) -> None: ...
    def list_audits(self, plan_id: int) -> list[ShiftPlanningAudits]: ...


class SqlModelShiftRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---- facility settings -------------------------------------------------

    def facility_settings(self) -> ShiftFacilitySettings | None:
        return self.session.exec(select(ShiftFacilitySettings).where(ShiftFacilitySettings.id == 1)).first()

    def save_facility_settings(self, settings: ShiftFacilitySettings) -> None:
        self.session.add(settings)
        self.session.commit()

    # ---- plans -------------------------------------------------------------

    def create_plan(self, plan: ShiftPlans) -> ShiftPlans:
        self.session.add(plan)
        self.session.commit()
        self.session.refresh(plan)
        return plan

    def get_plan(self, plan_id: int) -> ShiftPlans | None:
        return self.session.get(ShiftPlans, plan_id)

    def get_plan_by_month(self, target_month: str) -> ShiftPlans | None:
        return self.session.exec(
            select(ShiftPlans).where(ShiftPlans.target_month == target_month)
        ).first()

    def save_plan(self, plan: ShiftPlans) -> None:
        """Optimistic-locked plan update via claim_lock_orm."""
        claim_lock_orm(
            self.session,
            model_class=ShiftPlans,
            where_col="id",
            id_val=plan.id,
            expected_version=plan.lock_version,
        )
        self.session.add(plan)
        self.session.commit()

    # ---- plan cells --------------------------------------------------------

    def create_plan_cell(self, cell: ShiftPlanCells) -> ShiftPlanCells:
        self.session.add(cell)
        self.session.commit()
        self.session.refresh(cell)
        return cell

    def get_plan_cell(self, plan_id: int, staff_user_id: Any, target_date: date) -> ShiftPlanCells | None:
        return self.session.exec(
            select(ShiftPlanCells).where(
                ShiftPlanCells.plan_id == plan_id,
                ShiftPlanCells.staff_user_id == staff_user_id,
                ShiftPlanCells.target_date == target_date,
            )
        ).first()

    def list_plan_cells(self, plan_id: int) -> list[ShiftPlanCells]:
        return self.session.exec(
            select(ShiftPlanCells).where(ShiftPlanCells.plan_id == plan_id)
        ).all()

    def save_plan_cell(self, cell: ShiftPlanCells) -> None:
        self.session.add(cell)
        self.session.commit()

    # ---- solve jobs --------------------------------------------------------

    def create_solve_job(self, job: ShiftSolveJobs) -> ShiftSolveJobs:
        self.session.add(job)
        self.session.commit()
        self.session.refresh(job)
        return job

    def get_job(self, job_id: int) -> ShiftSolveJobs | None:
        return self.session.get(ShiftSolveJobs, job_id)

    def save_job(self, job: ShiftSolveJobs) -> None:
        self.session.add(job)
        self.session.commit()

    # ---- violations --------------------------------------------------------

    def create_violation(self, violation: ShiftViolations) -> None:
        self.session.add(violation)
        self.session.commit()

    def list_violations(self, plan_id: int) -> list[ShiftViolations]:
        return self.session.exec(
            select(ShiftViolations).where(ShiftViolations.plan_id == plan_id)
        ).all()

    # ---- audits ------------------------------------------------------------

    def create_audit(self, audit: ShiftPlanningAudits) -> None:
        self.session.add(audit)
        self.session.commit()

    def list_audits(self, plan_id: int) -> list[ShiftPlanningAudits]:
        return self.session.exec(
            select(ShiftPlanningAudits)
            .where(ShiftPlanningAudits.target_plan_id == plan_id)
            .order_by(ShiftPlanningAudits.created_at.desc())
        ).all()


def ShiftRepositoryDep(session: Annotated[Session, Depends(get_session)]) -> ShiftRepository:
    return SqlModelShiftRepository(session)
