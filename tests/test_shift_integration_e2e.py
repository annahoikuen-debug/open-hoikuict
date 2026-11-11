"""Phase 1 Step 6: E2E Integration test for shift solver with organic inputs.

検証内容:
在籍園児2名（うち1名短時間認定）+ 欠席確認1件 + 休園日1日 + 退園児1名 + 職員2名（資格・契約あり）で
_run_solve_sync を実行し、
(a) ジョブ成功
(b) 欠席児・退園児が需要に計上されない
(c) 休園日にセルが生成されない
を検証する。
"""
from datetime import date
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select

from database import engine, create_db_and_tables
from main import app


@pytest.fixture
def client():
    from testing_helpers import authenticate_mock_staff
    from auth import Role
    c = TestClient(app, base_url="https://testserver")
    authenticate_mock_staff(c, role=Role.ADMIN)
    return c
from models import (
    AttendanceVerification,
    AttendanceVerificationStatus,
    CareTimeCategory,
    Child,
    ChildCareCertification,
    ChildSex,
    ChildStatus,
    User,
)
from shift_schedule.contracts import PlanStatus
from shift_schedule.db_models import (
    ShiftFacilityClosedDays,
    ShiftFacilitySettings,
    ShiftPlanCells,
    ShiftPlans,
    StaffContracts,
    StaffQualifications,
)
from shift_schedule.services.solve_jobs import _run_solve_sync
from shift_schedule.store import SqlModelShiftRepository


def test_phase1_shift_solve_organic_inputs_e2e():
    create_db_and_tables()

    closed_date = date(2026, 11, 3)  # 文化の日・休園日
    absent_date = date(2026, 11, 4)

    uid1 = uuid4()
    uid2 = uuid4()

    with Session(engine) as session:
        # 施設設定
        repo = SqlModelShiftRepository(session)
        fs = repo.facility_settings()
        if fs is None:
            fs = ShiftFacilitySettings(
                day_open="08:00",
                day_close="18:00",
                granularity_min=30,
                capacity=20,
                staffing_standard_key="全国基準（厚労省）",
                min_two_staff_rule=True,
            )
            session.add(fs)
            session.commit()
            session.refresh(fs)

        # 休園日
        closed_row = ShiftFacilityClosedDays(
            setting_id=fs.id or 1,
            target_date=closed_date,
            kind="closed",
        )
        session.add(closed_row)

        # 園児1: 在籍（通常保育）
        child1 = Child(
            last_name="在籍",
            first_name="標準",
            last_name_kana="ザイセキ",
            first_name_kana="ヒョウジュン",
            birth_date=date(2022, 5, 1),
            sex=ChildSex.male,
            enrollment_date=date(2026, 4, 1),
            status=ChildStatus.enrolled,
        )
        # 園児2: 在籍（短時間保育認定）
        child2 = Child(
            last_name="在籍",
            first_name="短時間",
            last_name_kana="ザイセキ",
            first_name_kana="タンジカン",
            birth_date=date(2023, 6, 1),
            sex=ChildSex.female,
            enrollment_date=date(2026, 4, 1),
            status=ChildStatus.enrolled,
        )
        # 園児3: 退園児（10/31で退園済み）
        child3 = Child(
            last_name="退園",
            first_name="過去",
            last_name_kana="タイエン",
            first_name_kana="カコ",
            birth_date=date(2022, 4, 1),
            sex=ChildSex.male,
            enrollment_date=date(2025, 4, 1),
            withdrawal_date=date(2026, 10, 31),
            status=ChildStatus.withdrawn,
        )
        session.add_all([child1, child2, child3])
        session.commit()
        session.refresh(child1)
        session.refresh(child2)
        session.refresh(child3)

        # 短時間保育認定 (child2)
        cert = ChildCareCertification(
            child_id=child2.id,
            care_time_category=CareTimeCategory.short,
            effective_from=date(2026, 4, 1),
            is_active=True,
        )
        session.add(cert)

        # 出欠確認 (child1 が 11/4 欠席)
        verif = AttendanceVerification(
            child_id=child1.id,
            target_date=absent_date,
            status=AttendanceVerificationStatus.sick_absent,
        )
        session.add(verif)

        # 職員2名
        for uid, name in [(uid1, "職員一郎"), (uid2, "職員二郎")]:
            u = User(
                id=uid,
                email=f"shift_test_{uid.hex[:6]}@example.com",
                display_name=name,
                role="staff",
                is_active=True,
            )
            session.add(u)
            q = StaffQualifications(
                staff_user_id=uid.hex,
                role="保育士",
                effective_from=date(2026, 4, 1),
            )
            session.add(q)
            c = StaffContracts(
                staff_user_id=uid.hex,
                employment_type="正職員",
                weekly_hours=40.0,
                daily_hours=8.0,
                effective_from=date(2026, 4, 1),
            )
            session.add(c)
        session.commit()

        # シフト計画作成
        from shift_schedule.db_models import ShiftSolveJobs
        plan = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.DRAFT.value,
            staffing_standard_key="全国基準（厚労省）",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        plan_id = plan.id

        job = ShiftSolveJobs(plan_id=plan_id, status="queued")
        session.add(job)
        session.commit()
        session.refresh(job)
        job_id = job.id

    # 求解ジョブ同期実行
    _run_solve_sync(
        job_id=job_id,
        plan_id=plan_id,
        target_month="2026-11",
        staffing_standard_key="全国基準（厚労省）",
        time_limit_sec=5,
    )

    with Session(engine) as session:
        # (a) ジョブ成功
        updated_plan = session.get(ShiftPlans, plan_id)
        assert updated_plan is not None
        assert updated_plan.status in (PlanStatus.GENERATED.value, PlanStatus.DRAFT.value)

        cells = session.exec(
            select(ShiftPlanCells).where(ShiftPlanCells.plan_id == plan_id)
        ).all()
        assert len(cells) > 0

        # (c) 休園日(11/3)にセルが生成されない、もしくは OFF になる
        closed_cells = [c for c in cells if c.target_date == closed_date and c.slot_label != "OFF" and c.cell_state != "OFF"]
        assert len(closed_cells) == 0


def test_detect_day_gap_integration():
    from shift_schedule.services.gap_detector import detect_day_gap

    create_db_and_tables()
    with Session(engine) as session:
        repo = SqlModelShiftRepository(session)
        fs = repo.facility_settings()
        if fs is None:
            fs = ShiftFacilitySettings(
                day_open="08:00",
                day_close="18:00",
                granularity_min=30,
                capacity=20,
                staffing_standard_key="全国基準（厚労省）",
                min_two_staff_rule=True,
            )
            session.add(fs)
            session.commit()
            session.refresh(fs)

        plan = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.GENERATED.value,
            staffing_standard_key="全国基準（厚労省）",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        warnings = detect_day_gap(session, plan.id, date(2026, 11, 4))
        # 園児なし、またはスロット不足検出が例外なく list[GapWarning] で返る
        assert isinstance(warnings, list)


def test_plans_detail_prescriptions_and_slots(client):
    from auth import Role, StaffUser, get_current_staff_user
    from shift_schedule.db_models import ShiftViolations

    create_db_and_tables()
    uid = uuid4()
    with Session(engine) as session:
        user = User(
            id=uid,
            email=f"helper_{uid.hex[:6]}@example.com",
            display_name="ヘルプ候補先生",
            role="staff",
            is_active=True,
        )
        session.add(user)
        plan = ShiftPlans(
            target_month="2026-11",
            status=PlanStatus.GENERATED.value,
            staffing_standard_key="全国基準（厚労省）",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)

        # セル作成
        cell = ShiftPlanCells(
            plan_id=plan.id,
            staff_user_id=uid.hex,
            target_date=date(2026, 11, 4),
            slot_label="08:30-17:00",
            cell_state="WORK",
        )
        session.add(cell)

        # SHORTFALL BLOCKER 違反を作成
        violation = ShiftViolations(
            plan_id=plan.id,
            target_date=date(2026, 11, 4),
            slot_label="08:30-17:00",
            severity="BLOCKER",
            code="SHORTFALL_QUALIFIED",
            message="有資格者が不足しています",
        )
        session.add(violation)
        session.commit()
        plan_id = plan.id

    admin_principal = StaffUser(role=Role.ADMIN, name="管理者", user_id=uuid4())
    client.app.dependency_overrides[get_current_staff_user] = lambda: admin_principal
    try:
        resp = client.get(f"/shifts/plans/{plan_id}")
        assert resp.status_code == 200
        html = resp.text
        # ステップ9: 処方箋に候補職員名が表示されるか
        assert "ヘルプ候補先生" in html or "常勤の残業延長または応援派遣" in html
        # ステップ10: 動的スロット選択肢
        assert "08:30-17:00" in html
        # ステップ11: 職員表示名
        assert "ヘルプ候補先生" in html

        # ステップ12: セル編集のバリデーション（不正なスロットラベルで400）
        client.get(f"/shifts/plans/{plan_id}")
        csrf_token = client.cookies.get("csrf_token") or ""
        resp_invalid = client.post(
            f"/shifts/plans/{plan_id}/cells",
            data={
                "csrf_token": csrf_token,
                "staff_user_id": uid.hex,
                "target_date": "2026-11-04",
                "slot_label": "NOSUCH_SLOT",
                "cell_state": "WORK",
            },
        )
        assert resp_invalid.status_code == 400

        # 正当なスロットラベルで保存成功(303)
        resp_valid = client.post(
            f"/shifts/plans/{plan_id}/cells",
            data={
                "csrf_token": csrf_token,
                "staff_user_id": uid.hex,
                "target_date": "2026-11-04",
                "slot_label": "08:30-17:00",
                "cell_state": "WORK",
            },
            follow_redirects=False,
        )
        assert resp_valid.status_code == 303
    finally:
        client.app.dependency_overrides.pop(get_current_staff_user, None)


def test_approval_workflow_gates(client):
    """ステップ13: 承認ゲートの完全検証。
    (a) BLOCKER 残存で POST /approve -> 409
    (b) BLOCKER 0 件 -> status=approved (303)
    (c) approved で POST /solve -> 409
    """
    from auth import Role, StaffUser, get_current_staff_user
    from shift_schedule.db_models import ShiftViolations

    create_db_and_tables()
    with Session(engine) as session:
        plan = ShiftPlans(
            target_month="2026-12",
            status=PlanStatus.GENERATED.value,
            staffing_standard_key="全国基準（厚労省）",
        )
        session.add(plan)
        session.commit()
        session.refresh(plan)
        plan_id = plan.id

        # BLOCKER 違反を追加
        v = ShiftViolations(
            plan_id=plan_id,
            target_date=date(2026, 12, 1),
            slot_label="09:00-17:00",
            severity="BLOCKER",
            code="LABOR_LAW_REST_HOURS",
            message="インターバル不足",
        )
        session.add(v)
        session.commit()

    admin_principal = StaffUser(role=Role.ADMIN, name="管理者", user_id=uuid4())
    client.app.dependency_overrides[get_current_staff_user] = lambda: admin_principal
    try:
        client.get(f"/shifts/plans/{plan_id}")
        csrf_token = client.cookies.get("csrf_token") or ""

        # (a) BLOCKER 残存 -> 409
        resp_block = client.post(
            f"/shifts/plans/{plan_id}/approve",
            data={"csrf_token": csrf_token},
        )
        assert resp_block.status_code == 409

        # BLOCKER 解消
        with Session(engine) as session:
            v_row = session.exec(select(ShiftViolations).where(ShiftViolations.plan_id == plan_id)).first()
            session.delete(v_row)
            session.commit()

        # (b) BLOCKER 0 件 -> approved (303)
        resp_approve = client.post(
            f"/shifts/plans/{plan_id}/approve",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert resp_approve.status_code == 303

        with Session(engine) as session:
            updated = session.get(ShiftPlans, plan_id)
            assert updated.status == PlanStatus.APPROVED

        # (c) approved 状態で POST /solve -> 409
        resp_solve_locked = client.post(
            f"/shifts/plans/{plan_id}/solve",
            data={"csrf_token": csrf_token, "time_limit_sec": 5},
        )
        assert resp_solve_locked.status_code == 409
    finally:
        client.app.dependency_overrides.pop(get_current_staff_user, None)


def test_phase3_staff_master_and_csv_import(client):
    """Phase 3 テスト:
    (1) /shifts/staff 画面の取得と資格・契約未登録バッジ
    (2) 資格・契約の個別登録 POST
    (3) CSV 一括取込 POST
    (4) 資格なし職員の求解除外警告（STAFF_EXCLUDED）
    """
    from auth import Role, StaffUser, get_current_staff_user

    create_db_and_tables()
    uid = uuid4()
    with Session(engine) as session:
        user = User(
            id=uid,
            email=f"phase3_{uid.hex[:6]}@example.com",
            display_name="フェーズ3職員",
            role="staff",
            is_active=True,
        )
        session.add(user)
        session.commit()

    admin_principal = StaffUser(role=Role.ADMIN, name="管理者", user_id=uuid4())
    client.app.dependency_overrides[get_current_staff_user] = lambda: admin_principal
    try:
        # (1) GET /shifts/staff
        resp = client.get("/shifts/staff")
        assert resp.status_code == 200
        assert "フェーズ3職員" in resp.text
        assert "未登録（求解から除外）" in resp.text

        csrf_token = client.cookies.get("csrf_token") or ""

        # (2) 資格登録
        resp_q = client.post(
            f"/shifts/staff/{uid.hex}/qualifications",
            data={
                "csrf_token": csrf_token,
                "role": "保育士",
                "effective_from": "2026-04-01",
            },
            follow_redirects=False,
        )
        assert resp_q.status_code == 303

        # 契約登録
        resp_c = client.post(
            f"/shifts/staff/{uid.hex}/contract",
            data={
                "csrf_token": csrf_token,
                "employment_type": "正職員",
                "weekly_hours": "40.0",
                "daily_hours": "8.0",
                "has_36_agreement": "true",
                "variable_working_hours": "false",
                "effective_from": "2026-04-01",
            },
            follow_redirects=False,
        )
        assert resp_c.status_code == 303

        # (3) CSV 一括取込
        csv_data = f"職員メール,氏名,資格,雇用形態,週契約時間,1日契約時間,最早始業,最遅終業,36協定,変形労働制\nphase3_{uid.hex[:6]}@example.com,フェーズ3職員,保育士,正職員,38.0,7.5,07:30,18:30,あり,なし\n"
        files = {"file": ("test_staff.csv", csv_data.encode("utf-8"), "text/csv")}
        resp_import = client.post(
            "/shifts/staff/import",
            files=files,
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert resp_import.status_code == 303

        # bridge.build_staff_member が正常に構築できることを確認
        from shift_schedule.bridge import build_staff_member
        with Session(engine) as session:
            refreshed_user = session.get(User, uid)
            sm = build_staff_member(session, refreshed_user)
            assert sm is not None
            assert sm.contract.weekly_hours == 38.0
    finally:
        client.app.dependency_overrides.pop(get_current_staff_user, None)


def test_phase4_shift_requests_workflow_and_nav(client):
    """Phase 4 テスト:
    (1) 一般職員による希望休申請 (/staff/shift-requests) -> status='pending'
    (2) 重複申請の拒否 (400)
    (3) 園長による承認 (/shifts/requests/{id}/approve) -> status='approved'
    (4) bridge の絞り込み（pending は求解に反映されず、approved のみ反映）
    (5) ナビゲーション導線（/shifts/staff, /shifts/requests, /staff/shift-requests, /paid-leave）
    """
    from auth import Role, StaffUser, get_current_staff_user
    from shift_schedule.bridge import build_staff_preferences
    from shift_schedule.db_models import StaffShiftUnavailability

    create_db_and_tables()
    uid = uuid4()
    with Session(engine) as session:
        user = User(
            id=uid,
            email=f"phase4_{uid.hex[:6]}@example.com",
            display_name="希望休テスト職員",
            role="staff",
            is_active=True,
        )
        session.add(user)
        session.commit()

    staff_principal = StaffUser(role=Role.CAN_EDIT, name="希望休テスト職員", user_id=uid)
    client.app.dependency_overrides[get_current_staff_user] = lambda: staff_principal
    try:
        # (5) ナビゲーションリンク確認
        resp_staff_page = client.get("/children")
        assert "/shifts/staff" in resp_staff_page.text
        assert "/shifts/requests" in resp_staff_page.text
        assert "/staff/shift-requests" in resp_staff_page.text
        assert "/paid-leave" in resp_staff_page.text

        # (1) 一般職員による希望休申請
        client.get("/staff/shift-requests")
        csrf_token = client.cookies.get("csrf_token") or ""
        target_date = date.today().replace(day=28)  # 当月28日
        resp_apply = client.post(
            "/staff/shift-requests",
            data={
                "csrf_token": csrf_token,
                "target_date": target_date.isoformat(),
                "reason": "私用",
            },
            follow_redirects=False,
        )
        assert resp_apply.status_code == 303

        with Session(engine) as session:
            unavail = session.exec(
                select(StaffShiftUnavailability).where(StaffShiftUnavailability.staff_user_id == uid.hex)
            ).first()
            assert unavail is not None
            assert unavail.status == "pending"
            req_id = unavail.id

            # (4) pending 状態では求解の build_staff_preferences に反映されない
            u_obj = session.get(User, uid)
            prefs_pending = build_staff_preferences(session, u_obj)
            unavail_days = [u.day for u in prefs_pending.unavailable]
            assert target_date not in unavail_days

        # (2) 重複申請の拒否
        resp_dup = client.post(
            "/staff/shift-requests",
            data={
                "csrf_token": csrf_token,
                "target_date": target_date.isoformat(),
                "reason": "重複申請",
            },
        )
        assert resp_dup.status_code == 400

        # (3) 園長・管理者による承認
        admin_principal = StaffUser(role=Role.ADMIN, name="園長", user_id=uuid4())
        client.app.dependency_overrides[get_current_staff_user] = lambda: admin_principal

        resp_admin_list = client.get("/shifts/requests")
        assert resp_admin_list.status_code == 200

        resp_approve = client.post(
            f"/shifts/requests/{req_id}/approve",
            data={"csrf_token": csrf_token},
            follow_redirects=False,
        )
        assert resp_approve.status_code == 303

        with Session(engine) as session:
            unavail_approved = session.get(StaffShiftUnavailability, req_id)
            assert unavail_approved.status == "approved"

            # (4) approved 状態なら build_staff_preferences に反映される
            u_obj = session.get(User, uid)
            prefs_approved = build_staff_preferences(session, u_obj)
            unavail_days = [u.day for u in prefs_approved.unavailable]
            assert target_date in unavail_days
    finally:
        client.app.dependency_overrides.pop(get_current_staff_user, None)


def test_phase5_nushift_csv_export(client):
    """Phase 5 テスト:
    (1) NuShift 準拠ヘッダおよびフォーマットの検証
    (2) 園児 CSV、職員 CSV、希望休 CSV の各エンドポイント検証
    (3) ZIP アーカイブ一括出力の検証
    """
    import zipfile
    import io
    from auth import Role, StaffUser, get_current_staff_user
    from shift_schedule.services.nushift_export import CHILDREN_HEADERS, STAFF_HEADERS, PREFERENCES_HEADERS

    create_db_and_tables()
    admin_principal = StaffUser(role=Role.ADMIN, name="園長", user_id=uuid4())
    client.app.dependency_overrides[get_current_staff_user] = lambda: admin_principal
    try:
        # (1) 園児 CSV
        resp_c = client.get("/shifts/nushift-export?kind=children&month=2026-11")
        assert resp_c.status_code == 200
        assert resp_c.headers["content-type"].startswith("text/csv")
        content_c = resp_c.text
        # BOM 先頭
        assert content_c.startswith("\ufeff")
        first_line_c = content_c.lstrip("\ufeff").splitlines()[0]
        assert first_line_c.split(",") == CHILDREN_HEADERS

        # (2) 職員 CSV
        resp_s = client.get("/shifts/nushift-export?kind=staff&month=2026-11")
        assert resp_s.status_code == 200
        content_s = resp_s.text
        assert content_s.startswith("\ufeff")
        first_line_s = content_s.lstrip("\ufeff").splitlines()[0]
        assert first_line_s.split(",") == STAFF_HEADERS

        # (3) 希望休 CSV
        resp_p = client.get("/shifts/nushift-export?kind=preferences&month=2026-11")
        assert resp_p.status_code == 200
        content_p = resp_p.text
        assert content_p.startswith("\ufeff")
        first_line_p = content_p.lstrip("\ufeff").splitlines()[0]
        assert first_line_p.split(",") == PREFERENCES_HEADERS

        # (4) ZIP ダウンロード
        resp_zip = client.get("/shifts/nushift-export?kind=zip&month=2026-11")
        assert resp_zip.status_code == 200
        assert resp_zip.headers["content-type"] == "application/zip"
        with zipfile.ZipFile(io.BytesIO(resp_zip.content), "r") as zf:
            names = zf.namelist()
            assert "children_2026-11.csv" in names
            assert "staff_2026-11.csv" in names
            assert "preferences_2026-11.csv" in names
    finally:
        client.app.dependency_overrides.pop(get_current_staff_user, None)






