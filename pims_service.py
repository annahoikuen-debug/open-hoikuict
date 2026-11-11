from __future__ import annotations

import codecs
import csv
import io
import logging
import re
from calendar import monthrange
from datetime import date, datetime, time
from typing import Optional, Tuple, List, Dict, Any

from sqlmodel import Session, select

from auth_mail import send_auth_mail
from models.pims import PunchChild, PunchLog
from time_utils import local_naive_now, local_today

logger = logging.getLogger(__name__)

VALID_ABSENCE_REASONS = {"病欠等", "都合", "災害"}


def normalize_name(name: str) -> str:
    """全角・半角スペースを完全除去した正規化文字列を返す。"""
    if not name:
        return ""
    return re.sub(r"[\s\u3000]+", "", name)


def parse_date_str(val: Any) -> Optional[date]:
    """YYYY/MM/DD や YYYY-MM-DD 等の日付文字列を date オブジェクトに変換。"""
    if not val or val == "nan":
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    # YYYY/MM/DD or YYYY-MM-DD
    s = s.replace("-", "/")
    parts = s.split("/")
    if len(parts) == 3:
        try:
            return date(int(parts[0]), int(parts[1]), int(parts[2]))
        except ValueError:
            return None
    return None


def parse_time_str(val: Any) -> Optional[str]:
    """HH:mm 形式の時刻文字列を正規化して返す。"""
    if not val or val == "nan":
        return None
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return None
    # 08:30:00 -> 08:30
    parts = s.split(":")
    if len(parts) >= 2:
        try:
            h = int(parts[0])
            m = int(parts[1])
            return f"{h:02d}:{m:02d}"
        except ValueError:
            return None
    return None


def sync_core_children_if_empty(session: Session) -> int:
    """既存の children テーブルに園児が存在し、punch_children が空の場合に自動同期する。"""
    count = session.exec(select(PunchChild)).first()
    if count is not None:
        return 0

    try:
        from models.core import Child, Classroom, ChildStatus
        core_children = session.exec(select(Child).where(Child.status == ChildStatus.enrolled)).all()
        synced = 0
        for cc in core_children:
            c_name = cc.classroom.name if cc.classroom else "未設定"
            p_child = PunchChild(
                child_id=str(cc.id),
                name=f"{cc.last_name} {cc.first_name}".strip(),
                kana=f"{cc.last_name_kana} {cc.first_name_kana}".strip(),
                birth_date=cc.birth_date,
                class_name=c_name,
                family_id=str(cc.family_id) if cc.family_id else None,
                parent_email=cc.guardians[0].email if cc.guardians and cc.guardians[0].email else None,
                sort_order=cc.id or 0,
                is_active=True,
            )
            session.add(p_child)
            synced += 1
        if synced > 0:
            session.commit()
        return synced
    except Exception as exc:
        logger.warning(f"Failed to auto-sync core children: {exc}")
        return 0


def get_all_active_children(session: Session) -> List[PunchChild]:
    """有効な園児一覧を表示順、クラス名、氏名でソートして返す。"""
    sync_core_children_if_empty(session)
    statement = (
        select(PunchChild)
        .where(PunchChild.is_active == True)  # noqa: E712
        .order_by(PunchChild.sort_order, PunchChild.class_name, PunchChild.name)
    )
    return session.exec(statement).all()


def find_siblings(session: Session, child: PunchChild) -> List[PunchChild]:
    """同一世帯ID (family_id) を持つ他の有効な園児を検索して返す。

    世帯IDが空欄、または単独世帯の場合は空リストを返す（苗字判定は行わない）。
    """
    if not child.family_id or not child.family_id.strip():
        return []

    statement = (
        select(PunchChild)
        .where(
            PunchChild.family_id == child.family_id.strip(),
            PunchChild.child_id != child.child_id,
            PunchChild.is_active == True,  # noqa: E712
        )
        .order_by(PunchChild.sort_order, PunchChild.name)
    )
    return session.exec(statement).all()


def get_daily_child_states(session: Session, target_date: Optional[date] = None) -> Dict[str, Dict[str, Any]]:
    """当日の打刻トランザクションログから全園児のリアルタイム出欠ステータスを動的に算出する。

    戻り値辞書構造:
    child_id: {
        "status": "登園中" | "降園済" | "欠席" | "未登園",
        "badge_class": CSSクラス名,
        "detail": 時刻や欠席理由文字列,
        "check_in_time": "HH:mm" | None,
        "check_out_time": "HH:mm" | None,
        "absence_reason": "病欠等" | "都合" | "災害" | None
    }
    """
    if target_date is None:
        target_date = local_today()

    start_dt = datetime.combine(target_date, time.min)
    end_dt = datetime.combine(target_date, time.max)

    logs = session.exec(
        select(PunchLog)
        .where(PunchLog.punched_at >= start_dt, PunchLog.punched_at <= end_dt)
        .order_by(PunchLog.punched_at.asc())
    ).all()

    # 園児IDごとにログを分類
    child_logs: Dict[str, List[PunchLog]] = {}
    for log in logs:
        child_logs.setdefault(log.child_id, []).append(log)

    children = get_all_active_children(session)
    states: Dict[str, Dict[str, Any]] = {}

    for c in children:
        logs_for_child = child_logs.get(c.child_id, [])
        check_in_log: Optional[PunchLog] = None
        check_out_log: Optional[PunchLog] = None
        absence_log: Optional[PunchLog] = None

        for l in logs_for_child:
            if l.punch_type == "登園":
                if not check_in_log or l.punched_at < check_in_log.punched_at:
                    check_in_log = l
            elif l.punch_type == "降園":
                if not check_out_log or l.punched_at > check_out_log.punched_at:
                    check_out_log = l
            elif l.punch_type == "欠席":
                absence_log = l

        if absence_log:
            reason = absence_log.absence_reason or "欠席"
            states[c.child_id] = {
                "status": "欠席",
                "badge_class": "badge-absence",
                "detail": reason,
                "check_in_time": None,
                "check_out_time": None,
                "absence_reason": reason,
            }
        elif check_in_log and not check_out_log:
            t_str = check_in_log.punched_at.strftime("%H:%M")
            states[c.child_id] = {
                "status": "登園中",
                "badge_class": "badge-checkin",
                "detail": t_str,
                "check_in_time": t_str,
                "check_out_time": None,
                "absence_reason": None,
            }
        elif check_in_log and check_out_log:
            t_str = check_out_log.punched_at.strftime("%H:%M")
            states[c.child_id] = {
                "status": "降園済",
                "badge_class": "badge-checkout",
                "detail": t_str,
                "check_in_time": check_in_log.punched_at.strftime("%H:%M"),
                "check_out_time": t_str,
                "absence_reason": None,
            }
        elif check_out_log and not check_in_log:
            # 降園のみ打刻されたケース
            t_str = check_out_log.punched_at.strftime("%H:%M")
            states[c.child_id] = {
                "status": "降園済",
                "badge_class": "badge-checkout",
                "detail": t_str,
                "check_in_time": None,
                "check_out_time": t_str,
                "absence_reason": None,
            }
        else:
            states[c.child_id] = {
                "status": "未登園",
                "badge_class": "badge-not-arrived",
                "detail": "-",
                "check_in_time": None,
                "check_out_time": None,
                "absence_reason": None,
            }

    return states


def record_punch(
    session: Session,
    child_ids: List[str],
    punch_type: str,
    absence_reason: Optional[str] = None,
    punched_at: Optional[datetime] = None,
    is_auto_filled: bool = False,
    send_email: bool = True,
) -> Tuple[List[PunchLog], List[str]]:
    """打刻を実行し、保護者へメール通知（兄弟同時打刻時は連名1通）を送信する。

    戻り値: (作成されたPunchLogリスト, メッセージリスト)
    """
    if not punched_at:
        punched_at = local_naive_now()

    if punch_type == "欠席" and absence_reason not in VALID_ABSENCE_REASONS:
        absence_reason = "病欠等"

    created_logs: List[PunchLog] = []
    punched_children: List[PunchChild] = []

    for cid in child_ids:
        child = session.get(PunchChild, cid)
        if not child:
            continue
        log = PunchLog(
            child_id=cid,
            punched_at=punched_at,
            punch_type=punch_type,
            absence_reason=absence_reason if punch_type == "欠席" else None,
            is_auto_filled=is_auto_filled,
        )
        session.add(log)
        created_logs.append(log)
        punched_children.append(child)

    session.commit()

    # メール通知
    if send_email and punched_children:
        send_punch_notification_email(punched_children, punch_type, punched_at, absence_reason)

    names = "・".join([c.name for c in punched_children])
    msg = f"{names} さんの【{punch_type}】を記録しました。"
    return created_logs, [msg]


def undo_punch(
    session: Session,
    log_ids: List[str],
) -> Tuple[bool, str, Dict[str, Any]]:
    """直前の打刻ログを物理削除し、取り消しを実行する (Undo機能)。

    戻り値: (成功フラグ, メッセージ, 最新の園児ステータス辞書)
    """
    if not log_ids:
        return False, "取り消す打刻データがありません。", {}

    deleted_names = []
    for lid in log_ids:
        log = session.get(PunchLog, lid)
        if log:
            child = session.get(PunchChild, log.child_id)
            if child and child.name not in deleted_names:
                deleted_names.append(child.name)
            session.delete(log)

    session.commit()

    # 最新ステータスを再計算
    updated_states = get_daily_child_states(session)
    name_str = "・".join(deleted_names) if deleted_names else "園児"
    msg = f"{name_str} さんの直前の打刻を取り消しました。"
    return True, msg, updated_states


def send_punch_notification_email(
    children: List[PunchChild],
    punch_type: str,
    punched_at: datetime,
    absence_reason: Optional[str] = None,
) -> None:
    """打刻完了時に保護者メールへ通知を送信。兄弟の場合は連名で1通にまとめる。"""
    # メールアドレスごとに子供をグループ化
    email_groups: Dict[str, List[PunchChild]] = {}
    for c in children:
        if c.parent_email and c.parent_email.strip():
            email_groups.setdefault(c.parent_email.strip(), []).append(c)

    time_str = punched_at.strftime("%H:%M")
    date_str = punched_at.strftime("%Y年%m月%d日")

    for email_addr, group in email_groups.items():
        child_names = "、".join([f"{c.name} 様" for c in group])
        subject = f"【登降園システム】{punch_type}の打刻完了のお知らせ"

        lines = [
            "保護者 様",
            "",
            "保育ICTシステムより、打刻完了のお知らせです。",
            f"日時: {date_str} {time_str}",
            f"区分: {punch_type}",
        ]
        if punch_type == "欠席" and absence_reason:
            lines.append(f"欠席理由: {absence_reason}")

        lines.extend([
            f"対象児童: {child_names}",
            "",
            "※本メールにお心当たりがない場合は、園までご連絡ください。",
        ])
        body = "\n".join(lines)

        try:
            send_auth_mail(recipient=email_addr, subject=subject, body=body)
        except Exception as exc:
            logger.warning(f"保護者メール送信エラー ({email_addr}): {exc}")


def import_codmon_csv(session: Session, file_content: bytes) -> Dict[str, Any]:
    """コドモンの「公金管理システム連携.csv」を取り込み、マスタ補完と実績登録を行う。

    ヘッダー構成（固定9列）:
    名前, 名前(かな), 生年月日, ベンダCD, 予備, 日付, 欠席理由, 登園時刻, 退園時刻
    """
    # エンコーディング判定 (UTF-8 with BOM / UTF-8 / Shift_JIS / CP932)
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            text = file_content.decode(enc)
            break
        except UnicodeDecodeError:
            continue

    if text is None:
        raise ValueError("ファイルの文字コードを判別できませんでした (UTF-8またはShift_JISに対応しています)。")

    # CSVパース
    reader = csv.reader(io.StringIO(text))
    header = None
    rows = []
    for line in reader:
        if not line or all(cell.strip() == "" for cell in line):
            continue
        if header is None:
            header = [col.strip().replace("\ufeff", "") for col in line]
            continue
        rows.append([cell.strip() for cell in line])

    if not header:
        raise ValueError("CSVファイルが空です。")

    expected_cols = ["名前", "名前(かな)", "生年月日", "ベンダCD", "予備", "日付", "欠席理由", "登園時刻", "退園時刻"]
    # ヘッダーに主要カラムが含まれているか確認
    if not all(col in header for col in ["名前", "日付"]):
        raise ValueError(
            f"公金管理システム連携.csvのヘッダー仕様と一致しません。必要カラム: {expected_cols}"
        )

    col_idx = {col: i for i, col in enumerate(header)}

    # 既存の全園児をロード
    all_children = session.exec(select(PunchChild)).all()
    # スペース除去した正規化氏名 -> PunchChild のマッピング
    child_by_norm_name: Dict[str, PunchChild] = {
        normalize_name(c.name): c for c in all_children if c.name
    }

    new_children_count = 0
    updated_children_count = 0
    punch_logs_count = 0

    # 重複防止のため、既存ログを (child_id, target_date, punch_type) でキャッシュ
    existing_logs = session.exec(select(PunchLog)).all()
    log_cache = set()
    for el in existing_logs:
        log_cache.add((el.child_id, el.punched_at.date(), el.punch_type))

    auto_id_seq = len(all_children) + 1

    for row in rows:
        name_val = row[col_idx["名前"]] if "名前" in col_idx and col_idx["名前"] < len(row) else ""
        if not name_val:
            continue

        kana_val = row[col_idx["名前(かな)"]] if "名前(かな)" in col_idx and col_idx["名前(かな)"] < len(row) else ""
        birth_val = row[col_idx["生年月日"]] if "生年月日" in col_idx and col_idx["生年月日"] < len(row) else ""
        vender_val = row[col_idx["ベンダCD"]] if "ベンダCD" in col_idx and col_idx["ベンダCD"] < len(row) else ""
        date_val = row[col_idx["日付"]] if "日付" in col_idx and col_idx["日付"] < len(row) else ""
        absence_val = row[col_idx["欠席理由"]] if "欠席理由" in col_idx and col_idx["欠席理由"] < len(row) else ""
        check_in_val = row[col_idx["登園時刻"]] if "登園時刻" in col_idx and col_idx["登園時刻"] < len(row) else ""
        check_out_val = row[col_idx["退園時刻"]] if "退園時刻" in col_idx and col_idx["退園時刻"] < len(row) else ""

        norm_name = normalize_name(name_val)
        target_child = child_by_norm_name.get(norm_name)

        parsed_birth = parse_date_str(birth_val)
        target_date = parse_date_str(date_val)

        if target_child:
            # 既存園児マスタ補完: フリガナや生年月日が空欄の場合、CSVの値で自動補完
            changed = False
            if not target_child.kana and kana_val:
                target_child.kana = kana_val
                changed = True
            if not target_child.birth_date and parsed_birth:
                target_child.birth_date = parsed_birth
                changed = True
            if changed:
                session.add(target_child)
                updated_children_count += 1
        else:
            # 未登録児童: 新規マスタレコードとして作成
            cid = vender_val.strip() if vender_val and vender_val.strip() and vender_val.strip() != "nan" else f"C{auto_id_seq:04d}"
            # 既存IDと被らないように調整
            if session.get(PunchChild, cid):
                cid = f"C{auto_id_seq:04d}"
            auto_id_seq += 1

            target_child = PunchChild(
                child_id=cid,
                name=name_val,
                kana=kana_val if kana_val and kana_val != "nan" else None,
                birth_date=parsed_birth,
                class_name="未設定",
                family_id=None,
                parent_email=None,
                sort_order=auto_id_seq,
                is_active=True,
            )
            session.add(target_child)
            session.flush()  # ID確定
            child_by_norm_name[norm_name] = target_child
            new_children_count += 1

        if not target_date:
            continue

        # 実績ログ反映
        parsed_in = parse_time_str(check_in_val)
        parsed_out = parse_time_str(check_out_val)
        clean_absence = absence_val.strip() if absence_val and absence_val != "nan" else ""

        # 登園時刻
        if parsed_in:
            h, m = map(int, parsed_in.split(":"))
            dt = datetime.combine(target_date, time(h, m))
            key = (target_child.child_id, target_date, "登園")
            if key not in log_cache:
                log = PunchLog(
                    child_id=target_child.child_id,
                    punched_at=dt,
                    punch_type="登園",
                    absence_reason=None,
                    is_auto_filled=False,
                )
                session.add(log)
                log_cache.add(key)
                punch_logs_count += 1

        # 退園時刻（降園）
        if parsed_out:
            h, m = map(int, parsed_out.split(":"))
            dt = datetime.combine(target_date, time(h, m))
            key = (target_child.child_id, target_date, "降園")
            if key not in log_cache:
                log = PunchLog(
                    child_id=target_child.child_id,
                    punched_at=dt,
                    punch_type="降園",
                    absence_reason=None,
                    is_auto_filled=False,
                )
                session.add(log)
                log_cache.add(key)
                punch_logs_count += 1

        # 欠席理由（病欠等・都合・災害）
        if clean_absence and clean_absence in VALID_ABSENCE_REASONS:
            key = (target_child.child_id, target_date, "欠席")
            if key not in log_cache:
                dt = datetime.combine(target_date, time(9, 0))
                log = PunchLog(
                    child_id=target_child.child_id,
                    punched_at=dt,
                    punch_type="欠席",
                    absence_reason=clean_absence,
                    is_auto_filled=False,
                )
                session.add(log)
                log_cache.add(key)
                punch_logs_count += 1

    session.commit()
    return {
        "new_children": new_children_count,
        "updated_children": updated_children_count,
        "new_logs": punch_logs_count,
    }


def export_pims_csv(session: Session, year: int, month: int) -> Tuple[bytes, List[Dict[str, Any]]]:
    """ピムス公式9列CSVを生成し、降園抜けの自動補完（18:00）を行う。

    出力仕様:
    - ファイル形式: CSV (UTF-8 with BOM), CRLF
    - 固定9列:
      氏名, 氏名カナ, 生年月日, 未使用, 未使用, 日付, 欠席理由, 登園時刻, 降園時刻
    - 氏名・氏名カナ: スペース完全除去
    - 日付・生年月日: YYYY/MM/DD
    - 登園・降園時刻: HH:mm
    - 降園抜け検知: 登園時刻があるが降園時刻がない日は「18:00」を自動補完
    - 排他制御: 登降園時刻のいずれかがあれば、欠席理由は空欄
    - 契約外日: 実績のない日は欠席理由・登降園時刻ともに空欄

    戻り値: (csv_bytes, missing_checkouts_list)
    """
    _, last_day = monthrange(year, month)
    start_date = date(year, month, 1)
    end_date = date(year, month, last_day)

    children = get_all_active_children(session)

    # 対象月の全ログを一括ロード
    start_dt = datetime.combine(start_date, time.min)
    end_dt = datetime.combine(end_date, time.max)

    logs = session.exec(
        select(PunchLog)
        .where(PunchLog.punched_at >= start_dt, PunchLog.punched_at <= end_dt)
        .order_by(PunchLog.punched_at.asc())
    ).all()

    # child_id -> date -> logs
    child_daily_logs: Dict[str, Dict[date, List[PunchLog]]] = {}
    for log in logs:
        d = log.punched_at.date()
        child_daily_logs.setdefault(log.child_id, {}).setdefault(d, []).append(log)

    missing_checkouts: List[Dict[str, Any]] = []
    output_rows: List[List[str]] = []

    # ヘッダー行
    header = ["氏名", "氏名カナ", "生年月日", "未使用", "未使用", "日付", "欠席理由", "登園時刻", "降園時刻"]
    output_rows.append(header)

    for child in children:
        clean_name = normalize_name(child.name)
        clean_kana = normalize_name(child.kana or "")
        birth_str = child.birth_date.strftime("%Y/%m/%d") if child.birth_date else ""

        c_logs_map = child_daily_logs.get(child.child_id, {})

        for day_num in range(1, last_day + 1):
            cur_date = date(year, month, day_num)
            date_str = cur_date.strftime("%Y/%m/%d")

            d_logs = c_logs_map.get(cur_date, [])
            in_log: Optional[PunchLog] = None
            out_log: Optional[PunchLog] = None
            abs_log: Optional[PunchLog] = None

            for l in d_logs:
                if l.punch_type == "登園":
                    if not in_log or l.punched_at < in_log.punched_at:
                        in_log = l
                elif l.punch_type == "降園":
                    if not out_log or l.punched_at > out_log.punched_at:
                        out_log = l
                elif l.punch_type == "欠席":
                    abs_log = l

            in_time_str = in_log.punched_at.strftime("%H:%M") if in_log else ""
            out_time_str = out_log.punched_at.strftime("%H:%M") if out_log else ""
            reason_str = abs_log.absence_reason if abs_log and abs_log.absence_reason in VALID_ABSENCE_REASONS else ""

            # F-11: 降園抜け自動検知＆「18:00」自動補完
            if in_time_str and not out_time_str:
                out_time_str = "18:00"
                missing_checkouts.append({
                    "date": date_str,
                    "child_name": clean_name,
                    "check_in_time": in_time_str,
                    "auto_checkout_time": "18:00",
                    "status": "自動補完",
                })

            # 排他制御ルール: 登降園時刻のいずれかが入っている場合、欠席理由は必ず空欄にする
            if in_time_str or out_time_str:
                reason_str = ""

            # 9列構成
            row = [
                clean_name,      # 1. 氏名
                clean_kana,      # 2. 氏名カナ
                birth_str,       # 3. 生年月日
                "",              # 4. 未使用
                "",              # 5. 未使用
                date_str,        # 6. 日付
                reason_str,      # 7. 欠席理由
                in_time_str,     # 8. 登園時刻
                out_time_str,    # 9. 降園時刻
            ]
            output_rows.append(row)

    # BOM付きUTF-8, CRLFでCSV出力
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerows(output_rows)

    csv_text = buffer.getvalue()
    csv_bytes = codecs.BOM_UTF8 + csv_text.encode("utf-8")
    return csv_bytes, missing_checkouts


def export_missing_checkouts_csv(missing_list: List[Dict[str, Any]], year: int, month: int) -> bytes:
    """降園打刻忘れ一覧CSVを生成する (BOM付きUTF-8, CRLF)。

    カラム定義: 日付, 児童名, 登園時刻, 補完降園時刻, 状態
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(["日付", "児童名", "登園時刻", "補完降園時刻", "状態"])

    for item in missing_list:
        writer.writerow([
            item["date"],
            item["child_name"],
            item["check_in_time"],
            item["auto_checkout_time"],
            item["status"],
        ])

    csv_text = buffer.getvalue()
    return codecs.BOM_UTF8 + csv_text.encode("utf-8")

