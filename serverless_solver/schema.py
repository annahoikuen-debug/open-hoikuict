"""Pydantic schemas for Serverless Solver API (NuShift Solver-as-a-Service).

ステートレスなJSONシリアライズ／デシリアライズを保証し、
Webサーバー本体（FastAPI）とサーバーレスコンテナ間の型安全なAPI契約を定義する。
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class FacilityConfigSchema(BaseModel):
    """施設基本動作設定"""

    opening_time: str = Field(default="07:00", description="開所時刻 (HH:MM)")
    closing_time: str = Field(default="19:00", description="閉所時刻 (HH:MM)")
    granularity_min: int = Field(default=30, description="スロット刻み（分）")
    eleven_hour_rule: bool = Field(default=True, description="開所11時間超の常時2名以上配置ルール適用")
    min_staff_present: int = Field(default=2, description="保育時間帯の常時最低配置人数")
    closed_days: list[str] = Field(default_factory=list, description="休園日 (YYYY-MM-DD)")
    holiday_dates: list[str] = Field(default_factory=list, description="祝日 (YYYY-MM-DD)")


class ChildPlanSchema(BaseModel):
    """園児登降園計画"""

    child_id: str = Field(description="園児ID")
    name: str = Field(default="", description="園児氏名")
    day: str = Field(description="対象日 (YYYY-MM-DD)")
    age_class: str = Field(default="1歳児", description="年齢クラス表記")
    arrive: str = Field(default="08:30", description="登園時刻 (HH:MM)")
    depart: str = Field(default="16:30", description="降園時刻 (HH:MM)")
    is_short_time: bool = Field(default=False, description="保育短時間区分")
    absent: bool = Field(default=False, description="欠席フラグ")
    uses_early_care: bool = Field(default=False, description="早朝保育利用")
    uses_late_care: bool = Field(default=False, description="延長保育利用")


class StaffItemSchema(BaseModel):
    """職員定義"""

    staff_id: str = Field(description="職員ID（文字列）")
    name: str = Field(description="職員氏名")
    employment_type: str = Field(default="FULL_TIME", description="FULL_TIME / PART_TIME")
    is_qualified: bool = Field(default=True, description="保育士資格の有無")
    weekly_contract_hours: float = Field(default=40.0, description="週契約労働時間")
    max_consecutive_days: int = Field(default=5, description="連続勤務日数上限")
    can_work_early: bool = Field(default=True, description="早番可能か")
    can_work_late: bool = Field(default=True, description="遅番可能か")
    unavailable_dates: list[str] = Field(default_factory=list, description="希望休・有給・不可日 (YYYY-MM-DD)")


class ShiftSlotSchema(BaseModel):
    """個別スロットまたは勤務パターン枠"""

    code: str = Field(description="勤務記号（早/日/遅/休等）またはスロットラベル")
    start: Optional[str] = Field(default=None, description="開始時刻 (HH:MM)")
    end: Optional[str] = Field(default=None, description="終了時刻 (HH:MM)")
    break_hours: float = Field(default=1.0, description="休憩時間（時間）")
    is_pinned: bool = Field(default=False, description="手動ピン留め（固定保護）フラグ")
    slots: dict[str, str] = Field(
        default_factory=dict,
        description="スロット詳細状態 (slot_label -> CellState value)",
    )


class SolverOptionsSchema(BaseModel):
    """求解オプション"""

    time_limit_sec: int = Field(default=30, description="最大計算時間上限（秒）")
    solver_name: Optional[str] = Field(default="highs", description="highs または cbc")
    allow_shortfall: bool = Field(default=True, description="過剰制約計画（不足許容・ペナルティ最小化）の有効化")
    parallel_workers: int = Field(default=1, description="並行ソルバープロセス数")


class ShiftSolveRequest(BaseModel):
    """サーバーレス求解リクエスト"""

    facility_id: str | int = Field(default=1, description="施設ID")
    target_month: str = Field(description="対象年月 (YYYY-MM)")
    staffing_standard_key: str = Field(default="全国基準（厚労省）", description="配置基準プリセットキー")
    facility_config: FacilityConfigSchema = Field(default_factory=FacilityConfigSchema)
    children: list[ChildPlanSchema] = Field(
        default_factory=list,
        description="園児登降園計画一覧（配置基準需要の算出に使用）",
    )
    staff_list: list[StaffItemSchema] = Field(description="求解対象職員リスト")
    requirements: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="日別・スロット別の必要人員マトリクス (date -> slot_label -> required_count)",
    )
    pinned_assignments: dict[str, dict[str, ShiftSlotSchema]] = Field(
        default_factory=dict,
        description="固定ピン留めセル (staff_id -> date -> ShiftSlotSchema)",
    )
    prior_duty_streaks: dict[str, int] = Field(
        default_factory=dict,
        description="前月末時点の職員別連続勤務日数",
    )
    options: SolverOptionsSchema = Field(default_factory=SolverOptionsSchema)


class ScoreReportSchema(BaseModel):
    """Hard/Medium/Soft 3階層スコア"""

    hard: int = Field(default=0, description="法定・就業規則違反ペナルティ（0が必須）")
    medium: int = Field(default=0, description="配置不足コマ数ペナルティ（0が理想、不足時は最小化）")
    soft: int = Field(default=0, description="希望休・公平性スコア")


class ComplianceReportSchema(BaseModel):
    """法令遵守レポート"""

    coverage_ratio: float = Field(default=1.0, description="配置充足率 (0.0〜1.0)")
    shortfall_hours: float = Field(default=0.0, description="不足延べ時間（時間）")
    labor_standards_violations: list[str] = Field(default_factory=list, description="労基法違反メッセージ一覧")


class ShiftSolveResponse(BaseModel):
    """サーバーレス求解レスポンス"""

    status: str = Field(description="SUCCESS / FEASIBLE / INFEASIBLE / TIMEOUT / FAILED")
    elapsed_sec: float = Field(description="求解所要時間（秒）")
    score: ScoreReportSchema = Field(default_factory=ScoreReportSchema)
    schedule_matrix: dict[str, dict[str, ShiftSlotSchema]] = Field(
        default_factory=dict,
        description="確定シフトマトリクス (staff_id -> date -> ShiftSlotSchema)",
    )
    compliance_report: ComplianceReportSchema = Field(default_factory=ComplianceReportSchema)
    actionable_suggestions: list[str] = Field(
        default_factory=list,
        description="過剰制約時の自然言語処方箋（パート延長、出勤打診等）",
    )
    error_message: Optional[str] = Field(default=None, description="エラー時の詳細メッセージ")
