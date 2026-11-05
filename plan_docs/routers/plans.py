from __future__ import annotations

import calendar
from datetime import date, timedelta
import re
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import select

from ..auth_adapter import CurrentUser, require_can_edit, require_classroom_access
from ..auth_adapter import DEFAULT_CLASSROOM_REFS
from ..contracts import AGE_CLASS_OPTIONS, DocumentStatus, DocumentType
from ..db_models import PlanDocumentRow
from ..services.continuity import iso_week_monday, previous_business_day, previous_month
from ..services.generators import (
    generate_annual_plan,
    generate_monthly_plan,
    generate_simple_daily_plan,
    generate_weekly_plan,
    week_start_date_from_target_week,
)
from ..services.daily_examples import (
    DailyExampleCorpusError,
    corpus_metadata,
    get_daily_plan_example,
    list_daily_plan_examples,
)
from ..services.daily_reflections import (
    reflection_state,
    reflection_state_label,
    reflections_by_document_id,
)
from ..store import DocumentRepositoryDep, SqlModelDocumentRepository
from ..templating import render_template
from time_utils import local_today


router = APIRouter(tags=["plans"])


def _annual_documents_for_user(user: CurrentUser, repository: SqlModelDocumentRepository):
    classroom_refs = None if user.is_admin else user.classroom_refs
    return repository.list(
        nursery_ref=user.nursery_ref,
        classroom_refs=classroom_refs,
        document_type=DocumentType.ANNUAL_PLAN,
    )


def _documents_for_user(
    user: CurrentUser,
    repository: SqlModelDocumentRepository,
    document_type: DocumentType,
    *,
    classroom_ref: str | None = None,
    limit: int = 8,
):
    classroom_refs = None if user.is_admin else user.classroom_refs
    documents = repository.list(
        nursery_ref=user.nursery_ref,
        classroom_refs=classroom_refs,
        document_type=document_type,
    )
    if classroom_ref:
        documents = [document for document in documents if document.classroom_ref == classroom_ref]
    documents = [document for document in documents if document.status != DocumentStatus.ARCHIVED]
    return documents[:limit]


def _monthly_documents_for_user(user: CurrentUser, repository: SqlModelDocumentRepository, *, classroom_ref: str | None = None, limit: int = 8):
    return _documents_for_user(user, repository, DocumentType.MONTHLY_PLAN, classroom_ref=classroom_ref, limit=limit)


def _weekly_documents_for_user(user: CurrentUser, repository: SqlModelDocumentRepository, *, classroom_ref: str | None = None, limit: int = 8):
    return _documents_for_user(user, repository, DocumentType.WEEKLY_PLAN, classroom_ref=classroom_ref, limit=limit)


def _resolve_parent_document_id(
    raw_value: str,
    *,
    user: CurrentUser,
    repository: SqlModelDocumentRepository,
    classroom_ref: str,
    expected_type: DocumentType,
) -> tuple[str, str]:
    value = (raw_value or "").strip()
    if not value:
        return "", "上位計画の接続未確認"
    try:
        document_id = int(value)
    except ValueError:
        return "", "上位計画の接続未確認"
    document = repository.get(document_id)
    if (
        document is None
        or document.nursery_ref != user.nursery_ref
        or document.classroom_ref != classroom_ref
        or document.document_type != expected_type
    ):
        return "", "上位計画の接続未確認"
    return str(document.id), ""


def _form_values(**values: str) -> dict[str, str]:
    return {key: value for key, value in values.items()}


def _list_value(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


def _daily_activity_text(document) -> str:
    activities: list[str] = []
    if document.schedule:
        for row in sorted(document.schedule.rows, key=lambda item: item.order):
            activity = (row.label or "").strip()
            if activity and activity not in activities:
                activities.append(activity)
    if activities:
        return " / ".join(activities)
    for section in document.sections:
        if section.section_key == "daily_content" and section.body.strip():
            return section.body.strip()
    return "活動内容未入力"


def _adjacent_month(year: int, month: int, offset: int) -> tuple[int, int]:
    month_index = year * 12 + month - 1 + offset
    return month_index // 12, month_index % 12 + 1


def _age_class_from_classroom_ref(classroom_ref: str) -> str:
    match = re.search(r"([0-5])\s*歳児", classroom_ref or "")
    return f"{match.group(1)}歳児" if match else ""


@router.get("/daily-plans/")
def daily_plan_calendar(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    year: int | None = None,
    month: int | None = None,
    classroom_ref: str = "",
):
    today = local_today()
    selected_year = year if year is not None and 2000 <= year <= 2100 else today.year
    selected_month = month if month is not None and 1 <= month <= 12 else today.month
    accessible_classrooms = list(user.classroom_refs or DEFAULT_CLASSROOM_REFS)
    selected_classroom_ref = (
        classroom_ref if classroom_ref in accessible_classrooms else ""
    )
    displayed_classrooms = (
        [selected_classroom_ref] if selected_classroom_ref else accessible_classrooms
    )
    documents = repository.list(
        nursery_ref=user.nursery_ref,
        classroom_refs=None if user.is_admin else user.classroom_refs,
        document_type=DocumentType.DAILY_PLAN,
    )
    documents_by_date_and_classroom = {}
    month_prefix = f"{selected_year:04d}-{selected_month:02d}-"
    for document in documents:
        if (
            not document.target_date
            or not document.target_date.startswith(month_prefix)
            or document.classroom_ref not in displayed_classrooms
        ):
            continue
        documents_by_date_and_classroom.setdefault(
            (document.target_date, document.classroom_ref), document
        )
    reflections = reflections_by_document_id(
        repository.session,
        [document.id for document in documents if document.id is not None],
    )

    weeks = []
    for week in calendar.Calendar(firstweekday=calendar.MONDAY).monthdatescalendar(
        selected_year, selected_month
    ):
        days = []
        for day in week[:5]:
            in_month = day.month == selected_month
            entries = []
            if in_month:
                day_key = day.isoformat()
                for classroom in displayed_classrooms:
                    document = documents_by_date_and_classroom.get((day_key, classroom))
                    age_class = _age_class_from_classroom_ref(classroom)
                    reflection = reflections.get(document.id) if document else None
                    entries.append(
                        {
                            "classroom_ref": classroom,
                            "activity": _daily_activity_text(document) if document else "未作成",
                            "is_created": document is not None,
                            "reflection_state": reflection_state(reflection) if document else "",
                            "reflection_label": reflection_state_label(reflection) if document else "",
                            "url": (
                                f"/plans/documents/{document.id}"
                                if document
                                else "/plans/daily-plans/new?"
                                f"target_date={day_key}&classroom_ref={quote(classroom)}"
                                f"&age_class={quote(age_class)}&month={selected_month}"
                            ),
                        }
                    )
            days.append(
                {
                    "date": day,
                    "in_month": in_month,
                    "is_today": day == today,
                    "entries": entries,
                }
            )
        if any(day["in_month"] for day in days):
            weeks.append(days)

    # 週案保有週の日付を集約（未作成セルに「週案から作成」を表示するため）。
    weekly_plan_dates: set[str] = set()
    if selected_classroom_ref:
        month_first = date(selected_year, selected_month, 1)
        if selected_month == 12:
            month_last = date(selected_year + 1, 1, 1) - timedelta(days=1)
        else:
            month_last = date(selected_year, selected_month + 1, 1) - timedelta(days=1)
        weekly_rows = repository.session.exec(select(PlanDocumentRow).where(
            PlanDocumentRow.document_type == DocumentType.WEEKLY_PLAN.value,
            PlanDocumentRow.nursery_ref == user.nursery_ref,
            PlanDocumentRow.classroom_ref == selected_classroom_ref,
        )).all()
        for w in weekly_rows:
            if w.status == DocumentStatus.ARCHIVED.value or not w.week_start_date:
                continue
            try:
                ws = date.fromisoformat(w.week_start_date)
            except ValueError:
                continue
            for offset in range(5):
                d = ws + timedelta(days=offset)
                if month_first <= d <= month_last:
                    weekly_plan_dates.add(d.isoformat())

    previous_year, previous_month = _adjacent_month(selected_year, selected_month, -1)
    next_year, next_month = _adjacent_month(selected_year, selected_month, 1)
    classroom_query = (
        f"&classroom_ref={quote(selected_classroom_ref)}"
        if selected_classroom_ref
        else ""
    )
    return render_template(
        request,
        "daily_plans/calendar.html",
        user=user,
        calendar_year=selected_year,
        calendar_month=selected_month,
        weeks=weeks,
        weekday_labels=("月", "火", "水", "木", "金"),
        classroom_refs=accessible_classrooms,
        selected_classroom_ref=selected_classroom_ref,
        weekly_plan_dates=weekly_plan_dates,
        previous_month_url=(
            f"/plans/daily-plans/?year={previous_year}&month={previous_month}{classroom_query}"
        ),
        next_month_url=(
            f"/plans/daily-plans/?year={next_year}&month={next_month}{classroom_query}"
        ),
    )


@router.get("/annual-plans/new")
def new_annual_plan(request: Request, user: CurrentUser):
    return render_template(
        request,
        "annual_plans/form.html",
        user=user,
        default_classroom_ref=user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0],
    )


@router.post("/annual-plans")
def create_annual_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    school_year: Annotated[str, Form()] = "2026",
    class_name: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    class_outlook: Annotated[str, Form()] = "",
    focus_growth: Annotated[str, Form()] = "",
    annual_events: Annotated[str, Form()] = "",
    seasonal_context: Annotated[str, Form()] = "",
    care_points: Annotated[str, Form()] = "",
    family_collaboration_policy: Annotated[str, Form()] = "",
    health_safety_policy: Annotated[str, Form()] = "",
    preferred_expressions: Annotated[str, Form()] = "",
    term_1_note: Annotated[str, Form()] = "",
    term_2_note: Annotated[str, Form()] = "",
    term_3_note: Annotated[str, Form()] = "",
    term_4_note: Annotated[str, Form()] = "",
):
    require_can_edit(user, request)
    selected_classroom_ref = classroom_ref or class_name or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    selected_class_name = class_name or selected_classroom_ref
    require_classroom_access(user, selected_classroom_ref)
    document = generate_annual_plan(
        {
            "school_year": school_year,
            "class_name": selected_class_name,
            "classroom_ref": selected_classroom_ref,
            "owner_name": owner_name,
            "class_outlook": class_outlook,
            "focus_growth": focus_growth,
            "annual_events": annual_events,
            "seasonal_context": seasonal_context,
            "care_points": care_points,
            "family_collaboration_policy": family_collaboration_policy,
            "health_safety_policy": health_safety_policy,
            "preferred_expressions": preferred_expressions,
            "term_1_note": term_1_note,
            "term_2_note": term_2_note,
            "term_3_note": term_3_note,
            "term_4_note": term_4_note,
        },
        user,
    )
    created = repository.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.get("/monthly-plans/new")
def new_monthly_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    target_month: str = "",
    classroom_ref: str = "",
):
    default_classroom_ref = (
        classroom_ref
        if classroom_ref in user.classroom_refs
        else (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    )
    previous_reflection = ""
    previous_month_source = ""
    if target_month:
        try:
            prev = previous_month(target_month)
        except ValueError:
            prev = None
        if prev:
            monthly_rows = repository.session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.MONTHLY_PLAN.value,
                PlanDocumentRow.nursery_ref == user.nursery_ref,
                PlanDocumentRow.classroom_ref == default_classroom_ref,
                PlanDocumentRow.target_month == prev,
            )).all()
            prev_monthly_doc = None
            for candidate in monthly_rows:
                if candidate.status != DocumentStatus.ARCHIVED.value and candidate.sections:
                    prev_monthly_doc = candidate
                    break
            if prev_monthly_doc:
                for section in prev_monthly_doc.sections:
                    if section.get("section_key") == "monthly_reflection_viewpoint":
                        previous_reflection = section.get("body", "") or ""
                        previous_month_source = prev_monthly_doc.title or prev
                        break
    form_values = {
        "target_month": target_month,
        "classroom_ref": default_classroom_ref,
        "previous_reflection": previous_reflection,
        "previous_month_source": previous_month_source,
    }
    return render_template(
        request,
        "monthly_plans/form.html",
        user=user,
        annual_documents=_annual_documents_for_user(user, repository),
        default_classroom_ref=default_classroom_ref,
        form_values=form_values,
    )


@router.post("/monthly-plans")
def create_monthly_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    target_month: Annotated[str, Form()] = "",
    class_name: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    related_annual_summary: Annotated[str, Form()] = "",
    previous_reflection: Annotated[str, Form()] = "",
    current_children_snapshot: Annotated[str, Form()] = "",
    play_interests: Annotated[str, Form()] = "",
    seasonal_context: Annotated[str, Form()] = "",
    family_context: Annotated[str, Form()] = "",
    class_notes: Annotated[str, Form()] = "",
):
    require_can_edit(user, request)
    selected_classroom_ref = classroom_ref or class_name or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    selected_class_name = class_name or selected_classroom_ref
    require_classroom_access(user, selected_classroom_ref)
    document = generate_monthly_plan(
        {
            "target_month": target_month,
            "class_name": selected_class_name,
            "classroom_ref": selected_classroom_ref,
            "owner_name": owner_name,
            "related_annual_summary": related_annual_summary,
            "previous_reflection": previous_reflection,
            "current_children_snapshot": current_children_snapshot,
            "play_interests": play_interests,
            "seasonal_context": seasonal_context,
            "family_context": family_context,
            "class_notes": class_notes,
        },
        user,
    )
    created = repository.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.get("/weekly-plans/new")
def new_weekly_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    target_week: str = "",
    classroom_ref: str = "",
):
    default_classroom_ref = (
        classroom_ref
        if classroom_ref in user.classroom_refs
        else (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    )
    previous_week_reflection = ""
    previous_week_source = ""
    if target_week:
        try:
            week_start = week_start_date_from_target_week(target_week)
        except ValueError:
            week_start = None
        if week_start:
            prev_monday = week_start - timedelta(weeks=1)
            prev_week_start = prev_monday.isoformat()
            weekly_rows = repository.session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.WEEKLY_PLAN.value,
                PlanDocumentRow.nursery_ref == user.nursery_ref,
                PlanDocumentRow.classroom_ref == default_classroom_ref,
                PlanDocumentRow.week_start_date == prev_week_start,
            )).all()
            prev_weekly_doc = None
            for candidate in weekly_rows:
                if candidate.status != DocumentStatus.ARCHIVED.value and candidate.sections:
                    prev_weekly_doc = candidate
                    break
            if prev_weekly_doc:
                for section in prev_weekly_doc.sections:
                    if section.get("section_key") == "weekly_reflection_viewpoint":
                        previous_week_reflection = section.get("body", "") or ""
                        previous_week_source = prev_weekly_doc.title or prev_weekly_doc.week_start_date or ""
                        break
    form_values = {
        "target_week": target_week,
        "classroom_ref": default_classroom_ref,
        "previous_week_reflection": previous_week_reflection,
        "previous_week_source": previous_week_source,
    }
    return render_template(
        request,
        "weekly_plans/form.html",
        user=user,
        default_classroom_ref=default_classroom_ref,
        age_class_options=AGE_CLASS_OPTIONS,
        monthly_documents=_monthly_documents_for_user(user, repository, classroom_ref=default_classroom_ref),
        errors=[],
        form_values=form_values,
    )


@router.post("/weekly-plans")
def create_weekly_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    target_week: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
    age_class: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    parent_document_id: Annotated[str, Form()] = "",
    related_monthly_summary: Annotated[str, Form()] = "",
    previous_week_reflection: Annotated[str, Form()] = "",
    current_children_snapshot: Annotated[str, Form()] = "",
    weekly_activities_note: Annotated[str, Form()] = "",
    seasonal_context: Annotated[str, Form()] = "",
    family_context: Annotated[str, Form()] = "",
    class_notes: Annotated[str, Form()] = "",
    include_saturday: Annotated[str, Form()] = "",
):
    require_can_edit(user, request)
    selected_classroom_ref = classroom_ref or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    require_classroom_access(user, selected_classroom_ref)
    selected_class_name = selected_classroom_ref
    errors: list[str] = []
    if not target_week:
        errors.append("対象週を選択してください。")
    else:
        try:
            week_start_date_from_target_week(target_week)
        except ValueError:
            errors.append("対象週を正しい形式で選択してください。")
    if not age_class:
        errors.append("年齢を選択してください。")
    resolved_parent_id, connection_warning = _resolve_parent_document_id(
        parent_document_id,
        user=user,
        repository=repository,
        classroom_ref=selected_classroom_ref,
        expected_type=DocumentType.MONTHLY_PLAN,
    )
    if not parent_document_id and related_monthly_summary.strip():
        connection_warning = ""
    values = _form_values(
        target_week=target_week,
        classroom_ref=selected_classroom_ref,
        age_class=age_class,
        owner_name=owner_name,
        parent_document_id=parent_document_id,
        related_monthly_summary=related_monthly_summary,
        previous_week_reflection=previous_week_reflection,
        current_children_snapshot=current_children_snapshot,
        weekly_activities_note=weekly_activities_note,
        seasonal_context=seasonal_context,
        family_context=family_context,
        class_notes=class_notes,
        include_saturday=include_saturday,
    )
    if errors:
        return render_template(
            request,
            "weekly_plans/form.html",
            user=user,
            default_classroom_ref=selected_classroom_ref,
            age_class_options=AGE_CLASS_OPTIONS,
            monthly_documents=_monthly_documents_for_user(user, repository, classroom_ref=selected_classroom_ref),
            errors=errors,
            form_values=values,
        )
    document = generate_weekly_plan(
        {
            **values,
            "class_name": selected_class_name,
            "parent_document_id": resolved_parent_id,
            "connection_warning": connection_warning,
        },
        user,
    )
    created = repository.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.get("/daily-plans/new")
def new_daily_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    age_class: str = "",
    month: int | None = None,
    q: str = "",
    example_id: str = "",
    target_date: str = "",
    classroom_ref: str = "",
):
    default_classroom_ref = (
        classroom_ref
        if classroom_ref in user.classroom_refs
        else (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    )
    inferred_month = None
    if target_date:
        try:
            inferred_month = date.fromisoformat(target_date).month
        except ValueError:
            inferred_month = None
    selected_month = (
        month
        if month is not None and 1 <= month <= 12
        else (inferred_month or local_today().month)
    )
    selected_age_class = (
        age_class
        if age_class in AGE_CLASS_OPTIONS
        else _age_class_from_classroom_ref(default_classroom_ref)
    )
    weekly_prefill_rows: list[dict[str, str]] = []
    weekly_parent_id: int | None = None
    weekly_source_ref: str | None = None
    if target_date and classroom_ref:
        try:
            target_d = date.fromisoformat(target_date)
        except ValueError:
            target_d = None
        if target_d and 0 <= target_d.weekday() <= 4:
            monday = iso_week_monday(target_d)
            weekday_key = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][target_d.weekday()]
            weekly_rows = repository.session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.WEEKLY_PLAN.value,
                PlanDocumentRow.nursery_ref == user.nursery_ref,
                PlanDocumentRow.classroom_ref == classroom_ref,
                PlanDocumentRow.week_start_date == monday.isoformat(),
            )).all()
            weekly_doc = None
            for candidate in weekly_rows:
                if candidate.status != DocumentStatus.ARCHIVED.value and candidate.schedule:
                    weekly_doc = candidate
                    break
            if weekly_doc and weekly_doc.schedule:
                for row in weekly_doc.schedule.get("rows", []):
                    if row.get("row_key") != weekday_key:
                        continue
                    cells = row.get("cells", {})
                    activity = (cells.get("activity") or {}).get("body", "") if isinstance(cells.get("activity"), dict) else ""
                    support = (cells.get("support") or {}).get("body", "") if isinstance(cells.get("support"), dict) else ""
                    if activity or support:
                        weekly_parent_id = int(weekly_doc.id or 0)
                        weekly_source_ref = f"weekly.document:{weekly_doc.id}"
                        weekly_prefill_rows = [{
                            "row_key": "row_1",
                            "time_label": "",
                            "activity_name": activity,
                            "child_state": "",
                            "support": support,
                            "considerations": "",
                        }]
                        break
    previous_day_reflection = ""
    previous_day_date = ""
    if target_date and classroom_ref:
        try:
            target_d = date.fromisoformat(target_date)
        except ValueError:
            target_d = None
        if target_d:
            prev_business = previous_business_day(target_d)
            prev_daily_rows = repository.session.exec(select(PlanDocumentRow).where(
                PlanDocumentRow.document_type == DocumentType.DAILY_PLAN.value,
                PlanDocumentRow.nursery_ref == user.nursery_ref,
                PlanDocumentRow.classroom_ref == classroom_ref,
                PlanDocumentRow.target_date == prev_business.isoformat(),
            )).all()
            prev_daily_doc = None
            for candidate in prev_daily_rows:
                if candidate.status != DocumentStatus.ARCHIVED.value:
                    prev_daily_doc = candidate
                    break
            if prev_daily_doc:
                refl_map = reflections_by_document_id(repository.session, [int(prev_daily_doc.id or 0)])
                refl_rows = list(refl_map.values())
                submitted = [r for r in refl_rows if r.status == "submitted"]
                if submitted:
                    previous_day_reflection = submitted[0].body or ""
                    previous_day_date = prev_business.isoformat()
    selected_example = None
    examples = []
    corpus_info: dict[str, str] = {}
    corpus_error = ""
    try:
        examples = list_daily_plan_examples(
            age_class=selected_age_class or None,
            month=selected_month,
            query=q,
        )
        selected_example = get_daily_plan_example(example_id) if example_id else None
        corpus_info = corpus_metadata()
    except DailyExampleCorpusError as exc:
        corpus_error = str(exc)
    values = {
        "target_date": target_date,
        "classroom_ref": default_classroom_ref,
        "age_class": selected_age_class,
        "daily_aims": "\n".join(selected_example.aims) if selected_example else "",
        "daily_content": selected_example.content if selected_example else "",
        "example_id": selected_example.id if selected_example else "",
        "example_source_ref": selected_example.source_ref if selected_example else "",
        "timeline_rows": [
            {
                "row_key": f"corpus_{block.position + 1}",
                "time_label": block.time_label,
                "activity_name": " / ".join(
                    value
                    for value in (block.activity_name, block.activity_text)
                    if value
                ),
                "child_state": block.child_state,
                "support": block.support,
                "considerations": block.considerations,
            }
            for block in selected_example.activity_blocks
        ]
        if selected_example
        else weekly_prefill_rows or [
            {
                "row_key": "row_1",
                "time_label": "",
                "activity_name": "",
                "child_state": "",
                "support": "",
                "considerations": "",
            }
        ],
    }
    values["weekly_parent_id"] = weekly_parent_id
    values["weekly_source_ref"] = weekly_source_ref
    values["previous_day_reflection"] = previous_day_reflection
    values["previous_day_date"] = previous_day_date
    return render_template(
        request,
        "daily_plans/form.html",
        user=user,
        default_classroom_ref=default_classroom_ref,
        age_class_options=AGE_CLASS_OPTIONS,
        weekly_documents=[],
        errors=[],
        form_values=values,
        examples=examples,
        selected_month=selected_month,
        search_query=q,
        corpus_info=corpus_info,
        corpus_error=corpus_error,
        weekly_parent_id=weekly_parent_id,
        weekly_source_ref=weekly_source_ref,
        previous_day_reflection=previous_day_reflection,
        previous_day_date=previous_day_date,
    )


@router.post("/daily-plans")
def create_daily_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    target_date: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
    age_class: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    daily_aims: Annotated[str, Form()] = "",
    daily_content: Annotated[str, Form()] = "",
    timeline_row_key: Annotated[list[str], Form()] = [],
    timeline_time: Annotated[list[str], Form()] = [],
    timeline_activity: Annotated[list[str], Form()] = [],
    timeline_children: Annotated[list[str], Form()] = [],
    timeline_support: Annotated[list[str], Form()] = [],
    timeline_considerations: Annotated[list[str], Form()] = [],
    example_id: Annotated[str, Form()] = "",
    example_source_ref: Annotated[str, Form()] = "",
    parent_document_id: Annotated[str, Form()] = "",
):
    require_can_edit(user, request)
    selected_classroom_ref = classroom_ref or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    require_classroom_access(user, selected_classroom_ref)
    selected_class_name = selected_classroom_ref
    errors: list[str] = []
    if not target_date:
        errors.append("対象日を選択してください。")
    else:
        try:
            date.fromisoformat(target_date)
        except ValueError:
            errors.append("対象日を正しい形式で選択してください。")
    if not age_class:
        errors.append("年齢を選択してください。")
    resolved_parent_id: int | None = None
    weekly_source_ref: str | None = None
    if parent_document_id:
        try:
            candidate_id = int(parent_document_id)
        except ValueError:
            candidate_id = None
        if candidate_id is None:
            errors.append("週案の指定が不正です。")
        else:
            weekly_doc = repository.session.get(PlanDocumentRow, candidate_id)
            if (
                weekly_doc is None
                or weekly_doc.document_type != DocumentType.WEEKLY_PLAN.value
                or weekly_doc.nursery_ref != user.nursery_ref
                or weekly_doc.classroom_ref != selected_classroom_ref
                or weekly_doc.status == DocumentStatus.ARCHIVED.value
                or not weekly_doc.schedule
            ):
                errors.append("週案が見つかりません。")
            else:
                try:
                    target_d = date.fromisoformat(target_date)
                except ValueError:
                    target_d = None
                if target_d is None:
                    errors.append("対象日を正しい形式で選択してください。")
                else:
                    monday = iso_week_monday(target_d)
                    if weekly_doc.week_start_date != monday.isoformat():
                        errors.append("週案の対象週と日案の対象日が一致しません。")
                    else:
                        resolved_parent_id = candidate_id
                        weekly_source_ref = f"weekly.document:{candidate_id}"
    row_count = max(
        len(timeline_row_key),
        len(timeline_time),
        len(timeline_activity),
        len(timeline_children),
        len(timeline_support),
        len(timeline_considerations),
    )
    timeline_rows = [
        {
            "row_key": _list_value(timeline_row_key, index) or f"row_{index + 1}",
            "time_label": _list_value(timeline_time, index),
            "activity_name": _list_value(timeline_activity, index),
            "child_state": _list_value(timeline_children, index),
            "support": _list_value(timeline_support, index),
            "considerations": _list_value(timeline_considerations, index),
        }
        for index in range(row_count)
    ]
    if not any(
        any(str(row[key]).strip() for key in ("time_label", "activity_name", "child_state", "support", "considerations"))
        for row in timeline_rows
    ):
        errors.append("1日の流れを1行以上入力してください。")
    selected_example = None
    if example_id:
        try:
            selected_example = get_daily_plan_example(example_id)
        except DailyExampleCorpusError:
            selected_example = None
    values = _form_values(
        target_date=target_date,
        classroom_ref=selected_classroom_ref,
        age_class=age_class,
        owner_name=owner_name,
        daily_aims=daily_aims,
        daily_content=daily_content,
        example_id=selected_example.id if selected_example else "",
        example_source_ref=(selected_example.source_ref if selected_example else example_source_ref),
        parent_document_id=str(resolved_parent_id) if resolved_parent_id is not None else "",
        weekly_source_ref=weekly_source_ref or "",
    )
    values["timeline_rows"] = timeline_rows or [
        {
            "row_key": "row_1",
            "time_label": "",
            "activity_name": "",
            "child_state": "",
            "support": "",
            "considerations": "",
        }
    ]
    if errors:
        return render_template(
            request,
            "daily_plans/form.html",
            user=user,
            default_classroom_ref=selected_classroom_ref,
            age_class_options=AGE_CLASS_OPTIONS,
            weekly_documents=[],
            errors=errors,
            form_values=values,
            examples=[],
            selected_month=local_today().month,
            search_query="",
            corpus_info={},
            corpus_error="",
        )
    document = generate_simple_daily_plan(
        {
            **values,
            "class_name": selected_class_name,
            "parent_document_id": str(resolved_parent_id) if resolved_parent_id is not None else "",
            "weekly_source_ref": weekly_source_ref or "",
        },
        user,
    )
    created = repository.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.post("/daily-plans/bulk-from-weekly")
def bulk_daily_from_weekly(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    target_week: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
):
    """週案グリッドから、その週の日案を下書き一括作成する。"""
    require_can_edit(user, request)
    require_classroom_access(user, classroom_ref)
    if not target_week:
        raise HTTPException(status_code=400, detail="対象週を指定してください。")
    try:
        week_start = week_start_date_from_target_week(target_week)
    except ValueError:
        raise HTTPException(status_code=400, detail="対象週の形式が不正です。")

    weekly_rows = repository.session.exec(select(PlanDocumentRow).where(
        PlanDocumentRow.document_type == DocumentType.WEEKLY_PLAN.value,
        PlanDocumentRow.nursery_ref == user.nursery_ref,
        PlanDocumentRow.classroom_ref == classroom_ref,
        PlanDocumentRow.week_start_date == week_start.isoformat(),
    )).all()
    weekly_doc = None
    for candidate in weekly_rows:
        if candidate.status != DocumentStatus.ARCHIVED.value and candidate.schedule:
            weekly_doc = candidate
            break
    if weekly_doc is None:
        raise HTTPException(status_code=404, detail="週案が見つかりません。")

    offset_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    weekly_parent_id = str(int(weekly_doc.id or 0))
    weekly_source_ref = f"weekly.document:{weekly_doc.id}"
    age_class = weekly_doc.age_class or ""
    created = 0
    skipped = 0
    failed = 0
    for row in weekly_doc.schedule.get("rows", []):
        row_key = row.get("row_key", "")
        offset = offset_map.get(row_key)
        if offset is None:
            continue
        target_d = week_start + timedelta(days=offset)
        existing = repository.session.exec(select(PlanDocumentRow).where(
            PlanDocumentRow.document_type == DocumentType.DAILY_PLAN.value,
            PlanDocumentRow.nursery_ref == user.nursery_ref,
            PlanDocumentRow.classroom_ref == classroom_ref,
            PlanDocumentRow.target_date == target_d.isoformat(),
        )).first()
        if existing is not None:
            skipped += 1
            continue
        cells = row.get("cells", {})
        activity_cell = cells.get("activity")
        support_cell = cells.get("support")
        activity = activity_cell.get("body", "") if isinstance(activity_cell, dict) else ""
        support = support_cell.get("body", "") if isinstance(support_cell, dict) else ""
        timeline_rows = [{
            "row_key": f"row_{row_key}",
            "time_label": "",
            "activity_name": activity,
            "child_state": "",
            "support": support,
            "considerations": "",
        }]
        try:
            document = generate_simple_daily_plan({
                "target_date": target_d.isoformat(),
                "classroom_ref": classroom_ref,
                "age_class": age_class,
                "owner_name": user.name,
                "timeline_rows": timeline_rows,
                "parent_document_id": weekly_parent_id,
                "weekly_source_ref": weekly_source_ref,
                "class_name": weekly_doc.classroom_ref,
            }, user)
            repository.create(document)
            created += 1
        except Exception:
            repository.session.rollback()
            failed += 1
    query = urlencode({"created": created, "skipped": skipped, "failed": failed})
    return RedirectResponse(url=f"/plans/daily-plans/?{query}", status_code=303)
