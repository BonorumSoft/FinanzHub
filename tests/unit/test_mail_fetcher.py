"""Tests für app.inbox.mail_fetcher (Mock-IMAP, kein echter Server)."""
from __future__ import annotations

import email
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

import pytest

from app.config_loader import InboxConfig
from app.inbox.mail_fetcher import IncomingMail, MailFetcher

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_raw_mail(
    sender: str = "alice@example.com",
    subject: str = "Beleg",
    attachments: list[tuple[str, str, bytes]] | None = None,
) -> bytes:
    """Baut eine RFC822-Mail mit Text-Body und Anhängen."""
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = "belege@finanzhub.local"
    msg["Subject"] = subject
    msg.attach(MIMEText("Bitte verarbeiten.", "plain"))
    for filename, mimetype, data in attachments or []:
        maintype, subtype = mimetype.split("/", 1)
        if maintype == "image":
            part = MIMEImage(data, subtype, name=filename)
        elif maintype == "application":
            part = MIMEApplication(data, subtype, name=filename)
        else:
            continue
        msg.attach(part)
    return msg.as_bytes()


@pytest.fixture()
def cfg() -> InboxConfig:
    c = InboxConfig()
    c.accepted_mimetypes = ["image/jpeg", "application/pdf"]
    c.allowed_senders = ["alice@example.com"]
    return c


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_is_allowed_sender_strict(cfg):
    f = MailFetcher(cfg)
    assert f._is_allowed_sender("Alice <alice@example.com>") is True
    assert f._is_allowed_sender("Bob <bob@example.com>") is False


def test_is_allowed_sender_empty_whitelist_accepts_all():
    cfg = InboxConfig()
    cfg.allowed_senders = []
    f = MailFetcher(cfg)
    assert f._is_allowed_sender("anyone@anywhere.com") is True


def test_extract_attachments_filters_unknown_mime(cfg):
    f = MailFetcher(cfg)
    raw = _build_raw_mail(attachments=[
        ("bon.jpg", "image/jpeg", b"\xff\xd8\xff\xe0fake-jpeg"),
        ("doc.pdf", "application/pdf", b"%PDF-1.4 fake"),
        ("virus.exe", "application/x-msdownload", b"x"),
    ])
    msg = email.message_from_bytes(raw)
    attachments = f._extract_attachments(msg)
    names = [a.filename for a in attachments]
    assert "bon.jpg" in names
    assert "doc.pdf" in names
    assert "virus.exe" not in names


def test_extract_attachments_empty_when_no_attachments(cfg):
    f = MailFetcher(cfg)
    raw = _build_raw_mail(attachments=[])
    msg = email.message_from_bytes(raw)
    attachments = f._extract_attachments(msg)
    assert attachments == []


def test_fetch_new_handles_connection_error_gracefully(cfg, mocker, caplog):
    """IMAP nicht erreichbar → leere Liste, WARNING, kein Crash."""
    import logging

    class FakeIMAP:
        def __init__(self, *a, **kw):
            raise ConnectionError("IMAP offline")

    mocker.patch("imaplib.IMAP4_SSL", FakeIMAP)
    mocker.patch("imaplib.IMAP4", FakeIMAP)
    fetcher = MailFetcher(cfg)
    with caplog.at_level(logging.WARNING, logger="app.inbox.mail_fetcher"):
        result = fetcher.fetch_new()
    assert result == []


def test_close_is_safe_to_call_multiple_times(cfg):
    fetcher = MailFetcher(cfg)
    fetcher.close()
    fetcher.close()  # kein Fehler


def test_incoming_mail_dataclass():
    from datetime import datetime, timezone
    m = IncomingMail(uid="1", sender="a@b.c", subject="x",
                     received_at=datetime.now(timezone.utc))
    assert m.uid == "1"
    assert m.attachments == []
