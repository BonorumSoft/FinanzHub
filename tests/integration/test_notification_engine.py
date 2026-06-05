"""Integration-Test für die Notification-Engine (mit gemocktem SMTP)."""

from __future__ import annotations

from unittest.mock import patch

from app.config_loader import MailConfig, NotificationsConfig
from app.notifications.engine import NotificationEngine
from app.output.mail_service import MailService


def _mail_cfg() -> MailConfig:
    return MailConfig(
        host="localhost",
        port=25,
        username="",
        password="",
        from_address="test@example.com",
        test_recipient="recipient@example.com",
        test_mode=False,
    )


def _notif_cfg() -> NotificationsConfig:
    from app.config_loader import NotificationRule

    return NotificationsConfig(
        rules=[
            NotificationRule(
                id="daily_wealth_report",
                schedule="manual",
                template="daily_wealth_report",
                recipients=["real@example.com"],
            )
        ]
    )


class TestNotificationEngine:
    def test_send_test(self, db) -> None:
        ne = NotificationEngine(db, _notif_cfg(), MailService(_mail_cfg()), _mail_cfg())
        with patch("app.output.mail_service.smtplib.SMTP") as smtp:
            instance = smtp.return_value.__enter__.return_value
            result = ne.send_test("daily_wealth_report")
            assert result.success
            assert instance.send_message.called

    def test_unknown_notification_id(self, db) -> None:
        ne = NotificationEngine(db, _notif_cfg(), MailService(_mail_cfg()), _mail_cfg())
        result = ne.send_test("does_not_exist")
        assert not result.success

    def test_run_due_logs_to_db(self, db) -> None:
        from app.data.db import execute

        # Eine künstlich fällige Rule (schedule=daily) → daily_wealth_report
        cfg = _notif_cfg()
        cfg.rules[0].schedule = "daily"
        ne = NotificationEngine(db, cfg, MailService(_mail_cfg()), _mail_cfg())
        with patch("app.output.mail_service.smtplib.SMTP"):
            results = ne.run_due()
        assert len(results) == 1
        # notification_log wurde beschrieben
        rows = execute(db, "SELECT COUNT(*) AS n FROM notification_log")
        assert int(rows[0]["n"]) >= 1
