"""Client for NuShift Serverless Solver API.

Web基幹サーバーから独立したサーバーレスコンテナ（Cloud Run / Lambda / 独立コンテナ）へ
非同期HTTP POSTで求解ジョブを委譲し、障害時または未設定時はローカル内蔵ソルバーへ
自動フォールバックする耐障害性クライアント。
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import requests

from serverless_solver.schema import (
    ChildPlanSchema,
    FacilityConfigSchema,
    ShiftSlotSchema,
    ShiftSolveRequest,
    ShiftSolveResponse,
    StaffItemSchema,
)

logger = logging.getLogger("shift_schedule.serverless_client")

# サーバーレスソルバーのURL（未設定時はローカルフォールバック）
SERVERLESS_SOLVER_URL = os.getenv("HOIKUICT_SERVERLESS_SOLVER_URL", "").strip().rstrip("/")
SERVERLESS_SOLVER_TIMEOUT = int(os.getenv("HOIKUICT_SERVERLESS_SOLVER_TIMEOUT", "45"))


def get_serverless_solver_url() -> str:
    """サーバーレスソルバーのURLを動的に取得する。"""
    return os.getenv("HOIKUICT_SERVERLESS_SOLVER_URL", SERVERLESS_SOLVER_URL).strip().rstrip("/")


def _auth_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    token = (os.getenv("HOIKUICT_SERVERLESS_SOLVER_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def is_serverless_configured() -> bool:
    """サーバーレスソルバーが設定されているかを返す。"""
    try:
        from profile_config import should_use_serverless_solver

        if not should_use_serverless_solver():
            return False
    except ImportError:
        pass
    return bool(get_serverless_solver_url())


def check_serverless_health() -> bool:
    """サーバーレスエンドポイントのヘルスチェックを実施する。"""
    if not is_serverless_configured():
        return False
    url_base = get_serverless_solver_url()
    try:
        url = f"{url_base}/health"
        res = requests.get(url, timeout=5)
        return res.status_code == 200
    except Exception as exc:
        logger.warning("サーバーレスヘルスチェック失敗: %s (URL: %s)", exc, url_base)
        return False


def call_serverless_solve(request: ShiftSolveRequest) -> Optional[ShiftSolveResponse]:
    """サーバーレスAPIへ求解を委譲する。通信失敗時はNoneを返す（上位でフォールバック可能にする）。"""
    if not is_serverless_configured():
        logger.info("サーバーレスURL未設定のため、ローカル内蔵ソルバーへフォールバックします。")
        return None

    endpoint = f"{get_serverless_solver_url()}/api/v1/solve"
    logger.info(
        "サーバーレス求解要求送信: URL=%s, facility=%s, month=%s",
        endpoint,
        request.facility_id,
        request.target_month,
    )

    try:
        resp = requests.post(
            endpoint,
            json=request.model_dump(),
            timeout=SERVERLESS_SOLVER_TIMEOUT,
            headers=_auth_headers(),
        )
        if resp.status_code == 200:
            data = resp.json()
            return ShiftSolveResponse.model_validate(data)
        logger.error(
            "サーバーレスAPIエラー: status=%d, body=%s",
            resp.status_code,
            resp.text[:300],
        )
        return None
    except requests.Timeout:
        logger.error("サーバーレスAPIタイムアウト (%d秒超過)", SERVERLESS_SOLVER_TIMEOUT)
        return None
    except Exception as exc:
        logger.error("サーバーレスAPI接続例外: %s", exc)
        return None


def execute_via_serverless_if_available(
    context: Any,
    facility_id: Any,
    staffing_standard_key: str,
    time_limit_sec: int,
) -> Any | None:
    """サーバーレスが利用可能な場合、contextを変換して外部求解を実行し、SolveResult互換オブジェクトを返す。
    利用不可または失敗時は None を返し、呼び出し元でローカルフォールバックを促す。
    """
    if not is_serverless_configured():
        return None

    try:
        from shiftai.domain import CellState, ShiftDay
        from shiftai.monthly import SolveResult, SolveStatus

        # 1. 職員リストの変換
        staff_list: list[StaffItemSchema] = []
        for s in context.staff:
            sid = str(s.staff_id)
            c = context.contracts.get(sid)
            p = context.preferences.get(sid)
            unavail_dates = [u.day.isoformat() for u in getattr(p, "unavailable", ())] if p else []

            staff_list.append(
                StaffItemSchema(
                    staff_id=sid,
                    name=s.name,
                    employment_type=getattr(getattr(c, "employment_type", None), "name", "FULL_TIME"),
                    is_qualified=any("保育士" in str(r) for r in s.roles),
                    weekly_contract_hours=float(getattr(c, "weekly_hours", 40.0) if c else 40.0),
                    max_consecutive_days=int(getattr(c, "max_consecutive_days", 5) if c else 5),
                    unavailable_dates=unavail_dates,
                )
            )

        # 1b. 園児登降園計画の変換
        children_list: list[ChildPlanSchema] = []
        raw_children = getattr(context, "children", ()) or ()
        if not isinstance(raw_children, (list, tuple)):
            raw_children = ()
        for ch in raw_children:
            age_cls = getattr(getattr(ch, "age_class", None), "value", "1歳児")
            arrive_t = getattr(ch, "arrive", None)
            depart_t = getattr(ch, "depart", None)
            children_list.append(
                ChildPlanSchema(
                    child_id=str(ch.child_id),
                    name=str(getattr(ch, "name", ch.child_id)),
                    day=ch.day.isoformat() if hasattr(ch.day, "isoformat") else str(ch.day),
                    age_class=str(age_cls),
                    arrive=arrive_t.strftime("%H:%M") if hasattr(arrive_t, "strftime") else "08:30",
                    depart=depart_t.strftime("%H:%M") if hasattr(depart_t, "strftime") else "16:30",
                    is_short_time=bool(getattr(ch, "is_short_time", False)),
                    absent=bool(getattr(ch, "absent", False)),
                    uses_early_care=bool(getattr(ch, "uses_early_care", False)),
                    uses_late_care=bool(getattr(ch, "uses_late_care", False)),
                )
            )

        # 2. ピン留めセルの変換
        pinned_map: dict[str, dict[str, ShiftSlotSchema]] = {}
        for (sid, p_date, sl_label), c_state in context.fixed_assignments.items():
            sid_str = str(sid)
            d_str = p_date.isoformat() if hasattr(p_date, "isoformat") else str(p_date)
            code_val = "休" if c_state == CellState.OFF else sl_label
            pinned_map.setdefault(sid_str, {})[d_str] = ShiftSlotSchema(
                code=code_val,
                is_pinned=True,
            )

        # 3. リクエストオブジェクト構築
        req = ShiftSolveRequest(
            facility_id=facility_id,
            target_month=context.target_month,
            staffing_standard_key=staffing_standard_key,
            facility_config=FacilityConfigSchema(
                opening_time=context.facility_settings.day_open.strftime("%H:%M"),
                closing_time=context.facility_settings.day_close.strftime("%H:%M"),
                granularity_min=context.facility_settings.granularity_min,
                closed_days=[d.isoformat() for d in context.facility_settings.closed_days],
                holiday_dates=[d.isoformat() for d in context.facility_settings.holiday_dates],
            ),
            children=children_list,
            staff_list=staff_list,
            pinned_assignments=pinned_map,
            prior_duty_streaks=context.prior_duty_history or {},
            options=dict(time_limit_sec=time_limit_sec),
        )

        resp = call_serverless_solve(req)
        if resp is None:
            return None

        # 4. ShiftSolveResponse を SolveResult に復元
        state_by_value = {c.value: c for c in CellState}
        shift_days: list[ShiftDay] = []
        for d in context.all_days:
            d_str = d.isoformat()
            day_assignments: dict[str, dict[str, CellState]] = {}
            for sid_str, date_dict in resp.schedule_matrix.items():
                slot_info = date_dict.get(d_str)
                if slot_info and slot_info.slots:
                    day_assignments[sid_str] = {
                        sl_k: state_by_value.get(sl_v, CellState.WORK)
                        for sl_k, sl_v in slot_info.slots.items()
                    }
                elif slot_info and slot_info.code not in ("休", "公休", "OFF"):
                    day_assignments[sid_str] = {"all": CellState.WORK}
                else:
                    day_assignments[sid_str] = {"all": CellState.OFF}
            shift_days.append(ShiftDay(day=d, assignments=day_assignments))

        status_enum = (
            SolveStatus.OPTIMAL
            if resp.status in ("OPTIMAL", "SUCCESS")
            else SolveStatus.FEASIBLE
        )

        return SolveResult(
            status=status_enum,
            shift_days=shift_days,
            assignments={},
            objective_value=float(resp.score.soft),
            violations=[],
            messages=[f"Solved via Serverless Solver API in {resp.elapsed_sec:.2f}s"],
            stats={"elapsed_sec": resp.elapsed_sec, "serverless": True},
            score=None,
            overconstrained_shortfalls=[],
        )

    except Exception as exc:
        logger.exception("サーバーレス連携中に例外発生。ローカルフォールバックします: %s", exc)
        return None
