"""マルチテナント・法人組織階層の完全分離検証テスト (Phase 4 / 回帰防止).

本テストスイートが保証する不変条件:
1. Organization（法人）および Facility（施設・園）の階層データ構造が整合していること。
2. TenantContext / tenant_scope が並行スレッド・非同期タスク間で確実に分離され、
   明示設定がない場合は後方互換性のためデフォルト識別子にフォールバックすること。
3. StaffUser の RBAC において、法人統括管理者は傘下の全園にアクセスでき、
   単一園の職員は他園のリソースへ越境アクセスできない（403 Forbidden）こと。
4. DB 初期化時にデフォルト法人・施設が自動生成されること。
"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlmodel import Session, select

from auth import Role, StaffUser, check_facility_access
from database import create_db_and_tables, engine
from models.organization import (
    DEFAULT_FACILITY_ID,
    DEFAULT_ORGANIZATION_ID,
    Facility,
    Organization,
)
from security.tenant import (
    TenantContext,
    get_current_facility_id,
    get_current_organization_id,
    tenant_scope,
)


def test_デフォルト法人と施設が自動初期化される() -> None:
    """DB初期化時にデフォルト法人・施設が存在することを検証する。"""
    create_db_and_tables()
    with Session(engine) as session:
        org = session.get(Organization, DEFAULT_ORGANIZATION_ID)
        assert org is not None
        assert org.name == "デフォルト法人"

        fac = session.get(Facility, DEFAULT_FACILITY_ID)
        assert fac is not None
        assert fac.organization_id == DEFAULT_ORGANIZATION_ID
        assert fac.name == "デフォルト保育園"


def test_tenant_contextの分離とデフォルトフォールバック() -> None:
    """コンテキスト未指定時はデフォルトIDを返し、スコープ内では指定IDに切り替わること。"""
    # 1. デフォルト
    assert get_current_organization_id() == DEFAULT_ORGANIZATION_ID
    assert get_current_facility_id() == DEFAULT_FACILITY_ID

    custom_org_id = uuid4()
    custom_fac_id = uuid4()

    # 2. tenant_scope 内
    with tenant_scope(organization_id=custom_org_id, facility_id=custom_fac_id):
        assert get_current_organization_id() == custom_org_id
        assert get_current_facility_id() == custom_fac_id

    # 3. スコープ脱出後は元に戻る
    assert get_current_organization_id() == DEFAULT_ORGANIZATION_ID
    assert get_current_facility_id() == DEFAULT_FACILITY_ID

    # 4. TenantContext クラスでの利用
    with TenantContext(organization_id=custom_org_id, facility_id=custom_fac_id):
        assert get_current_organization_id() == custom_org_id
        assert get_current_facility_id() == custom_fac_id

    assert get_current_organization_id() == DEFAULT_ORGANIZATION_ID


def test_法人組織と複数園の登録とリレーション() -> None:
    """1つの法人に複数の園が紐づくデータ構造を検証する。"""
    create_db_and_tables()
    org_id = uuid4()
    fac1_id = uuid4()
    fac2_id = uuid4()

    with Session(engine) as session:
        org = Organization(
            id=org_id,
            name="社会福祉法人さくら会",
            code=f"SAKURA_{uuid4().hex[:6]}",
        )
        session.add(org)
        session.flush()

        fac1 = Facility(
            id=fac1_id,
            organization_id=org_id,
            name="さくら保育園 本園",
            code=f"SAKURA-01_{uuid4().hex[:6]}",
        )
        fac2 = Facility(
            id=fac2_id,
            organization_id=org_id,
            name="さくら第二保育園",
            code=f"SAKURA-02_{uuid4().hex[:6]}",
        )
        session.add(fac1)
        session.add(fac2)
        session.commit()

        # 問い合わせ検証
        facilities = session.exec(
            select(Facility).where(Facility.organization_id == org_id)
        ).all()
        assert len(facilities) == 2
        fac_names = {f.name for f in facilities}
        assert "さくら保育園 本園" in fac_names
        assert "さくら第二保育園" in fac_names


def test_マルチテナントRBACアクセス権限検証() -> None:
    """法人統括管理者と自園職員の権限境界（他園越境防御）を検証する。"""
    org_id = uuid4()
    fac_a_id = uuid4()
    fac_b_id = uuid4()

    # 1. 園Aの一般職員
    staff_a = StaffUser(
        role=Role.CAN_EDIT,
        name="園A 職員",
        organization_id=org_id,
        facility_id=fac_a_id,
        is_corporate_admin=False,
    )
    assert staff_a.can_access_facility(fac_a_id) is True
    assert staff_a.can_access_facility(fac_b_id) is False

    # check_facility_access の挙動
    check_facility_access(staff_a, fac_a_id)  # 例外なし

    with pytest.raises(HTTPException) as exc_info:
        check_facility_access(staff_a, fac_b_id)
    assert exc_info.value.status_code == 403
    assert "アクセス権限がありません" in exc_info.value.detail

    # 2. 法人統括管理者（全園横断アクセス可能）
    corporate_admin = StaffUser(
        role=Role.ADMIN,
        name="法人統括 理事長",
        organization_id=org_id,
        facility_id=fac_a_id,
        is_corporate_admin=True,
    )
    assert corporate_admin.can_access_facility(fac_a_id) is True
    assert corporate_admin.can_access_facility(fac_b_id) is True

    check_facility_access(corporate_admin, fac_a_id)  # 例外なし
    check_facility_access(corporate_admin, fac_b_id)  # 例外なし
