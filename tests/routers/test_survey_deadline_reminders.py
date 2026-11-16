"""アンケート期限リマインダー (P6-2) のテスト。"""

from __future__ import annotations

import unittest
from datetime import date, datetime, timedelta, timezone
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
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentNotificationKind,
    Survey,
    SurveyAnswer,
    SurveyAnswerUnit,
    SurveyAudienceType,
    SurveyQuestion,
    QuestionType,
    SurveyStatus,
    SurveyTarget,
    SurveyTargetType,
    User,
)
from notification_hub import send_survey_deadline_reminders
import routers.surveys as surveys_module
from testing_helpers import configure_test_environment


class SurveyDeadlineReminderTests(unittest.TestCase):
    def setUp(self):
        configure_test_environment()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(surveys_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[surveys_module.get_session] = override_get_session
        self.app.dependency_overrides[surveys_module.get_current_staff_user] = (
            lambda: StaffUser(
                role=Role.CAN_EDIT,
                name="アンケート担当",
            )
        )

        self.client = TestClient(self.app)
        unique_suffix = uuid4().hex[:8]
        now = datetime.now(timezone.utc)

        with Session(self.engine) as session:
            classroom = Classroom(name=f"たんぽぽ_{unique_suffix}組", display_order=1)
            session.add(classroom)
            session.flush()

            # 家族A (未回答)
            family_a = Family(
                family_name=f"山田家_{unique_suffix}",
                home_address="東京都品川区1-1",
            )
            session.add(family_a)
            session.flush()

            child_a = Child(
                last_name="山田",
                first_name="太郎",
                last_name_kana="ヤマダ",
                first_name_kana="タロウ",
                birth_date=date(2022, 4, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family_a.id,
            )
            session.add(child_a)
            session.flush()

            parent_a = ParentAccount(
                display_name=f"山田保護者_{unique_suffix}",
                email=f"parent_a_{unique_suffix}@example.com",
                status=ParentAccountStatus.active,
                family_id=family_a.id,
            )
            session.add(parent_a)
            session.flush()

            session.add(ParentChildLink(parent_account_id=parent_a.id, child_id=child_a.id))

            # 家族B (回答済み)
            family_b = Family(
                family_name=f"佐藤家_{unique_suffix}",
                home_address="東京都品川区2-2",
            )
            session.add(family_b)
            session.flush()

            child_b = Child(
                last_name="佐藤",
                first_name="次郎",
                last_name_kana="サトウ",
                first_name_kana="ジロウ",
                birth_date=date(2022, 5, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family_b.id,
            )
            session.add(child_b)
            session.flush()

            parent_b = ParentAccount(
                display_name=f"佐藤保護者_{unique_suffix}",
                email=f"parent_b_{unique_suffix}@example.com",
                status=ParentAccountStatus.active,
                family_id=family_b.id,
            )
            session.add(parent_b)
            session.flush()

            session.add(ParentChildLink(parent_account_id=parent_b.id, child_id=child_b.id))

            # アンケート（締切18時間後、全家庭対象）
            survey = Survey(
                title=f"行事参加アンケート_{unique_suffix}",
                description="参加人数を教えてください。",
                audience_type=SurveyAudienceType.parent,
                answer_unit=SurveyAnswerUnit.family,
                status=SurveyStatus.published,
                opens_at=now - timedelta(days=2),
                closes_at=now + timedelta(hours=18),
            )
            session.add(survey)
            session.flush()

            session.add(SurveyTarget(survey_id=survey.id, target_type=SurveyTargetType.all))
            session.add(SurveyQuestion(
                survey_id=survey.id,
                label="参加しますか？",
                question_type=QuestionType.text_short,
                display_order=1,
            ))

            # 家族Bの回答を登録
            answer_b = SurveyAnswer(
                survey_id=survey.id,
                family_id=family_b.id,
                answered_by_parent_account_id=parent_b.id,
            )
            session.add(answer_b)

            session.commit()
            self.survey_id = survey.id
            self.parent_a_id = parent_a.id
            self.parent_b_id = parent_b.id

    def test_send_reminders_only_to_unanswered_parents(self):
        """締切前日の未回答保護者のみにリマインダーが送信され、回答済みには送信されないこと。"""
        with Session(self.engine) as session:
            notifs = send_survey_deadline_reminders(session, threshold_hours=24)
            session.commit()

            self.assertEqual(len(notifs), 1)
            n = notifs[0]
            self.assertEqual(n.parent_account_id, self.parent_a_id)
            self.assertEqual(n.source_type, "survey_reminder")
            self.assertEqual(n.source_id, str(self.survey_id))
            self.assertIn("締切間近", n.title)

    def test_duplicate_prevention(self):
        """2回目以降の実行ではリマインダーが重複送信されないこと。"""
        with Session(self.engine) as session:
            first_run = send_survey_deadline_reminders(session, threshold_hours=24)
            session.commit()
            self.assertEqual(len(first_run), 1)

            second_run = send_survey_deadline_reminders(session, threshold_hours=24)
            session.commit()
            self.assertEqual(len(second_run), 0)

    def test_trigger_reminders_api_endpoint(self):
        """APIエンドポイント /surveys/trigger-reminders が正常に呼び出せること。"""
        resp = self.client.post("/surveys/trigger-reminders?hours=24")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["sent_count"], 1)
