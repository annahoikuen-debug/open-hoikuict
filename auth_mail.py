"""SMTP transport shared by parent registration and staff account recovery."""

import os
import smtplib
import ssl
from email.message import EmailMessage


def send_auth_mail(*, recipient: str, subject: str, body: str) -> None:
    mail_from = os.getenv("HOIKUICT_PARENT_MAIL_FROM")
    if not mail_from:
        # テスト環境や開発環境で環境変数が未設定の場合は実際のSMTP送信をスキップする。
        # 本番運用では HOIKUICT_PARENT_MAIL_FROM の設定が必須。
        return
    message = EmailMessage()
    message["From"] = mail_from
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    smtp_host = os.getenv("HOIKUICT_SMTP_HOST")
    if not smtp_host:
        return
    with smtplib.SMTP(
        smtp_host,
        int(os.getenv("HOIKUICT_SMTP_PORT", "587")),
        timeout=20,
    ) as smtp:
        if os.getenv("HOIKUICT_SMTP_STARTTLS", "1") == "1":
            smtp.starttls(context=ssl.create_default_context())
        username = os.getenv("HOIKUICT_SMTP_USERNAME")
        if username:
            smtp.login(username, os.getenv("HOIKUICT_SMTP_PASSWORD") or "")
        smtp.send_message(message)
