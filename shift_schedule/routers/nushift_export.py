"""NuShift CSV エクスポートルーター。

GET /shifts/nushift-export?month=YYYY-MM&kind=children|staff|preferences|zip
"""

from __future__ import annotations

import io
import zipfile
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlmodel import Session

from auth import StaffUser, get_current_staff_user, require_admin
from database import get_session
from ..services.nushift_export import children_csv_string, preferences_csv_string, staff_csv_string

router = APIRouter(prefix="/shifts", tags=["nushift_export"])


def _parse_month_range(month_str: str) -> tuple[date, date]:
    try:
        parts = month_str.split("-")
        year = int(parts[0])
        month = int(parts[1])
        start_date = date(year, month, 1)
        # 翌月1日の前日
        if month == 12:
            end_date = date(year + 1, 1, 1)
        else:
            end_date = date(year, month + 1, 1)
        from datetime import timedelta
        end_date = end_date - timedelta(days=1)
        return start_date, end_date
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"無効な年月指定です: {month_str} (形式: YYYY-MM)") from e


@router.get("/nushift-export")
def export_nushift_data(
    month: str = Query(..., pattern=r"^\d{4}-\d{2}$"),
    kind: Literal["children", "staff", "preferences", "zip"] = "zip",
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
) -> Response:
    require_admin(current_user)

    start_date, end_date = _parse_month_range(month)

    if kind == "children":
        content = children_csv_string(session, start_date, end_date)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="nushift_children_{month}.csv"'},
        )
    elif kind == "staff":
        content = staff_csv_string(session)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="nushift_staff_{month}.csv"'},
        )
    elif kind == "preferences":
        content = preferences_csv_string(session, start_date, end_date)
        return Response(
            content=content.encode("utf-8"),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="nushift_preferences_{month}.csv"'},
        )
    elif kind == "zip":
        c_csv = children_csv_string(session, start_date, end_date)
        s_csv = staff_csv_string(session)
        p_csv = preferences_csv_string(session, start_date, end_date)

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(f"children_{month}.csv", c_csv.encode("utf-8"))
            zf.writestr(f"staff_{month}.csv", s_csv.encode("utf-8"))
            zf.writestr(f"preferences_{month}.csv", p_csv.encode("utf-8"))

        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="nushift_export_{month}.zip"'},
        )
