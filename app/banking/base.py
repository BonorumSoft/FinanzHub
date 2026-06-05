"""Abstrakte Banking-Adapter-Schnittstelle.

Alle konkreten Bank-Adapter (Enable Banking, FinTS, CSV, Demo) implementieren
dieses Interface. ``bank_collector`` arbeitet ausschließlich gegen diese
Schnittstelle, niemals gegen konkrete Klassen.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass
class BankBalance:
    """Kontosaldo zu einem bestimmten Zeitpunkt."""

    account_id: str
    account_name: str
    iban: str | None
    balance: float
    currency: str = "EUR"
    recorded_at: date | None = None


@dataclass
class BankTransaction:
    """Eine einzelne Buchung."""

    transaction_id: str
    account_id: str
    amount: float
    currency: str
    booking_date: date
    description: str
    counterparty_name: str | None = None
    counterparty_iban: str | None = None
    is_internal: bool = False
    value_date: date | None = None
    raw: dict | None = field(default=None, repr=False)


class BankAdapter(ABC):
    """Abstrakte Basisklasse für alle Bank-Adapter."""

    name: str = "abstract"

    @abstractmethod
    def get_balances(self) -> list[BankBalance]:
        """Liefert die aktuellen Salden aller Konten dieses Adapters."""

    @abstractmethod
    def get_transactions(self, since: date) -> list[BankTransaction]:
        """Liefert alle Buchungen seit ``since`` (inklusive) in chronologischer Reihenfolge."""

    @abstractmethod
    def test_connection(self) -> bool:
        """Prüft, ob die Verbindung zum Provider aufgebaut werden kann."""

    def own_ibans(self) -> list[str]:
        """Hilfs-Methode: eigene IBANs, die als interne Umbuchung erkannt werden sollen."""
        return []
