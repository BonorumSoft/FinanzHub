"""End-to-end Tests für app.inbox.inbox_engine (mit Mocks)."""
from __future__ import annotations

import io
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PIL import Image
from sqlalchemy import text

from app.config_loader import InboxConfig
from app.data.db import apply_migrations, build_engine
from app.inbox.inbox_engine import InboxEngine
from app.inbox.mail_fetcher import Attachment, IncomingMail
from app.inbox.receipt_extractor import ExtractedReceipt

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


def _make_jpeg() -> bytes:
    img = Image.new("RGB", (40, 30), color="white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@pytest.fixture()
def db_engine(tmp_path):
    eng = build_engine(f"sqlite:///{tmp_path}/test.db")
    apply_migrations(eng, migrations_dir="migrations")
    yield eng
    eng.dispose()


@pytest.fixture()
def inbox_config(tmp_path) -> InboxConfig:
    cfg = InboxConfig()
    cfg.enabled = True
    cfg.storage_path = str(tmp_path / "receipts")
    cfg.accepted_mimetypes = ["image/jpeg", "application/pdf"]
    cfg.allowed_senders = ["allowed@example.com"]
    return cfg


def _make_mail(uid: str = "1", sender: str = "allowed@example.com", n_attachments: int = 1) -> IncomingMail:
    return IncomingMail(
        uid=uid,
        sender=sender,
        subject="Beleg von REWE",
        received_at=datetime.now(timezone.utc),
        attachments=[
            Attachment(filename=f"bon{i}.jpg", mimetype="image/jpeg", data=_make_jpeg())
            for i in range(n_attachments)
        ],
    )


def _fake_extracted(amount: float = 47.90, d: str = "2026-06-04", merchant: str = "REWE") -> ExtractedReceipt:
    return ExtractedReceipt(
        date=d, amount=amount, currency="EUR", merchant=merchant,
        category="Lebensmittel", is_invoice=False, is_payment_proof=False,
        confidence=0.92, model="mock",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_full_flow_with_demo_image(db_engine, inbox_config, mocker, tmp_path):
    """Bild → Konvertierung → Mock-Extractor → DB-Eintrag."""
    # Mock MailFetcher → 1 Mail mit 1 Anhang
    mail = _make_mail()
    fetcher_mock = MagicMock()
    fetcher_mock.fetch_new.return_value = [mail]
    fetcher_mock.mark_processed = MagicMock()
    # Mock Extractor
    ext_mock = MagicMock()
    ext_mock.extract.return_value = _fake_extracted()
    engine = InboxEngine(
        inbox_config, db_engine,
        mail_fetcher=fetcher_mock,
        receipt_extractor=ext_mock,
    )
    result = engine.process_inbox()
    assert result.mails_processed == 1
    assert result.attachments_processed == 1
    assert result.receipts_extracted == 1
    # DB-Eintrag prüfen
    with db_engine.begin() as conn:
        rows = conn.execute(text("SELECT * FROM receipts")).fetchall()
    assert len(rows) == 1
    rec = dict(rows[0]._mapping)
    assert rec["extracted_merchant"] == "REWE"
    assert rec["status"] in {"extracted", "matched", "manual_review", "no_match"}
    assert rec["original_mimetype"] == "image/jpeg"
    fetcher_mock.mark_processed.assert_called_once_with(mail.uid)


def test_unknown_sender_mail_ignored(db_engine, inbox_config, mocker):
    """Mail von nicht-whitelisted Sender wird ignoriert."""
    mail = IncomingMail(
        uid="x", sender="spam@evil.com", subject="hi",
        received_at=datetime.now(timezone.utc),
        attachments=[Attachment(filename="a.jpg", mimetype="image/jpeg", data=_make_jpeg())],
    )
    fetcher_mock = MagicMock()
    fetcher_mock.fetch_new.return_value = [mail]
    fetcher_mock.mark_processed = MagicMock()
    ext_mock = MagicMock()
    ext_mock.extract.return_value = _fake_extracted()
    engine = InboxEngine(
        inbox_config, db_engine,
        mail_fetcher=fetcher_mock,
        receipt_extractor=ext_mock,
    )
    result = engine.process_inbox()
    assert result.mails_processed == 1
    assert result.attachments_processed == 0
    # KEIN DB-Eintrag (oder einer mit status=error, je nach Whitelist-Verhalten)
    with db_engine.begin() as conn:
        rows = conn.execute(text("SELECT * FROM receipts")).fetchall()
    assert len(rows) == 0  # unknown sender → keine Persistierung


def test_extraction_failure_sets_error_status(db_engine, inbox_config):
    """Bei KI-Fehler: status='error', kein Crash, Mail trotzdem als verarbeitet markiert."""
    fetcher_mock = MagicMock()
    fetcher_mock.fetch_new.return_value = [_make_mail()]
    fetcher_mock.mark_processed = MagicMock()
    ext_mock = MagicMock()
    ext_mock.extract.side_effect = RuntimeError("KI explodiert")
    engine = InboxEngine(
        inbox_config, db_engine,
        mail_fetcher=fetcher_mock,
        receipt_extractor=ext_mock,
    )
    result = engine.process_inbox()
    assert result.receipts_failed >= 1
    with db_engine.begin() as conn:
        rows = conn.execute(text("SELECT * FROM receipts")).fetchall()
    assert any(r._mapping["status"] == "error" for r in rows)
    fetcher_mock.mark_processed.assert_called_once()


def test_double_processing_idempotent(db_engine, inbox_config):
    """Gleiche Mail zweimal → unabhängige Verarbeitung (kein unique-constraint nötig)."""
    mail = _make_mail(uid="dup")
    fetcher_mock = MagicMock()
    fetcher_mock.fetch_new.return_value = [mail]
    fetcher_mock.mark_processed = MagicMock()
    ext_mock = MagicMock()
    ext_mock.extract.return_value = _fake_extracted()
    engine = InboxEngine(
        inbox_config, db_engine,
        mail_fetcher=fetcher_mock,
        receipt_extractor=ext_mock,
    )
    engine.process_inbox()
    engine.process_inbox()
    with db_engine.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM receipts")).scalar()
    # Beide Läufe persistieren (kein hash-basierter Dedup auf Mail-Ebene;
    # wird bewusst nicht erzwungen, da Mail-UID sich nach Löschung wiederholen kann)
    assert n == 2


def test_inbox_disabled_returns_empty(inbox_config, db_engine):
    inbox_config.enabled = False
    fetcher_mock = MagicMock()
    fetcher_mock.fetch_new.return_value = [_make_mail()]
    engine = InboxEngine(
        inbox_config, db_engine,
        mail_fetcher=fetcher_mock,
    )
    result = engine.process_inbox()
    assert result.mails_processed == 0
    fetcher_mock.fetch_new.assert_not_called()


def test_match_linked_in_receipts(db_engine, inbox_config):
    """Extractor liefert Daten → Matcher findet TX → receipt.matched_transaction_id gesetzt."""
    # TX anlegen (SQLite akzeptiert kein Decimal — zu float konvertieren)
    with db_engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO transactions (transaction_id, account_id, booking_date, amount, description, counterparty_name) "
            "VALUES (:tid, :acc, :d, :a, :p, :c)"
        ), {
            "tid": "TX-99", "acc": "ACC-1", "d": date(2026, 6, 4),
            "a": float(Decimal("-47.90")), "p": "REWE STUHR 1234", "c": "REWE",
        })
    fetcher_mock = MagicMock()
    fetcher_mock.fetch_new.return_value = [_make_mail()]
    fetcher_mock.mark_processed = MagicMock()
    ext_mock = MagicMock()
    ext_mock.extract.return_value = _fake_extracted(amount=47.90, d="2026-06-04", merchant="REWE")
    engine = InboxEngine(
        inbox_config, db_engine,
        mail_fetcher=fetcher_mock,
        receipt_extractor=ext_mock,
    )
    result = engine.process_inbox()
    assert result.receipts_matched == 1
    with db_engine.begin() as conn:
        rec = dict(conn.execute(text("SELECT * FROM receipts LIMIT 1")).fetchone()._mapping)
    assert rec["matched_transaction_id"] == "TX-99"
    assert rec["status"] == "matched"
    assert rec["match_confidence"] >= 0.85


def test_pdf_attachment_direct(db_engine, inbox_config):
    """PDF-Anhang wird direkt verarbeitet, ohne Bild-Konvertierung."""
    pdf_bytes = b"%PDF-1.4\n%%EOF\n"
    mail = IncomingMail(
        uid="p", sender="allowed@example.com", subject="Rechnung",
        received_at=datetime.now(timezone.utc),
        attachments=[Attachment(filename="r.pdf", mimetype="application/pdf", data=pdf_bytes)],
    )
    fetcher_mock = MagicMock()
    fetcher_mock.fetch_new.return_value = [mail]
    fetcher_mock.mark_processed = MagicMock()
    ext_mock = MagicMock()
    ext_mock.extract.return_value = _fake_extracted()
    engine = InboxEngine(
        inbox_config, db_engine,
        mail_fetcher=fetcher_mock,
        receipt_extractor=ext_mock,
    )
    result = engine.process_inbox()
    assert result.attachments_processed == 1


def test_test_extraction_returns_only_receipt(db_engine, inbox_config, mocker, tmp_path):
    """test_extraction persistiert NICHTS in der DB."""
    cfg = InboxConfig()
    cfg.storage_path = str(tmp_path / "test_receipts")
    cfg.extraction.provider = "local_lm_studio"
    ext_mock = MagicMock()
    ext_mock.extract.return_value = _fake_extracted(amount=10.0)
    img_path = tmp_path / "bon.jpg"
    img_path.write_bytes(_make_jpeg())
    engine = InboxEngine(cfg, db_engine, receipt_extractor=ext_mock)
    out = engine.test_extraction(img_path)
    assert out.merchant == "REWE"
    # Kein DB-Eintrag
    with db_engine.begin() as conn:
        n = conn.execute(text("SELECT count(*) FROM receipts")).scalar()
    assert n == 0


def test_extraction_with_low_confidence_manual_review(db_engine, inbox_config):
    """confidence < min_confidence_for_match → status=manual_review."""
    fetcher_mock = MagicMock()
    fetcher_mock.fetch_new.return_value = [_make_mail()]
    fetcher_mock.mark_processed = MagicMock()
    low_conf = _fake_extracted()
    low_conf.confidence = 0.40  # unter 0.75
    ext_mock = MagicMock()
    ext_mock.extract.return_value = low_conf
    engine = InboxEngine(
        inbox_config, db_engine,
        mail_fetcher=fetcher_mock,
        receipt_extractor=ext_mock,
    )
    engine.process_inbox()
    with db_engine.begin() as conn:
        rec = dict(conn.execute(text("SELECT * FROM receipts LIMIT 1")).fetchone()._mapping)
    assert rec["status"] == "manual_review"


def test_receipt_tags_table_exists(db_engine):
    """receipt_tags-Tabelle wird via Migration angelegt."""
    with db_engine.begin() as conn:
        rows = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='receipt_tags'"
        )).fetchall()
    assert len(rows) == 1
