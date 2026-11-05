"""登園可能判定サービス（改善案8）。

一般的な保育所の登園基準（発熱・感染症経過日数など）に基づき、
職員の受診判断を支援する**参考値**を返す。最終判断は園長・保護者の責任
（README の免責事項に準拠）。

判定ルール（既定値は facility_settings のように将来設定化可能な定数として分離）:
- 体温 37.5°C 以上は「要注意」、38.0°C 以上は「要検討（自宅安静を推奨）」
- 発熱欠席の翌日以降、解熱（37.0°C 未満）から丸2日経過で「登園目安」
- 主な感染症の出席停止期間の目安（学校保健安全法準拠の保育所運用例）
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

# 解熱後の登園目安日数（丸2日: 解熱日を0日として2日後）
FEVER_RETURN_DAYS = 2
# 要注意・要検討の体温しきい値
TEMP_CAUTION_C = 37.5
TEMP_REVIEW_C = 38.0

# 主な感染症の出席停止期間の目安（診断名キーワード → 解熱後待機日数）
# 学校保健安全法の第2種・第3種を保育所運用に置き換えた参考値
INFECTION_POLICIES: dict[str, dict[str, object]] = {
    "インフルエンザ": {"wait_days": 0, "after_fever": True, "label": "解熱後5日（解熱2日とする園あり）"},
    "新型コロナ": {"wait_days": 0, "after_fever": True, "label": "解熱後1日以上（症状により調整）"},
    "はしか": {"wait_days": 3, "after_fever": True, "label": "解熱後3日"},
    "風疹": {"wait_days": 0, "after_fever": True, "label": "発疹消失後"},
    "水痘": {"wait_days": 0, "after_fever": False, "label": "発疹全部が痂皮化"},
    "おたふく": {"wait_days": 0, "after_fever": False, "label": "耳下腺腫脹消失後5日"},
    "溶連菌": {"wait_days": 1, "after_fever": True, "label": "治療開始後24〜48時間経過"},
    "咽頭結膜熱": {"wait_days": 2, "after_fever": True, "label": "主要症状消退後2日"},
    "流行性角結膜炎": {"wait_days": 2, "after_fever": False, "label": "眼科医の登園許可"},
}


@dataclass(frozen=True)
class EligibilityResult:
    """登園可否の判定結果。"""
    allowed: bool
    level: str  # "ok" / "caution" / "review" / "blocked"
    messages: list[str]


def _fever_free_days(fever_free_since: date, target_date: date) -> int:
    """解熱日からの経過日数（解熱日を0日とする）。"""
    return (target_date - fever_free_since).days


def judge_fever(
    *,
    target_date: date,
    temperature_c: Optional[float],
    fever_free_since: Optional[date],
    return_days: int = FEVER_RETURN_DAYS,
    caution_c: float = TEMP_CAUTION_C,
    review_c: float = TEMP_REVIEW_C,
) -> EligibilityResult:
    """体温と解熱経過から登園可否の参考判定を返す。

    - temperature_c: 当日の体温（未計測なら None）
    - fever_free_since: 解熱した日（37.0°C 未満になった日）
    - return_days / caution_c / review_c: 施設設定で上書き可能（改善案8）
    """
    messages: list[str] = []

    # 当日の体温が高ければ当日の判定を優先
    if temperature_c is not None:
        if temperature_c >= review_c:
            messages.append(
                f"体温 {temperature_c:.1f}°C。当日は登園を控え、自宅で様子を見ることを推奨します。"
            )
            return EligibilityResult(False, "review", messages)
        if temperature_c >= caution_c:
            messages.append(
                f"体温 {temperature_c:.1f}°C。微熱のため様子観察が必要です。園と相談してください。"
            )
            return EligibilityResult(False, "caution", messages)

    if fever_free_since is None:
        return EligibilityResult(True, "ok", [])

    days = _fever_free_days(fever_free_since, target_date)
    if days < 0:
        messages.append("解熱日の指定が未来です。日付を確認してください。")
        return EligibilityResult(True, "caution", messages)
    if days < return_days:
        messages.append(
            f"解熱から{days}日経過。登園目安は解熱後{return_days}日です。"
        )
        return EligibilityResult(False, "review", messages)
    messages.append(f"解熱から{days}日経過。登園目安を満たしています。")
    return EligibilityResult(True, "ok", messages)


def judge_infection(
    *,
    diagnosis: Optional[str],
    onset_date: Optional[date],
    fever_free_since: Optional[date],
    target_date: date,
) -> EligibilityResult:
    """診断名から出席停止期間の目安を判定する。

    - diagnosis: 保護者が申告した診断名（部分一致で判定）
    - onset_date: 発症日
    """
    messages: list[str] = []
    if not diagnosis:
        return EligibilityResult(True, "ok", [])

    policy = None
    matched_name = ""
    for keyword, candidate in INFECTION_POLICIES.items():
        if keyword in diagnosis:
            policy = candidate
            matched_name = keyword
            break
    if policy is None:
        messages.append(f"「{diagnosis}」は既知の出席停止基準に未登録です。園の判断を優先してください。")
        return EligibilityResult(True, "caution", messages)

    label = policy["label"]
    after_fever = policy["after_fever"]
    if after_fever and fever_free_since is not None:
        days = _fever_free_days(fever_free_since, target_date)
        required = int(policy["wait_days"])
        if days < required:
            messages.append(
                f"{matched_name}: 解熱後{days}日（基準は{label}）。出席停止が推奨されます。"
            )
            return EligibilityResult(False, "blocked", messages)
        messages.append(f"{matched_name}: 基準（{label}）を満たしています。")
        return EligibilityResult(True, "ok", messages)

    if onset_date is not None:
        elapsed = (target_date - onset_date).days
        required = int(policy["wait_days"])
        if required and elapsed < required:
            messages.append(
                f"{matched_name}: 発症から{elapsed}日（基準は{label}）。出席停止が推奨されます。"
            )
            return EligibilityResult(False, "blocked", messages)
        messages.append(f"{matched_name}: 基準（{label}）を確認してください。")
        return EligibilityResult(True, "caution", messages)

    messages.append(f"{matched_name}: 基準（{label}）を満たしているか職員が確認してください。")
    return EligibilityResult(True, "caution", messages)


def judge_attendance(
    *,
    target_date: date,
    temperature_c: Optional[float] = None,
    fever_free_since: Optional[date] = None,
    diagnosis: Optional[str] = None,
    onset_date: Optional[date] = None,
    return_days: int = FEVER_RETURN_DAYS,
    caution_c: float = TEMP_CAUTION_C,
    review_c: float = TEMP_REVIEW_C,
) -> EligibilityResult:
    """体温・解熱経過・感染症基準を統合した登園可否の参考判定。

    return_days / caution_c / review_c に施設設定（FacilitySettings）の値を渡すと
    施設別の基準で判定する（改善案8）。省略時は既定値。
    """
    fever_result = judge_fever(
        target_date=target_date,
        temperature_c=temperature_c,
        fever_free_since=fever_free_since,
        return_days=return_days,
        caution_c=caution_c,
        review_c=review_c,
    )
    infection_result = judge_infection(
        diagnosis=diagnosis,
        onset_date=onset_date,
        fever_free_since=fever_free_since,
        target_date=target_date,
    )

    level_rank = {"ok": 0, "caution": 1, "review": 2, "blocked": 3}
    combined_level = max(
        (fever_result.level, infection_result.level),
        key=lambda level: level_rank[level],
    )
    combined_allowed = fever_result.allowed and infection_result.allowed
    return EligibilityResult(
        allowed=combined_allowed,
        level=combined_level,
        messages=[*fever_result.messages, *infection_result.messages],
    )
