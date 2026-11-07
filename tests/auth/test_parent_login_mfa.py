import re
from datetime import timedelta

import pytest
from sqlmodel import Session, select

from local_auth import ACTION_CODE_ALPHABET
from models import (
    AuthSession,
    CredentialActionToken,
    ParentAccount,
    ParentMfaPending,
)
import routers.parent_auth as routes
from routers.parent_auth import (
    PARENT_LOGIN_RATE_LIMITER_ACCOUNT,
    PARENT_LOGIN_RATE_LIMITER_IP,
    PARENT_MFA_PENDING_COOKIE,
    PARENT_MFA_SEND_RATE_LIMITER,
    PARENT_MFA_VERIFY_RATE_LIMITER,
)
from test_guardian_account_sync import pilot as pilot_fixture
from tests.auth.test_parent_code_mail import active_account
from time_utils import utc_now

CODE_RE = re.compile(rf"[{re.escape(ACTION_CODE_ALPHABET)}]{{6}}")


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


@pytest.fixture(autouse=True)
def _reset_rate_limiters():
    """テスト間で共有されるレート制限状態をリセットし、順序依存を防ぐ。"""
    PARENT_LOGIN_RATE_LIMITER_IP.reset_all()
    PARENT_LOGIN_RATE_LIMITER_ACCOUNT.reset_all()
    PARENT_MFA_SEND_RATE_LIMITER.reset_all()
    PARENT_MFA_VERIFY_RATE_LIMITER.reset_all()
    yield


def _capture_send_auth_mail(monkeypatch):
    captured = []
    monkeypatch.setattr(
        routes, "send_auth_mail", lambda **kw: captured.append(kw.get("body", ""))
    )
    return captured


def _complete_mfa(client, captured, *, redirect_to="/parent-portal/"):
    assert captured, "MFA verification email was not sent"
    match = CODE_RE.search(captured[-1])
    assert match, f"verification code not found in mail body: {captured[-1]!r}"
    return client.post(
        "/parent-portal/mfa/verify",
        data={"code": match.group(0), "redirect_to": redirect_to},
        follow_redirects=False,
    )


def test_login_password_then_mfa_redirects_and_issues_session(pilot, monkeypatch):
    client, engine, ids, _ = pilot
    account_id = active_account(pilot)
    captured = _capture_send_auth_mail(monkeypatch)

    response = client.post(
        "/parent-portal/login",
        data={"login_id": "parent@example.test", "password": "River!7892Long-Phrase"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/parent-portal/mfa/verify"
    # Password alone must not issue a usable session (pre-MFA session is revoked)
    assert client.cookies.get("hoikuict_parent_session") is None
    with Session(engine) as session:
        account = session.get(ParentAccount, account_id)
        active = session.exec(
            select(AuthSession).where(
                AuthSession.parent_account_id == account.id,
                AuthSession.revoked_at.is_(None),
            )
        ).all()
        assert active == []

    mfa_response = _complete_mfa(client, captured)
    assert mfa_response.status_code == 303
    assert mfa_response.headers["location"] == "/parent-portal/"
    assert client.cookies.get("hoikuict_parent_session") is not None

    # Portal is viewable and exactly one active session with mfa_satisfied_at remains
    assert client.get("/parent-portal/").status_code == 200
    with Session(engine) as session:
        sessions = session.exec(
            select(AuthSession).where(
                AuthSession.parent_account_id == account_id,
                AuthSession.revoked_at.is_(None),
            )
        ).all()
        assert len(sessions) == 1
        assert sessions[0].mfa_satisfied_at is not None

    with Session(engine) as session:
        account = session.get(ParentAccount, account_id)
        assert account.last_login_at is not None


def test_wrong_mfa_code_is_rejected_and_attempts_are_limited(pilot, monkeypatch):
    PARENT_MFA_VERIFY_RATE_LIMITER.reset_all()
    client, engine, ids, _ = pilot
    active_account(pilot)
    captured = _capture_send_auth_mail(monkeypatch)

    client.post(
        "/parent-portal/login",
        data={"login_id": "parent@example.test", "password": "River!7892Long-Phrase"},
        follow_redirects=False,
    )

    # Up to 5 wrong attempts; after that even the right code is rejected
    for _ in range(5):
        response = client.post(
            "/parent-portal/mfa/verify",
            data={"code": "111111", "redirect_to": "/parent-portal/"},
            follow_redirects=False,
        )
        assert response.status_code == 400

    # Reset the router-level verify limiter and check service-level attempt exhaustion
    PARENT_MFA_VERIFY_RATE_LIMITER.reset_all()
    response = client.post(
        "/parent-portal/mfa/verify",
        data={
            "code": CODE_RE.search(captured[-1]).group(0),
            "redirect_to": "/parent-portal/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert client.cookies.get("hoikuict_parent_session") is None


def test_mfa_verify_requires_pending_cookie(pilot, monkeypatch):
    client, engine, ids, _ = pilot
    active_account(pilot)
    _capture_send_auth_mail(monkeypatch)
    client.cookies.clear()

    response = client.post(
        "/parent-portal/mfa/verify",
        data={"code": "123456", "redirect_to": "/parent-portal/"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_case_insensitive_mfa_code(pilot, monkeypatch):
    client, engine, ids, _ = pilot
    active_account(pilot)
    captured = _capture_send_auth_mail(monkeypatch)

    client.post(
        "/parent-portal/login",
        data={"login_id": "parent@example.test", "password": "River!7892Long-Phrase"},
        follow_redirects=False,
    )

    match = CODE_RE.search(captured[-1])
    assert match is not None

    # メールに記載された大文字コードを小文字で入力しても成功する
    response = client.post(
        "/parent-portal/mfa/verify",
        data={"code": match.group(0).lower(), "redirect_to": "/parent-portal/"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert client.cookies.get("hoikuict_parent_session") is not None


def test_expired_mfa_pending_is_rejected(pilot, monkeypatch):
    client, engine, ids, _ = pilot
    active_account(pilot)
    captured = _capture_send_auth_mail(monkeypatch)
    client.post(
        "/parent-portal/login",
        data={"login_id": "parent@example.test", "password": "River!7892Long-Phrase"},
        follow_redirects=False,
    )

    with Session(engine) as session:
        pending_row = session.exec(select(ParentMfaPending)).one()
        pending_row.expires_at = utc_now() - timedelta(seconds=1)
        session.add(pending_row)
        session.commit()

    response = client.post(
        "/parent-portal/mfa/verify",
        data={
            "code": CODE_RE.search(captured[-1]).group(0),
            "redirect_to": "/parent-portal/",
        },
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_mfa_can_be_disabled_by_env(pilot, monkeypatch):
    monkeypatch.setenv("HOIKUICT_PARENT_LOGIN_MFA", "0")
    capture_sent = []
    monkeypatch.setattr(
        routes, "send_auth_mail", lambda **kw: capture_sent.append(kw.get("body", ""))
    )

    client, engine, ids, _ = pilot
    active_account(pilot)
    response = client.post(
        "/parent-portal/login",
        data={"login_id": "parent@example.test", "password": "River!7892Long-Phrase"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/parent-portal/"
    assert capture_sent == []
    assert client.cookies.get("hoikuict_parent_session") is not None


def test_relogin_invalidates_previous_pending(pilot, monkeypatch):
    client, engine, ids, _ = pilot
    active_account(pilot)
    _capture_send_auth_mail(monkeypatch)

    client.post(
        "/parent-portal/login",
        data={"login_id": "parent@example.test", "password": "River!7892Long-Phrase"},
        follow_redirects=False,
    )
    old_reference = client.cookies.get(PARENT_MFA_PENDING_COOKIE)
    assert old_reference is not None

    captured2 = []
    monkeypatch.setattr(
        routes, "send_auth_mail", lambda **kw: captured2.append(kw.get("body", ""))
    )
    client.post(
        "/parent-portal/login",
        data={"login_id": "parent@example.test", "password": "River!7892Long-Phrase"},
        follow_redirects=False,
    )
    new_reference = client.cookies.get(PARENT_MFA_PENDING_COOKIE)
    assert new_reference is not None
    assert new_reference != old_reference

    # 古い保留参照は削除済みなので検証に失敗する
    client.cookies.clear()
    client.cookies.set(PARENT_MFA_PENDING_COOKIE, old_reference)
    response = client.post(
        "/parent-portal/mfa/verify",
        data={"code": "111111", "redirect_to": "/parent-portal/"},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_credential_action_token_not_created_for_mfa(pilot, monkeypatch):
    client, engine, ids, _ = pilot
    active_account(pilot)
    _capture_send_auth_mail(monkeypatch)

    with Session(engine) as session:
        before = session.exec(
            select(CredentialActionToken).where(
                CredentialActionToken.action == "mfa_verify"
            )
        ).all()

    client.post(
        "/parent-portal/login",
        data={"login_id": "parent@example.test", "password": "River!7892Long-Phrase"},
        follow_redirects=False,
    )

    with Session(engine) as session:
        after = session.exec(
            select(CredentialActionToken).where(
                CredentialActionToken.action == "mfa_verify"
            )
        ).all()
    assert len(after) == len(before)


def test_smtp_failure_returns_503_and_removes_pending(pilot, monkeypatch):
    client, engine, ids, _ = pilot
    active_account(pilot)

    def boom(**kw):
        raise RuntimeError("smtp down")

    monkeypatch.setattr(routes, "send_auth_mail", boom)

    response = client.post(
        "/parent-portal/login",
        data={"login_id": "parent@example.test", "password": "River!7892Long-Phrase"},
        follow_redirects=False,
    )
    assert response.status_code == 503
    assert "送信に失敗しました" in response.text

    # 保留レコードは削除されている
    with Session(engine) as session:
        assert session.exec(select(ParentMfaPending)).all() == []
