"""Mail-Service: kapselt SMTP, TLS, Test-Modus und Retry-Logik.

Bei SMTP-Fehlern wird ``ERROR`` geloggt, der Fehler in
``notification_log`` eingetragen, und es wird kein Absturz ausgelöst.
"""

from __future__ import annotations

import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid

from app.config_loader import MailConfig
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MailResult:
    success: bool
    recipients: list[str]
    subject: str
    error_message: str | None = None
    attempts: int = 1
    message_id: str | None = None


class MailService:
    """SMTP-Wrapper mit TLS-Pflicht, Test-Modus und Retry."""

    def __init__(self, config: MailConfig) -> None:
        self.config = config

    def _build_recipients(self, to_addresses: list[str]) -> list[str]:
        if self.config.test_mode and self.config.test_recipient:
            return [self.config.test_recipient]
        return to_addresses

    def send(
        self,
        subject: str,
        html_body: str,
        text_body: str,
        to_addresses: list[str],
        cc: list[str] | None = None,
        attachments: list[tuple[str, bytes, str]] | None = None,
    ) -> MailResult:
        """Versendet eine Mail. Bei temporärem SMTP-Fehler 2× Retry."""
        recipients = self._build_recipients(to_addresses)
        if not recipients:
            return MailResult(False, [], subject, "Keine Empfänger konfiguriert")

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.config.from_address
        msg["To"] = ", ".join(recipients)
        if cc:
            msg["Cc"] = ", ".join(cc)
        msg_id = make_msgid(domain=self.config.from_address.split("@")[-1])
        msg["Message-ID"] = msg_id
        msg.set_content(text_body or "FinanzHub Nachricht (HTML-Version anzeigen)")
        msg.add_alternative(html_body, subtype="html")

        for name, data, mime in attachments or []:
            msg.add_attachment(data, maintype=mime.split("/")[0], subtype=mime.split("/")[1], filename=name)

        attempts = 0
        last_err: Exception | None = None
        for attempt in range(1, 3):  # 2 Versuche
            attempts = attempt
            try:
                self._smtp_send(msg, recipients + (cc or []))
                return MailResult(
                    success=True,
                    recipients=recipients,
                    subject=subject,
                    attempts=attempts,
                    message_id=msg_id,
                )
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError) as err:
                last_err = err
                logger.warning("SMTP temporärer Fehler (Versuch %d): %s", attempt, err)
                time.sleep(2**attempt)
            except (smtplib.SMTPException, ssl.SSLError, OSError) as err:
                last_err = err
                logger.error("SMTP-Fehler: %s", err)
                break
        return MailResult(
            success=False,
            recipients=recipients,
            subject=subject,
            error_message=str(last_err) if last_err else "Unbekannter Fehler",
            attempts=attempts,
        )

    def _smtp_send(self, msg: EmailMessage, recipients: list[str]) -> None:
        if self.config.use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(self.config.host, self.config.port, timeout=self.config.timeout) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                if self.config.username:
                    smtp.login(self.config.username, self.config.password)
                smtp.send_message(msg, to_addrs=recipients)
        else:
            with smtplib.SMTP(self.config.host, self.config.port, timeout=self.config.timeout) as smtp:
                if self.config.username:
                    smtp.login(self.config.username, self.config.password)
                smtp.send_message(msg, to_addrs=recipients)


__all__ = ["MailResult", "MailService"]
