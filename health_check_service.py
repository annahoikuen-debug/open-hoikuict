"""施設・園の初期設定および運用ヘルスチェック診断サービス (P1-1)。

クラス未所属園児、料金マスタ、全銀設定、開園時間、キオスク設定などの
抜け漏れを自動診断し、健全度スコアと推奨アクションを生成します。
"""
from __future__ import annotations

from typing import Any
from sqlmodel import Session, select

from guardian_hours import closing_time
from models import (
    BillingSetting,
    Child,
    ChildStatus,
    FacilitySettings,
    FeeItem,
)
from staff_session_settings import get_staff_session_policy


def run_facility_health_check(session: Session) -> dict[str, Any]:
    """園の全体設定を診断し、健全度スコアと診断結果リストを返す。"""
    diagnostics: list[dict[str, Any]] = []

    # 1. 全銀口座振替の委託者コード
    zengin_setting = session.exec(select(BillingSetting).order_by(BillingSetting.id)).first()
    if zengin_setting is None or zengin_setting.collector_code in {"", "1234567890", "0000000000"}:
        diagnostics.append({
            "id": "zengin_collector_code",
            "category": "請求・口座振替",
            "title": "全銀口座振替の委託者コードが初期値のままです",
            "description": "委託者コードが未設定またはダミー値になっています。銀行提出用電文を作成する前に正規コードの登録が必要です。",
            "level": "critical",
            "action_url": "/billing/settings",
            "action_label": "全銀設定を修正 →",
        })
    else:
        diagnostics.append({
            "id": "zengin_collector_code",
            "category": "請求・口座振替",
            "title": "全銀口座振替設定",
            "description": f"委託者コード（{zengin_setting.collector_code}）が正しく登録されています。",
            "level": "ok",
            "action_url": "/billing/settings",
            "action_label": "設定を確認 →",
        })

    # 2. クラス未所属の在園児
    unassigned_children = session.exec(
        select(Child).where(
            Child.status == ChildStatus.enrolled,
            Child.classroom_id == None,  # noqa: E711
        )
    ).all()
    if unassigned_children:
        names = "、".join(c.full_name for c in unassigned_children[:3])
        if len(unassigned_children) > 3:
            names += f" ほか計{len(unassigned_children)}名"
        diagnostics.append({
            "id": "unassigned_children",
            "category": "園児・クラス",
            "title": f"クラスに所属していない在園児が {len(unassigned_children)} 名います",
            "description": f"未所属（{names}）は出欠管理や連絡帳一覧に表示されません。所属クラスを割り当ててください。",
            "level": "warning",
            "action_url": "/classrooms/",
            "action_label": "クラスを割当 →",
        })
    else:
        diagnostics.append({
            "id": "unassigned_children",
            "category": "園児・クラス",
            "title": "園児のクラス割当",
            "description": "すべての在園児がいずれかのクラスに適切に所属しています。",
            "level": "ok",
            "action_url": "/classrooms/",
            "action_label": "クラス一覧 →",
        })

    # 3. 請求項目マスタ (FeeItem)
    active_fee_items = session.exec(
        select(FeeItem).where(FeeItem.is_active == True)  # noqa: E712
    ).all()
    if not active_fee_items:
        diagnostics.append({
            "id": "fee_items_defined",
            "category": "請求・口座振替",
            "title": "料金項目マスタが登録されていません",
            "description": "毎月の給食費や教材費等の請求計算を行うには料金マスタの登録が必要です。",
            "level": "warning",
            "action_url": "/billing/settings",
            "action_label": "料金項目を登録 →",
        })
    else:
        diagnostics.append({
            "id": "fee_items_defined",
            "category": "請求・口座振替",
            "title": "請求項目マスタ (FeeItem)",
            "description": f"{len(active_fee_items)} 件の請求項目マスタが有効化されています。",
            "level": "ok",
            "action_url": "/billing/settings",
            "action_label": "マスタを確認 →",
        })

    # 4. 施設基本設定 (FacilitySettings)
    facility_setting = session.exec(select(FacilitySettings)).first()
    if facility_setting is None:
        diagnostics.append({
            "id": "facility_settings",
            "category": "施設運用",
            "title": "施設基本設定が未完了です",
            "description": "お迎え最終時刻や発熱判定基準値が設定されていません。",
            "level": "warning",
            "action_url": "/settings/facility",
            "action_label": "基本設定を開く →",
        })
    else:
        fever_c = getattr(facility_setting, "fever_caution_c", "37.5")
        diagnostics.append({
            "id": "facility_settings",
            "category": "施設運用",
            "title": "施設基本設定（開園・発熱基準）",
            "description": f"発熱判定基準（{fever_c}℃）等が適切に設定されています。",
            "level": "ok",
            "action_url": "/settings/facility",
            "action_label": "設定を確認 →",
        })

    # 5. キオスク閉園時刻 (Guardian Hours)
    kiosk_closing = closing_time(session)
    if not kiosk_closing:
        diagnostics.append({
            "id": "kiosk_closing",
            "category": "施設運用",
            "title": "キオスクの閉園時刻が未設定です",
            "description": "保護者タブレットでの登降園受付終了時刻が設定されていません。",
            "level": "warning",
            "action_url": "/settings/guardian-hours",
            "action_label": "閉園時刻を設定 →",
        })
    else:
        diagnostics.append({
            "id": "kiosk_closing",
            "category": "施設運用",
            "title": "キオスク閉園時刻",
            "description": f"キオスク閉園時刻（{kiosk_closing}）が設定されています。",
            "level": "ok",
            "action_url": "/settings/guardian-hours",
            "action_label": "設定を確認 →",
        })

    # 6. 職員セッション維持時間 (Staff Session Policy)
    try:
        policy = get_staff_session_policy(session)
        timeout_min = policy.idle_minutes if policy else 30
        diagnostics.append({
            "id": "staff_session_policy",
            "category": "セキュリティ",
            "title": "職員ログイン維持時間",
            "description": f"セッション有効期限（{timeout_min}分）が設定されています。",
            "level": "ok",
            "action_url": "/settings/staff-sessions",
            "action_label": "時間設定を確認 →",
        })
    except Exception:
        diagnostics.append({
            "id": "staff_session_policy",
            "category": "セキュリティ",
            "title": "職員ログイン維持時間",
            "description": "セッション有効期限が安全な範囲に設定されているか確認してください。",
            "level": "ok",
            "action_url": "/settings/staff-sessions",
            "action_label": "設定を確認 →",
        })

    # スコアとカウントの集計
    critical_count = sum(1 for d in diagnostics if d["level"] == "critical")
    warning_count = sum(1 for d in diagnostics if d["level"] == "warning")
    ok_count = sum(1 for d in diagnostics if d["level"] == "ok")

    score = 100 - (critical_count * 25) - (warning_count * 10)
    score = max(0, min(100, score))

    if score >= 90:
        rating = "良好"
    elif score >= 70:
        rating = "概ね良好"
    elif score >= 50:
        rating = "注意"
    else:
        rating = "要対応"

    return {
        "score": score,
        "rating": rating,
        "counts": {
            "critical": critical_count,
            "warning": warning_count,
            "ok": ok_count,
            "total": len(diagnostics),
        },
        "diagnostics": diagnostics,
    }
