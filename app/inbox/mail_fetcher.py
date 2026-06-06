"""IMAP-Poller für die Beleg-Inbox.

Holt ungelesene Mails mit Anhängen, filtert nach Whitelist und akzeptierten
MIME-Typen, liefert :class:`IncomingMail`-Objekte zurück. Verbindungsfehler
führen nur zu WARNINGs und leerer Liste — der Scheduler versucht es beim
nächsten Intervall erneut.
"""

from __future__ import annotations

import contextlib
import email
import imaplib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import Message
from email.utils import parsedate_to_datetime
from typing import Any

from app.config_loader import InboxConfig
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Attachment:
    """Ein Anhang aus einer Mail."""

    filename: str
    mimetype: str
    data: bytes


@dataclass
class IncomingMail:
    """Eine verarbeitete Mail mit Anhängen."""

    uid: str
    sender: str
    subject: str
    received_at: datetime
    attachments: list[Attachment] = field(default_factory=list)


class MailFetcher:
    """Pollt ein IMAP-Postfach auf neue Mails.

    Args:
        config: Vollständige :class:`InboxConfig`. Verbindungsdaten aus
            ``imap.username``/``imap.password``.
    """

    def __init__(self, config: InboxConfig) -> None:
        self._config = config
        self._conn: imaplib.IMAP4 | imaplib.IMAP4_SSL | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_new(self) -> list[IncomingMail]:
        """Verbindet zum IMAP-Server, holt ungelesene Mails.

        Returns:
            Liste :class:`IncomingMail`. Leere Liste bei Fehler oder leeren Postfach.

        Raises:
            Keine. Alle Exceptions werden gefangen und geloggt.
        """
        try:
            self._connect()
            if self._conn is None:
                return []
            self._select_folder()
            uids = self._search_unseen()
            mails: list[IncomingMail] = []
            for uid in uids:
                try:
                    mails.append(self._fetch_one(uid))
                except Exception as err:  # noqa: BLE001 — bewusst breit
                    logger.warning("Mail UID %s übersprungen: %s", uid, err)
            return mails
        except Exception as err:  # noqa: BLE001
            logger.warning("IMAP-Polling fehlgeschlagen: %s", err)
            self._safe_disconnect()
            return []

    def mark_processed(self, uid: str) -> None:
        """Markiert Mail als gelesen und verschiebt sie optional in Zielordner."""
        try:
            if self._conn is None:
                self._connect()
            if self._conn is None:
                return
            self._conn.store(uid, "+FLAGS", "\\Seen")
            target = self._config.imap.move_to_folder.strip()
            if target:
                self._conn.copy(uid, target)
                self._conn.store(uid, "+FLAGS", "\\Deleted")
                self._conn.expunge()
                logger.debug("Mail %s nach %s verschoben", uid, target)
        except Exception as err:  # noqa: BLE001
            logger.warning("Konnte Mail %s nicht als verarbeitet markieren: %s", uid, err)

    def close(self) -> None:
        """Schließt die IMAP-Verbindung explizit."""
        self._safe_disconnect()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._safe_disconnect()
        host = self._config.imap.host
        port = self._config.imap.port
        if self._config.imap.use_ssl:
            self._conn = imaplib.IMAP4_SSL(host, port)
        else:
            self._conn = imaplib.IMAP4(host, port)
        assert self._conn is not None
        self._conn.login(self._config.imap.username, self._config.imap.password)
        logger.info("IMAP verbunden: %s:%d", host, port)

    def _safe_disconnect(self) -> None:
        if self._conn is None:
            return
        with contextlib.suppress(Exception):
            self._conn.logout()
        self._conn = None

    def _select_folder(self) -> None:
        assert self._conn is not None
        folder = self._config.imap.folder or "INBOX"
        self._conn.select(folder)

    def _search_unseen(self) -> list[str]:
        assert self._conn is not None
        typ, data = self._conn.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            return []
        return data[0].split()

    def _fetch_one(self, uid: bytes) -> IncomingMail:
        assert self._conn is not None
        typ, msg_data = self._conn.fetch(uid, "(RFC822)")
        if typ != "OK" or not msg_data or not msg_data[0]:
            raise RuntimeError(f"Kein Body für UID {uid!r}")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)
        sender = str(msg.get("From", "")) or "<unknown>"
        subject = str(msg.get("Subject", "")) or ""
        date_hdr = msg.get("Date")
        received = (
            parsedate_to_datetime(date_hdr).astimezone(timezone.utc)
            if date_hdr
            else datetime.now(timezone.utc)
        )
        if not self._is_allowed_sender(sender):
            logger.info("Absender ignoriert (nicht in Whitelist): %s", sender)
            return IncomingMail(
                uid=uid.decode() if isinstance(uid, bytes) else str(uid),
                sender=sender,
                subject=subject,
                received_at=received,
                attachments=[],
            )
        attachments = self._extract_attachments(msg)
        return IncomingMail(
            uid=uid.decode() if isinstance(uid, bytes) else str(uid),
            sender=sender,
            subject=subject,
            received_at=received,
            attachments=attachments,
        )

    def _is_allowed_sender(self, sender: str) -> bool:
        if not self._config.allowed_senders:
            return True
        sender_lower = sender.lower()
        return any(s.lower() in sender_lower for s in self._config.allowed_senders)

    def _extract_attachments(self, msg: Message) -> list[Attachment]:
        accepted = {m.lower() for m in self._config.accepted_mimetypes}
        out: list[Attachment] = []
        for part in msg.walk():
            if part.is_multipart():
                continue
            if part.get_content_disposition() == "inline":
                continue
            payload = part.get_payload(decode=True)
            if not payload:
                continue
            mimetype = (part.get_content_type() or "").lower()
            if mimetype not in accepted:
                logger.debug("Anhang übersprungen (MIME %s nicht akzeptiert)", mimetype)
                continue
            filename = part.get_filename() or f"attachment-{len(out)}"
            out.append(Attachment(filename=filename, mimetype=mimetype, data=payload))
        return out


__all__ = ["Attachment", "IncomingMail", "MailFetcher"]


# Helfer für Tests (defensiv, falls email-Parsing mal fehlschlägt)
def _safe_get(msg: Message, key: str) -> str:
    value: Any = msg.get(key)
    return str(value) if value is not None else ""
