"""シフト求解入力変換サービス。

既存の ShiftPlanCells （指定セル・ピン留めセル）を shiftai.solver が受け付ける
fixed_assignments 辞書 ((staff_id, target_date, slot_label) -> CellState) に正規化・変換する。
園定義勤務パターン（ShiftDutyPatterns）の動的解決に対応。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from shiftai.domain import CellState

if TYPE_CHECKING:
    from ..db_models import ShiftDutyPatterns, ShiftFacilitySettings, ShiftPlanCells


def normalize_staff_id(raw_id: str | int | UUID) -> str:
    """職員IDを文字列に正規化する。UUIDはhex形式で統一。"""
    sid_str = str(raw_id)
    try:
        return UUID(sid_str).hex
    except (ValueError, AttributeError):
        return sid_str


def resolve_slot_to_time_window(
    slot_label: str,
    settings: ShiftFacilitySettings | None = None,
    duty_patterns: Sequence[ShiftDutyPatterns] | None = None,
) -> list[str]:
    """スロットラベル（区分名・記号または "HH:MM-HH:MM"）を時間帯ラベルのリストに解決する。

    1. すでに "HH:MM-HH:MM" 形式ならそのまま返す。
    2. 園定義勤務パターン（ShiftDutyPatterns）の名前や記号に一致する場合はその開始〜終了に展開。
    3. 後方互換性として "EARLY" / "NORMAL" / "LATE" も解決。
    """
    cleaned = (slot_label or "").strip()
    if not cleaned:
        return []
    if "-" in cleaned and ":" in cleaned:
        return [cleaned]

    upper = cleaned.upper()
    if upper in ("OFF", "休", "公休", "休暇"):
        return []

    # 1. 園定義勤務パターンとの照合
    if duty_patterns:
        for dp in duty_patterns:
            if cleaned == dp.name or cleaned == dp.symbol or upper == dp.name.upper():
                return [f"{dp.start_time}-{dp.end_time}"]

    # 2. 既定区分名マッピング（後方互換）
    if upper == "EARLY":
        open_time = getattr(settings, "day_open", "07:30") if settings else "07:30"
        return [f"{open_time}-16:30"]
    if upper == "NORMAL":
        return ["08:30-17:30"]
    if upper == "LATE":
        close_time = getattr(settings, "day_close", "19:30") if settings else "19:30"
        return [f"10:30-{close_time}"]

    return [cleaned]


def parse_cell_state_value(state_val: str | None) -> CellState:
    """cell_state（'pinned', 'WORK', 'BREAK', 'OFF' など）を CellState 列挙型にマッピングする。"""
    if not state_val:
        return CellState.WORK
    val_upper = state_val.strip().upper()
    if val_upper in ("PINNED", "SPECIFIED", "WORK", "勤務"):
        return CellState.WORK
    if val_upper in ("BREAK", "休憩"):
        return CellState.BREAK
    if val_upper in ("OFF", "公休", "オフ", "休"):
        return CellState.OFF
    return CellState.WORK


def build_fixed_assignments(
    cells: Iterable[ShiftPlanCells],
    settings: ShiftFacilitySettings | None = None,
    duty_patterns: Sequence[ShiftDutyPatterns] | None = None,
) -> dict[tuple[str, date, str], CellState]:
    """ShiftPlanCells リストからソルバー用の fixed_assignments マッピングを構築する。

    is_pinned=True または cell_state='pinned' のセルを固定対象とし、
    キーは (staff_id, target_date, "HH:MM-HH:MM")、値は CellState (WORK/BREAK/OFF) とする。
    """
    fixed: dict[tuple[str, date, str], CellState] = {}
    for cell in cells:
        is_pinned = getattr(cell, "is_pinned", False) or (getattr(cell, "cell_state", "") == "pinned")
        if not is_pinned:
            continue

        sid = normalize_staff_id(cell.staff_user_id)
        d = cell.target_date
        state = parse_cell_state_value(getattr(cell, "cell_state", "WORK"))

        slot_labels = resolve_slot_to_time_window(cell.slot_label, settings, duty_patterns=duty_patterns)
        for sl in slot_labels:
            fixed[(sid, d, sl)] = state

    return fixed
