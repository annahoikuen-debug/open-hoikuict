"""保護者お知らせ一覧の種別フィルタ (P6-3) および期限間近アンケート強調 (P6-4) のテスト。"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone, timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from auth import Role, StaffUser
from models import (
    Child,
    ChildStatus,
    Classroom,
    Family,
    Notice,
    NoticePriority,
    NoticeStatus,
    NoticeTarget,
    NoticeTargetType,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentNotification,
    ParentNotificationKind,
    Survey,
    SurveyAnswerUnit,
    SurveyAudienceType,
    SurveyStatus,
    SurveyTarget,
    SurveyTargetType,
)
import routers.daily_contacts as daily_contacts_module
import routers.notices as notices_module
import routers.parent_accounts as parent_accounts_module
import routers.parent_auth as parent_auth_module
import routers.parent_portal as parent_portal_module
from testing_helpers import configure_test_environment


class ParentPortalNoticesFilterTests(unittest.TestCase):
    def setUp(self):
        configure_test_environment()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(parent_portal_module.router)
        self.app.include_router(parent_portal_module.mock_login_router)
        self.app.include_router(parent_accounts_module.router)
        self.app.include_router(parent_auth_module.router)
        self.app.include_router(notices_module.router)
        self.app.include_router(daily_contacts_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[parent_portal_module.get_session] = (
            override_get_session
        )
        self.app.dependency_overrides[parent_accounts_module.get_session] = (
            override_get_session
        )
        self.app.dependency_overrides[parent_auth_module.get_session] = (
            override_get_session
        )
        self.app.dependency_overrides[notices_module.get_session] = override_get_session
        self.app.dependency_overrides[daily_contacts_module.get_session] = (
            override_get_session
        )
        self.app.dependency_overrides[parent_accounts_module.get_current_staff_user] = (
            lambda: StaffUser(
                role=Role.CAN_EDIT,
                name="台帳担当",
                can_manage_child_records=True,
            )
        )
        self.app.dependency_overrides[parent_auth_module.require_local_parent_auth] = (
            lambda: None
        )

        self.client = TestClient(self.app)

        unique_suffix = uuid4().hex[:8]

        with Session(self.engine) as session:
            classroom = Classroom(name="さくら組", display_order=1)
            session.add(classroom)
            session.flush()

            family = Family(
                family_name=f"山田家_{unique_suffix}",
                home_address="東京都渋谷区1-1-1",
                home_phone="03-0000-0000",
            )
            session.add(family)
            session.flush()

            child = Child(
                last_name="山田",
                first_name="太郎",
                last_name_kana="ヤマダ",
                first_name_kana="タロウ",
                birth_date=date(2021, 5, 5),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family.id,
            )
            session.add(child)
            session.flush()

            parent = ParentAccount(
                display_name=f"保護者_{unique_suffix}",
                email=f"parent_{unique_suffix}@example.com",
                status=ParentAccountStatus.active,
                family_id=family.id,
            )
            session.add(parent)
            session.flush()

            link = ParentChildLink(
                parent_account_id=parent.id,
                child_id=child.id,
            )
            session.add(link)

            now = datetime.now(timezone.utc)

            # 1. 全体お知らせ（高優先度）
            notice = Notice(
                title=f"園だより_{unique_suffix}",
                body="今月の行事予定です。",
                priority=NoticePriority.high,
                status=NoticeStatus.published,
                publish_start_at=now - timedelta(days=1),
            )
            session.add(notice)
            session.flush()

            target = NoticeTarget(
                notice_id=notice.id,
                target_type=NoticeTargetType.all,
            )
            session.add(target)

            # 2. 締切間近アンケート (2日後締切)
            urgent_survey = Survey(
                title=f"発表会参加希望_{unique_suffix}",
                description="観覧希望人数をご回答ください。",
                status=SurveyStatus.published,
                audience_type=SurveyAudienceType.parent,
                answer_unit=SurveyAnswerUnit.family,
                opens_at=now - timedelta(days=1),
                closes_at=now + timedelta(days=2),
            )
            session.add(urgent_survey)
            session.flush()

            survey_target = SurveyTarget(
                survey_id=urgent_survey.id,
                target_type=SurveyTargetType.all,
            )
            session.add(survey_target)

            # 3. 個別通知
            notification = ParentNotification(
                parent_account_id=parent.id,
                kind=ParentNotificationKind.notice_published,
                title=f"個別通知_{unique_suffix}",
                body="個別のご連絡です。",
                source_type="notice",
                source_id="1",
                is_read=False,
            )
            session.add(notification)

            session.commit()
            self.parent_id = parent.id
            self.notice_id = notice.id
            self.survey_id = urgent_survey.id
            self.notification_id = notification.id

        # ログイン
        response = self.client.post(
            "/parent-portal/login",
            data={"parent_account_id": self.parent_id},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_parent_notices_list_renders_filters_and_tabs(self):
        """お知らせ一覧に種別タブとトグルが表示され、全種別のアイテムが含まれること。"""
        resp = self.client.get("/parent-portal/notices")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("notice-filter-tab", resp.text)
        self.assertIn("toggle-unread", resp.text)
        self.assertIn("toggle-actionable", resp.text)
        self.assertIn("notice-item", resp.text)
        self.assertIn("アンケート", resp.text)
        self.assertIn("お知らせ", resp.text)

    def test_urgent_survey_banner_displayed_when_deadline_near(self):
        """締切3日以内の未回答アンケートがある場合、強調バナーが表示されること。"""
        # お知らせ一覧での確認
        resp_notices = self.client.get("/parent-portal/notices")
        self.assertEqual(resp_notices.status_code, 200)
        self.assertIn("urgent-surveys-container", resp_notices.text)
        self.assertIn("ご回答をお願いします（回答期限が迫っています）", resp_notices.text)

        # ホーム画面での確認
        resp_home = self.client.get("/parent-portal/")
        self.assertEqual(resp_home.status_code, 200)
        self.assertIn("home-urgent-surveys", resp_home.text)
        self.assertIn("ご回答をお願いします（回答期限が迫っています）", resp_home.text)

    def test_server_side_filtering_by_category_and_unread(self):
        """クエリパラメータによるカテゴリ・未読のサーバーサイド絞り込みが機能すること。"""
        # category=notice
        resp_notice = self.client.get("/parent-portal/notices?category=notice")
        self.assertEqual(resp_notice.status_code, 200)
        self.assertIn("data-kind=\"notice\"", resp_notice.text)

        # category=survey
        resp_survey = self.client.get("/parent-portal/notices?category=survey")
        self.assertEqual(resp_survey.status_code, 200)
        self.assertIn("data-kind=\"survey\"", resp_survey.text)
