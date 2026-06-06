"""Orchestrator: holt Mails, verarbeitet Anhänge, extrahiert, matched, persistiert."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config_loader import InboxConfig
from app.inbox.attachment_handler import AttachmentHandler
from app.inbox.image_converter import ImageConverter
from app.inbox.mail_fetcher import IncomingMail, MailFetcher
from app.inbox.receipt_extractor import ExtractedReceipt, ReceiptExtractor
from app.inbox.transaction_matcher import MatchResult, TransactionMatcher
from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Ergebnis-Datenmodell
# ---------------------------------------------------------------------------


@dataclass
class InboxRunResult:
    """Zusammenfassung eines Inbox-Laufs."""

    mails_processed: int = 0
    attachments_processed: int = 0
    receipts_extracted: int = 0
    receipts_matched: int = 0
    receipts_failed: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class InboxEngine:
    """Orchestriert den gesamten Beleg-Verarbeitungs-Workflow."""

    def __init__(
        self,
        config: InboxConfig,
        db_engine: Engine,
        mail_fetcher: MailFetcher | None = None,
        image_converter: ImageConverter | None = None,
        receipt_extractor: ReceiptExtractor | None = None,
        transaction_matcher: TransactionMatcher | None = None,
        attachment_handler: AttachmentHandler | None = None,
    ) -> None:
        self._config = config
        self._engine = db_engine
        self._fetcher = mail_fetcher or MailFetcher(config)
        self._image_converter = image_converter
        self._extractor = receipt_extractor or ReceiptExtractor(config.extraction)
        self._matcher = transaction_matcher or TransactionMatcher(
            db_engine, config.matching
        )
        self._handler = attachment_handler or AttachmentHandler(
            config,
            image_converter=self._image_converter or ImageConverter(),
            output_dir=Path(config.storage_path),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def process_inbox(self) -> InboxRunResult:
        """Hauptmethode (vom Scheduler aufgerufen)."""
        if not self._config.enabled:
            logger.debug("Inbox deaktiviert, überspringe")
            return InboxRunResult()

        result = InboxRunResult()
        try:
            mails = self._fetcher.fetch_new()
        except Exception as err:  # noqa: BLE001
            logger.warning("MailFetcher fehlgeschlagen: %s", err)
            return result

        for mail in mails:
            result.mails_processed += 1
            if not mail.attachments:
                self._fetcher.mark_processed(mail.uid)
                continue
            # Defensive whitelist-Check (falls MailFetcher umgangen wird)
            if not self._is_allowed_sender(mail.sender):
                logger.info("Engine: Absender ignoriert (nicht in Whitelist): %s", mail.sender)
                self._fetcher.mark_processed(mail.uid)
                continue
            for att in mail.attachments:
                outcome = self._process_attachment(mail, att)
                if outcome == "extracted":
                    result.attachments_processed += 1
                    result.receipts_extracted += 1
                elif outcome == "matched":
                    result.attachments_processed += 1
                    result.receipts_extracted += 1
                    result.receipts_matched += 1
                elif outcome == "failed":
                    result.receipts_failed += 1
                    result.errors.append(f"{att.filename}: siehe Logs")
            self._fetcher.mark_processed(mail.uid)
        return result

    def _is_allowed_sender(self, sender: str) -> bool:
        if not self._config.allowed_senders:
            return True
        s = sender.lower()
        return any(p.lower() in s for p in self._config.allowed_senders)

    def test_extraction(self, file_path: Path) -> ExtractedReceipt:
        """Nur Extraktion (ohne DB-Schreiben). Nützlich zum Testen."""
        if file_path.suffix.lower() in {".jpg", ".jpeg", ".png", ".heic", ".webp"}:
            converter = self._image_converter or ImageConverter()
            pdf_path = Path(self._config.storage_path) / f"test_{int(datetime.now().timestamp())}.pdf"
            converter.convert(file_path.read_bytes(), _guess_mime(file_path), pdf_path)
        else:
            pdf_path = file_path
        return self._extractor.extract(pdf_path)

    # ------------------------------------------------------------------
    # Intern
    # ------------------------------------------------------------------

    def _process_attachment(self, mail: IncomingMail, attachment: Any) -> str:
        """Verarbeitet einen einzelnen Anhang. Liefert 'extracted'|'matched'|'failed'|'skipped'."""
        # 1. Routing + ggf. Bild→PDF
        processed = self._handler.process(attachment)
        if processed.action == "skip" or processed.pdf_path is None:
            logger.info(
                "Anhang übersprungen: %s (%s)",
                attachment.filename,
                processed.error or "kein PDF-Pfad",
            )
            # Trotzdem als receipt mit status=error persistieren, damit Audit-Trail da ist
            if processed.error:
                self._persist_receipt_error(mail, attachment, processed.error)
            return "skipped"

        # 2. KI-Extraktion
        try:
            extracted = self._extractor.extract(processed.pdf_path)
        except Exception as err:  # noqa: BLE001
            logger.warning("Extraktion fehlgeschlagen für %s: %s", attachment.filename, err)
            self._persist_receipt_error(mail, attachment, f"Extraction: {err}")
            return "failed"

        # 3. Validierung: confidence zu niedrig → manual_review
        if extracted.confidence < self._config.extraction.min_confidence_for_match:
            status = "manual_review"
            match_result = MatchResult(None, 0.0, "no_match", 0)
        else:
            # 4. Matching gegen Transaktionen
            match_result = self._matcher.find_match(extracted)
            status = self._status_from_match(match_result)

        # 5. Persistieren
        receipt_id = self._persist_receipt(
            mail, attachment, processed.pdf_path, extracted, match_result, status
        )

        # 6. Bestätigungsmail (wenn aktiviert)
        if self._config.confirmation.enabled and receipt_id is not None:
            try:
                self._send_confirmation(mail, extracted, match_result, status)
            except Exception as err:  # noqa: BLE001
                logger.warning("Bestätigungsmail fehlgeschlagen: %s", err)

        return "matched" if match_result.transaction_id else "extracted"

    def _status_from_match(self, match: MatchResult) -> str:
        if match.confidence >= self._config.extraction.min_confidence_for_match and match.transaction_id:
            return "matched"
        if match.candidate_count == 0:
            return "no_match"
        return "manual_review"

    def _persist_receipt(
        self,
        mail: IncomingMail,
        attachment: Any,
        pdf_path: Path,
        extracted: ExtractedReceipt,
        match: MatchResult,
        status: str,
    ) -> int | None:
        try:
            payload = {
                "source_email": mail.sender,
                "source_subject": mail.subject,
                "received_at": mail.received_at,
                "original_filename": attachment.filename,
                "original_mimetype": attachment.mimetype,
                "original_size_bytes": len(attachment.data),
                "pdf_path": str(pdf_path),
                "pdf_stored_at": datetime.now(timezone.utc),
                **extracted.to_db_dict(),
                "matched_transaction_id": match.transaction_id,
                "match_confidence": match.confidence,
                "match_method": match.method,
                "matched_at": datetime.now(timezone.utc) if match.transaction_id else None,
                "status": status,
                "processed_at": datetime.now(timezone.utc),
            }
            cols = ", ".join(payload.keys())
            placeholders = ", ".join(f":{k}" for k in payload)
            sql = text(
                f"INSERT INTO receipts ({cols}) VALUES ({placeholders}) RETURNING id"
            )
            with self._engine.begin() as conn:
                row = conn.execute(sql, payload).fetchone()
            return int(row[0]) if row else None
        except Exception as err:  # noqa: BLE001
            logger.error("Persistierung fehlgeschlagen: %s", err)
            return None

    def _persist_receipt_error(
        self,
        mail: IncomingMail,
        attachment: Any,
        error_msg: str,
    ) -> int | None:
        try:
            payload = {
                "source_email": mail.sender,
                "source_subject": mail.subject,
                "received_at": mail.received_at,
                "original_filename": attachment.filename,
                "original_mimetype": attachment.mimetype,
                "original_size_bytes": len(attachment.data),
                "status": "error",
                "error_message": error_msg[:1000],
                "processed_at": datetime.now(timezone.utc),
            }
            cols = ", ".join(payload.keys())
            placeholders = ", ".join(f":{k}" for k in payload)
            sql = text(
                f"INSERT INTO receipts ({cols}) VALUES ({placeholders}) RETURNING id"
            )
            with self._engine.begin() as conn:
                row = conn.execute(sql, payload).fetchone()
            return int(row[0]) if row else None
        except Exception as err:  # noqa: BLE001
            logger.warning("Fehler-Persistierung fehlgeschlagen: %s", err)
            return None

    def _send_confirmation(
        self,
        mail: IncomingMail,
        extracted: ExtractedReceipt,
        match: MatchResult,
        status: str,
    ) -> None:
        """Versendet Bestätigungsmail. Verwendet SMTP aus mail.yaml falls konfiguriert.

        Bewusst einfach gehalten: nutzt ``smtplib`` direkt, um keine harte
        Abhängigkeit von :class:`MailService` zu schaffen (Inbox läuft
        unabhängig von der Scheduler-Mail-Pipeline).
        """
        if not self._config.confirmation.reply_to_sender:
            return
        host = os.environ.get("INBOX_SMTP_HOST") or os.environ.get("SMTP_HOST")
        if not host:
            logger.debug("Kein SMTP-Host konfiguriert, überspringe Bestätigung")
            return
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = f"Beleg verarbeitet ({status})"
        recipient = _extract_email_address(mail.sender)
        if recipient:
            msg["To"] = recipient
        from_addr = os.environ.get("INBOX_SMTP_FROM") or os.environ.get("SMTP_FROM", "finanzhub@localhost")
        msg["From"] = from_addr
        body = self._build_confirmation_body(extracted, match, status)
        msg.set_content(body)
        try:
            with smtplib.SMTP(host, int(os.environ.get("INBOX_SMTP_PORT", "587")), timeout=15) as s:
                s.starttls()
                user = os.environ.get("INBOX_SMTP_USER") or os.environ.get("SMTP_USER")
                pwd = os.environ.get("INBOX_SMTP_PASS") or os.environ.get("SMTP_PASSWORD")
                if user and pwd:
                    s.login(user, pwd)
                s.send_message(msg)
        except Exception as err:  # noqa: BLE001
            logger.warning("SMTP-Versand fehlgeschlagen: %s", err)

    @staticmethod
    def _build_confirmation_body(
        extracted: ExtractedReceipt, match: MatchResult, status: str
    ) -> str:
        lines = [
            "Beleg wurde verarbeitet.",
            "",
            f"Status: {status}",
            f"Konfidenz: {extracted.confidence:.0%}",
        ]
        if extracted.merchant:
            lines.append(f"Händler: {extracted.merchant}")
        if extracted.amount is not None:
            lines.append(f"Betrag: {extracted.amount:.2f} {extracted.currency}")
        if extracted.date:
            lines.append(f"Datum: {extracted.date}")
        if extracted.category:
            lines.append(f"Kategorie: {extracted.category}")
        lines.append("")
        if match.transaction_id:
            lines.append(f"✅ Zugeordnet zu Transaktion: {match.transaction_id}")
            lines.append(f"   Methode: {match.method}, Konfidenz: {match.confidence:.0%}")
        else:
            lines.append("⚠️  Kein automatischer Match gefunden.")
            lines.append("   Bitte manuell prüfen: finanzhub inbox show <id>")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helfer
# ---------------------------------------------------------------------------


def _extract_email_address(sender_header: str) -> str | None:
    """Extrahiert die reine E-Mail-Adresse aus 'Name <addr>' oder 'addr'."""
    import re

    m = re.search(r"<([^>]+@[^>]+)>", sender_header)
    if m:
        return m.group(1).strip()
    m = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", sender_header)
    return m.group(0).strip() if m else None


def _guess_mime(file_path: Path) -> str:
    suffix = file_path.suffix.lower()
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".heic": "image/heic",
        ".heif": "image/heif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }.get(suffix, "application/octet-stream")


# JSON-Encoding-Helper für extraction_raw (von Tests gebraucht)
def _to_jsonable(value: Any) -> Any:
    if isinstance(value, ExtractedReceipt):
        return value.to_db_dict()
    return value


_ = json  # noqa: F841 — re-export für Tests
__all__ = ["InboxEngine", "InboxRunResult"] + (["_to_jsonable"] if False else [])
