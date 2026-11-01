import inspect
import models
from sqlmodel import SQLModel


def test_models_all_exported_symbols():
    """models モジュールからエクスポートされている全クラス・シンボルが取得可能であることを検証する。"""
    # 必須の基底・認証・施設・職員・児童・登降園・請求・シフトモデル群の存在確認
    critical_symbols = [
        "User",
        "Child",
        "Family",
        "Classroom",
        "AttendanceRecord",
        "FacilitySettings",
        "StaffPaidLeave",
        "StaffPaidLeaveRequest",
        "ParentAccount",
        "ParentNotification",
        "ChildSex",
        "ChildStatus",
        "DailyContactEntry",
        "MeetingNote",
        "Survey",
        "ProfilePhoto",
        "BillingClaim",
        "BillingCycle",
        "ZenginExport",
        "ZenginExportLine",
    ]

    for sym in critical_symbols:
        assert hasattr(models, sym), f"models missing critical symbol: {sym}"
        val = getattr(models, sym)
        assert inspect.isclass(val), f"{sym} should be a class"


def test_models_metadata_tables():
    """SQLModel.metadata に models 内で定義された主要テーブルが正しく登録されていることを確認。"""
    tables = SQLModel.metadata.tables
    expected_tables = [
        "users",
        "children",
        "families",
        "classrooms",
        "facility_settings",
        "staff_paid_leaves",
        "staff_paid_leave_requests",
        "parent_accounts",
        "billing_claims",
        "billing_cycles",
        "zengin_exports",
        "zengin_export_lines",
    ]
    for tbl in expected_tables:
        assert tbl in tables, f"Expected table '{tbl}' not found in SQLModel.metadata.tables"
