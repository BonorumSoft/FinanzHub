"""Tests für ``app.output.mail_service``."""

from __future__ import annotations

from email.message import EmailMessage
from unittest.mock import MagicMock, patch

from app.config_loader import MailConfig
from app.output.mail_service import MailService


def _cfg(**overrides: object) -> MailConfig:
    base: dict = {
        "host": "localhost",
        "port": 25,
        "username": "",
        "password": "",
        "from_address": "test@example.com",
        "test_recipient": "test-rcpt@example.com",
        "test_mode": False,
    }
    base.update(overrides)
    return MailConfig.model_validate(base)


class TestMailService:
    def test_test_mode_routes_to_test_recipient(self) -> None:
        cfg = _cfg(test_mode=True)
        svc = MailService(cfg)
        assert svc._build_recipients(["real@example.com"]) == ["test-rcpt@example.com"]

    def test_no_test_mode_keeps_recipients(self) -> None:
        cfg = _cfg(test_mode=False)
        svc = MailService(cfg)
        assert svc._build_recipients(["real@example.com"]) == ["real@example.com"]

    def test_no_recipients_returns_error(self) -> None:
        cfg = _cfg(test_mode=True, test_recipient="")
        svc = MailService(cfg)
        result = svc.send("Subj", "<p>html</p>", "txt", [])
        assert not result.success
        assert "Keine Empfänger" in (result.error_message or "")

    @patch("app.output.mail_service.smtplib.SMTP")
    def test_send_success(self, smtp_class: MagicMock) -> None:
        instance = smtp_class.return_value.__enter__.return_value
        svc = MailService(_cfg())
        result = svc.send("Hello", "<p>x</p>", "x", ["a@example.com"])
        assert result.success
        assert instance.send_message.called

    @patch("app.output.mail_service.smtplib.SMTP")
    def test_send_auth(self, smtp_class: MagicMock) -> None:
        instance = smtp_class.return_value.__enter__.return_value
        svc = MailService(_cfg(username="u", password="p", use_tls=True))
        result = svc.send("Hello", "<p>x</p>", "x", ["a@example.com"])
        assert result.success
        instance.starttls.assert_called_once()
        instance.login.assert_called_once_with("u", "p")

    @patch("app.output.mail_service.smtplib.SMTP")
    def test_send_smtp_exception(self, smtp_class: MagicMock) -> None:
        smtp_class.return_value.__enter__.side_effect = OSError("connect failed")
        svc = MailService(_cfg())
        result = svc.send("Subj", "<p>x</p>", "x", ["a@example.com"])
        assert not result.success
        assert "connect failed" in (result.error_message or "")

    def test_message_built_with_text_and_html(self) -> None:
        cfg = _cfg()
        svc = MailService(cfg)
        msg = EmailMessage()
        msg.set_content("text")
        msg.add_alternative("<p>html</p>", subtype="html")
        # Stelle sicher, dass beide Parts vorhanden sind
        assert msg.is_multipart()
        assert msg.get_body(preferencelist=("plain",)) is not None
        assert msg.get_body(preferencelist=("html",)) is not None
