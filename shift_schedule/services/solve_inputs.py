"""シフト求解入力変換サービス。

既存の ShiftPlanCells （指定セル・ピン留めセル）を shiftai.solver が受け付ける
fixed_assignments 辞書 ((staff_id, target_date, slot_label) -> CellState) に正規化・変換する。
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from typing import TYPE_CHECKING
from uuid import UUID

from shiftai.domain import CellState

if TYPE_CHECKING:
    from ..db_models import ShiftFacilitySettings, ShiftPlanCells


def normalize_staff_id(raw_id: str | int | UUID) -> str:
    """職員IDを文字列に正規化する。UUIDはhex形式で統一。"""
    sid_str = str(raw_id)
    try:
        return UUID(sid_str).hex
    except (ValueError, AttributeError):
        return sid_str


def resolve_slot_to_time_window(slot_label: str, settings: ShiftFacilitySettings | None = None) -> list[str]:
    """スロットラベル（区分名または "HH:MM-HH:MM"）を時間帯ラベルのリストに解決する。

    すでに "HH:MM-HH:MM" 形式ならそのまま返す。
    "EARLY" / "NORMAL" / "LATE" などの区分名の場合は施設設定の開閉所時間および一般的な標準時間帯に展開する。
    """
    cleaned = (slot_label or "").strip()
    if not cleaned:
        return []
    if "-" in cleaned and ":" in cleaned:
        return [cleaned]

    upper = cleaned.upper()
    # 区分名マッピング（U2推奨案: 区分名も許可しソルバー直前で展開）
    # 粒度30分換算の標準的な区分時間帯（例）
    if upper == "EARLY":
        # 施設開所 07:00〜09:00 想定
        open_time = getattr(settings, "day_open", "07:00") if settings else "07:00"
        return [f"{open_time}-09:00"]
    if upper == "NORMAL":
        return ["09:00-17:00"]
    if upper == "LATE":
        close_time = getattr(settings, "day_close", "19:00") if settings else "19:00"
        return [f"17:00-{close_time}"]
    if upper == "OFF":
        # 公休の場合は特定スロットではなく全スロットOFFとして扱えるが、ラベルとしては空
        return []

    return [cleaned]


def parse_cell_state_value(state_val: str | None) -> CellState:
    """cell_state（'pinned', 'WORK', 'BREAK', 'OFF' など）を CellState 列挙型にマッピングする。

    U1推奨案: 既存の 'pinned' または 'specified' は WORK（勤務）とみなす。
    """
    if not state_val:
        return CellState.WORK
    val_upper = state_val.strip().upper()
    if val_upper in ("PINNED", "SPECIFIED", "WORK", "勤務"):
        return CellState.WORK
    if val_upper in ("BREAK", "休憩"):
        return CellState.BREAK
    if val_upper in ("OFF", "公休", "オフ"):
        return CellState.OFF
    return CellState.WORK


def build_fixed_assignments(
    cells: Iterable[ShiftPlanCells],
    settings: ShiftFacilitySettings | None = None,
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

        slot_labels = resolve_slot_to_time_window(cell.slot_label, settings)
        for sl in slot_labels:
            fixed[(sid, d, sl)] = state

    return fixed
