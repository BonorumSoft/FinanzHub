"""Deduplizierung von Bank-Transaktionen.

Generiert deterministische Transaktions-IDs aus den Kern-Feldern einer
Buchung. So können wir den Idempotenz-Vertrag garantieren: derselbe
fachliche Vorgang führt immer zur selben ID und damit zu genau einer
Zeile in der ``transactions``-Tabelle.
"""

from __future__ import annotations

import hashlib
from typing import Final

from app.logger import get_logger

logger = get_logger(__name__)

_FIELDS: Final[tuple[str, ...]] = (
    "booking_date",
    "amount",
    "description",
    "counterparty_iban",
)


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return str(value).strip().lower()


def generate_transaction_id(
    booking_date: str,
    amount: float,
    description: str,
    counterparty_iban: str | None = None,
) -> str:
    """Berechnet eine deterministische Transaktions-ID als SHA-256-Hex.

    Wird verwendet, wenn der Provider keine eigene ID liefert. Andernfalls
    sollte dessen ID direkt übernommen werden.
    """
    parts = [
        _normalize(booking_date),
        _normalize(f"{amount:.2f}"),
        _normalize(description),
        _normalize(counterparty_iban),
    ]
    raw = "|".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def is_provider_id(provider_id: str | None) -> bool:
    """Heuristik: sieht der String nach einer vom Provider vergebenen ID aus?"""
    if not provider_id:
        return False
    pid = provider_id.strip()
    if len(pid) < 8:
        return False
    return any(ch.isalnum() for ch in pid)


__all__ = ["generate_transaction_id", "is_provider_id"]
