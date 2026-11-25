"""Nap check service for SIDS prevention and Kodmon-compatible timeline management.

コドモン互換の5分/10分刻み時系列タイムライン、差分ワンタップ一括入力、
体位サイクル判定、環境（室温・湿度・天気）記録、SIDSアラート判定を提供します。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional
from sqlmodel import Session, select

from models import (
    Child,
    ChildStatus,
    Classroom,
    NapCheckRecord,
    NapClassroomEnvironment,
    AttendanceRecord,
)
from time_utils import utc_now

# 体位定義マスター
POSTURE_DEFINITIONS = {
    "back": {"key": "back", "label": "仰向け", "symbol": "↑", "badge_class": "bg-sky-100 text-sky-800 border-sky-300 font-bold", "color": "#0284c7"},
    "right": {"key": "right", "label": "右向き", "symbol": "→", "badge_class": "bg-emerald-100 text-emerald-800 border-emerald-300", "color": "#059669"},
    "left": {"key": "left", "label": "左向き", "symbol": "←", "badge_class": "bg-amber-100 text-amber-800 border-amber-300", "color": "#d97706"},
    "prone": {"key": "prone", "label": "うつ伏せ", "symbol": "↓", "badge_class": "bg-rose-100 text-rose-800 border-rose-300 font-extrabold ring-2 ring-rose-400 animate-pulse", "color": "#e11d48"},
    "awake": {"key": "awake", "label": "起床", "symbol": "起", "badge_class": "bg-violet-100 text-violet-800 border-violet-300", "color": "#7c3aed"},
}

POSTURE_CYCLE = ["", "back", "right", "left", "prone", "awake"]

HOURS_LIST = ["11:00", "12:00", "13:00", "14:00", "15:00"]


def get_next_posture(current: str) -> str:
    """現在の体位の次の体位キーを返す（ワンタップサイクル用）。"""
    curr = current or ""
    try:
        idx = POSTURE_CYCLE.index(curr)
        next_idx = (idx + 1) % len(POSTURE_CYCLE)
        return POSTURE_CYCLE[next_idx]
    except ValueError:
        return "back"


def generate_time_slots(hour_str: str = "13:00", interval: int = 5) -> list[str]:
    """1時間枠の中の分スロット一覧を返す（例: ['13:00', '13:05', ..., '13:55']）。"""
    try:
        hour = int(hour_str.split(":")[0])
    except Exception:
        hour = 13
    interval = 10 if interval == 10 else 5
    slots = []
    for minute in range(0, 60, interval):
        slots.append(f"{hour:02d}:{minute:02d}")
    return slots


def get_current_nearest_slot(local_dt: datetime, interval: int = 5) -> str:
    """現在時刻から直近の午睡スロットキー（HH:MM）を算出する。"""
    interval = 10 if interval == 10 else 5
    minute = (local_dt.minute // interval) * interval
    hour = local_dt.hour
    if hour < 11:
        return "11:00"
    if hour > 15:
        return "15:55"
    return f"{hour:02d}:{minute:02d}"


def get_or_create_nap_record(
    session: Session, child_id: int, target_date: date, created_by: str = ""
) -> NapCheckRecord:
    """指定園児・日付の NapCheckRecord を取得または新規初期化する。"""
    rec = session.exec(
        select(NapCheckRecord).where(
            NapCheckRecord.child_id == child_id,
            NapCheckRecord.target_date == target_date,
        )
    ).first()
    if rec is None:
        rec = NapCheckRecord(
            child_id=child_id,
            target_date=target_date,
            slots={},
            daily_memo="",
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(rec)
        session.flush()
    return rec


def get_or_create_classroom_environment(
    session: Session, classroom_id: int, target_date: date, created_by: str = ""
) -> NapClassroomEnvironment:
    """指定クラス・日付の環境記録を取得または新規初期化する。"""
    env = session.exec(
        select(NapClassroomEnvironment).where(
            NapClassroomEnvironment.classroom_id == classroom_id,
            NapClassroomEnvironment.target_date == target_date,
        )
    ).first()
    if env is None:
        env = NapClassroomEnvironment(
            classroom_id=classroom_id,
            target_date=target_date,
            weather="sunny",
            room_temperature=22.0,
            humidity=50.0,
            created_by=created_by,
            updated_by=created_by,
        )
        session.add(env)
        session.flush()
    return env


def update_child_nap_slot(
    session: Session,
    child_id: int,
    target_date: date,
    time_key: str,
    posture: str,
    breathing: str = "normal",
    temperature: Optional[float] = None,
    staff_name: str = "",
) -> NapCheckRecord:
    """指定園児の特定時刻スロットの体位・呼吸・体温を更新する。"""
    rec = get_or_create_nap_record(session, child_id, target_date, created_by=staff_name)
    slots = dict(rec.slots or {})
    if not posture:
        slots.pop(time_key, None)
    else:
        slot_data: dict[str, Any] = {
            "posture": posture,
            "breathing": breathing or "normal",
            "checked_by": staff_name,
            "updated_at": utc_now().isoformat(),
        }
        if temperature is not None:
            slot_data["temperature"] = temperature
        slots[time_key] = slot_data
    rec.slots = slots
    rec.updated_at = utc_now()
    rec.updated_by = staff_name
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def bulk_set_slot_for_children(
    session: Session,
    child_ids: list[int],
    target_date: date,
    time_key: str,
    posture: str = "back",
    breathing: str = "normal",
    staff_name: str = "",
) -> int:
    """複数園児の特定スロットを一括セット（差分ベースのベース登録）する。"""
    updated_count = 0
    now = utc_now()
    for cid in child_ids:
        rec = get_or_create_nap_record(session, cid, target_date, created_by=staff_name)
        slots = dict(rec.slots or {})
        slots[time_key] = {
            "posture": posture,
            "breathing": breathing,
            "checked_by": staff_name,
            "updated_at": now.isoformat(),
        }
        rec.slots = slots
        rec.updated_at = now
        rec.updated_by = staff_name
        session.add(rec)
        updated_count += 1
    session.commit()
    return updated_count


def update_child_nap_memo(
    session: Session,
    child_id: int,
    target_date: date,
    memo: str,
    staff_name: str = "",
) -> NapCheckRecord:
    """園児の「この日の体調・午睡のメモ」を更新する。"""
    rec = get_or_create_nap_record(session, child_id, target_date, created_by=staff_name)
    rec.daily_memo = memo.strip() if memo else None
    rec.updated_at = utc_now()
    rec.updated_by = staff_name
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def update_classroom_environment(
    session: Session,
    classroom_id: int,
    target_date: date,
    weather: Optional[str] = None,
    room_temperature: Optional[float] = None,
    humidity: Optional[float] = None,
    notes: Optional[str] = None,
    staff_name: str = "",
) -> NapClassroomEnvironment:
    """クラスの環境記録（室温・湿度・天気）を更新する。"""
    env = get_or_create_classroom_environment(
        session, classroom_id, target_date, created_by=staff_name
    )
    if weather is not None:
        env.weather = weather
    if room_temperature is not None:
        env.room_temperature = room_temperature
    if humidity is not None:
        env.humidity = humidity
    if notes is not None:
        env.notes = notes
    env.updated_at = utc_now()
    env.updated_by = staff_name
    session.add(env)
    session.commit()
    session.refresh(env)
    return env


def load_nap_check_sheet_data(
    session: Session,
    target_date: date,
    classroom_id: Optional[int] = None,
    only_present: bool = True,
    search_query: str = "",
    selected_hour: str = "13:00",
    interval: int = 5,
) -> dict[str, Any]:
    """コドモン互換タイムライン表示に必要なデータ構造を構築する。"""
    # 園児一覧の取得
    query = select(Child).where(Child.status == ChildStatus.enrolled)
    if classroom_id:
        query = query.where(Child.classroom_id == classroom_id)
    if search_query:
        query = query.where(
            (Child.first_name.contains(search_query))
            | (Child.last_name.contains(search_query))
            | (Child.first_name_kana.contains(search_query))
            | (Child.last_name_kana.contains(search_query))
        )
    children = session.exec(query.order_by(Child.classroom_id, Child.id)).all()

    # 登園状況の突合（打刻チェックイン済＆未降園）
    child_ids = [c.id for c in children if c.id is not None]
    attendances = session.exec(
        select(AttendanceRecord).where(
            AttendanceRecord.attendance_date == target_date,
            AttendanceRecord.child_id.in_(child_ids) if child_ids else False,
        )
    ).all()
    attendance_map = {
        att.child_id: (att.check_in_at is not None and att.check_out_at is None)
        for att in attendances
    }

    # 登園中のみ表示フィルタ
    filtered_children = []
    for c in children:
        is_present = bool(attendance_map.get(c.id, False))
        if only_present and not is_present:
            continue
        filtered_children.append((c, is_present, "登園中" if is_present else "未登園"))

    # 午睡レコードの取得
    target_cids = [c[0].id for c in filtered_children if c[0].id is not None]
    records = session.exec(
        select(NapCheckRecord).where(
            NapCheckRecord.target_date == target_date,
            NapCheckRecord.child_id.in_(target_cids) if target_cids else False,
        )
    ).all()
    records_by_child_id = {r.child_id: r for r in records}

    # 時間スロット一覧
    slots = generate_time_slots(selected_hour, interval)

    # 各園児の行データを構築
    rows = []
    prone_count = 0
    total_recorded_slots = 0

    for child, is_present, att_status in filtered_children:
        rec = records_by_child_id.get(child.id)
        slot_data = rec.slots if rec and rec.slots else {}
        memo = rec.daily_memo if rec else ""

        # スロットごとの表示情報をマッピング
        row_slots = []
        for s in slots:
            data = slot_data.get(s)
            posture_key = data.get("posture") if data else ""
            posture_info = POSTURE_DEFINITIONS.get(posture_key, {})
            if posture_key == "prone":
                prone_count += 1
            if posture_key:
                total_recorded_slots += 1
            row_slots.append({
                "time": s,
                "posture": posture_key,
                "label": posture_info.get("label", ""),
                "symbol": posture_info.get("symbol", ""),
                "badge_class": posture_info.get("badge_class", "bg-slate-50 text-slate-400 border-slate-200 hover:bg-slate-100"),
                "checked_by": data.get("checked_by", "") if data else "",
                "data": data,
            })

        rows.append({
            "child": child,
            "is_present": is_present,
            "attendance_status": att_status,
            "record": rec,
            "slots": row_slots,
            "memo": memo,
        })

    # クラス環境記録
    classroom_env = None
    if classroom_id:
        classroom_env = session.exec(
            select(NapClassroomEnvironment).where(
                NapClassroomEnvironment.classroom_id == classroom_id,
                NapClassroomEnvironment.target_date == target_date,
            )
        ).first()

    classrooms = session.exec(select(Classroom).order_by(Classroom.id)).all()

    return {
        "target_date": target_date,
        "classroom_id": classroom_id,
        "classrooms": classrooms,
        "selected_hour": selected_hour,
        "hours_list": HOURS_LIST,
        "slots": slots,
        "interval": interval,
        "rows": rows,
        "total_children_count": len(filtered_children),
        "prone_count": prone_count,
        "classroom_env": classroom_env,
        "only_present": only_present,
        "search_query": search_query,
        "posture_definitions": POSTURE_DEFINITIONS,
    }
