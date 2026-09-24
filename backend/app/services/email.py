"""Outgoing email (magic links). Swappable like the AI providers."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import Settings

log = logging.getLogger("nudgy.email")


class EmailSender(Protocol):
    def send(self, to: str, subject: str, text: str) -> None: ...


class ConsoleEmail:
    """Development only: logs the message (including the link) instead of sending it."""

    def __init__(self):
        self.sent: list[tuple[str, str, str]] = []

    def send(self, to: str, subject: str, text: str) -> None:
        self.sent.append((to, subject, text))
        log.info("EMAIL to=%s subject=%s\n%s", to, subject, text)


class SmtpEmail:
    def __init__(self, s: Settings):
        self.s = s

    def send(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.s.email_from, to, subject
        msg.set_content(text)
        with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=15) as smtp:
            smtp.starttls()
            if self.s.smtp_user:
                smtp.login(self.s.smtp_user, self.s.smtp_password)
            smtp.send_message(msg)


_console = ConsoleEmail()


def get_email_sender(s: Settings) -> EmailSender:
    return SmtpEmail(s) if s.email_provider == "smtp" else _console
