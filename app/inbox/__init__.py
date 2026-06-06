"""Beleg-Inbox: IMAP-Polling, KI-Extraktion, Transaktions-Matching.

Sechs Module mit klaren Verantwortlichkeiten:

- :mod:`app.inbox.mail_fetcher`       — IMAP-Poller
- :mod:`app.inbox.attachment_handler`  — Routing Bild vs. PDF
- :mod:`app.inbox.image_converter`     — Bild → PDF
- :mod:`app.inbox.receipt_extractor`   — KI-Extraktion (provider-agnostisch)
- :mod:`app.inbox.transaction_matcher` — Beleg ↔ Buchung
- :mod:`app.inbox.inbox_engine`        — Orchestrator

Sicherheit:
  - Whitelist ``allowed_senders`` ist Pflicht in Produktion.
  - Original-Anhang wird IMMER zuerst in DB erfasst, bevor verarbeitet wird.
  - KI-Output wird validiert (Wertebereiche, parsebare Datumsangaben).
  - PDFs in ``storage_path`` außerhalb des Git-Repos, Modus 0700.
"""
