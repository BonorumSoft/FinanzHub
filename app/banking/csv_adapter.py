"""CSV-Adapter für manuelle Bank-Exporte.

Viele Banken bieten CSV-Exporte an. Dieses Modul liest typische
Spalten (``Datum``, ``Betrag``, ``Verwendungszweck``, ``IBAN``) tolerant
ein und konvertiert sie in :class:`BankTransaction`-Records.
"""

from __future__ import annotations

import csv
from datetime import date, datetime
from pathlib import Path

from app.banking.base import BankAdapter, BankBalance, BankTransaction
from app.data.dedup import generate_transaction_id
from app.logger import get_logger

logger = get_logger(__name__)


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "booking_date": ("Datum", "Buchungsdatum", "Booking Date", "date"),
    "value_date": ("Wertstellung", "Value Date"),
    "amount": ("Betrag", "Amount", "amount"),
    "currency": ("Währung", "Currency"),
    "description": ("Verwendungszweck", "Buchungstext", "Description", "Memo"),
    "counterparty_name": ("Empfänger", "Auftraggeber", "Counterparty", "Name"),
    "counterparty_iban": ("IBAN", "Empfänger-IBAN", "Counterparty IBAN"),
}


def _find_col(headers: list[str], *aliases: str) -> str | None:
    lower = {h.lower(): h for h in headers}
    for alias in aliases:
        if alias.lower() in lower:
            return lower[alias.lower()]
    return None


class CSVAdapter(BankAdapter):
    """Liest eine CSV-Datei mit Bank-Transaktionen."""

    name = "csv"

    def __init__(self, csv_path: str, account_id: str = "CSV_IMPORT", account_name: str = "CSV-Import") -> None:
        self.path = Path(csv_path)
        self.account_id = account_id
        self.account_name = account_name

    def test_connection(self) -> bool:
        return self.path.exists()

    def get_balances(self) -> list[BankBalance]:
        return []  # CSV liefert in der Regel keinen Saldo

    def get_transactions(self, since: date) -> list[BankTransaction]:
        if not self.path.exists():
            logger.warning("CSVAdapter: Datei %s existiert nicht", self.path)
            return []
        with self.path.open("r", encoding="utf-8", newline="") as fh:
            # Heuristik: Trennzeichen anhand der Kopfzeile ableiten.
            sample = fh.read(4096)
            fh.seek(0)
            delimiter = ";" if sample.count(";") > sample.count(",") else ","
            reader = csv.DictReader(fh, delimiter=delimiter)
            headers = reader.fieldnames or []
            txs: list[BankTransaction] = []
            for row in reader:
                tx = self._parse_row(row, headers, since)
                if tx is not None:
                    txs.append(tx)
        return txs

    def own_ibans(self) -> list[str]:
        return []

    def _parse_row(
        self, row: dict[str, str], headers: list[str], since: date
    ) -> BankTransaction | None:
        date_col = _find_col(headers, *_FIELD_ALIASES["booking_date"])
        amount_col = _find_col(headers, *_FIELD_ALIASES["amount"])
        if not date_col or not amount_col:
            return None

        raw_date = (row.get(date_col) or "").strip()
        if not raw_date:
            return None
        booking = self._parse_date(raw_date)
        if booking is None or booking < since:
            return None

        raw_amount = (row.get(amount_col) or "0").strip().replace(".", "").replace(",", ".")
        try:
            amount = float(raw_amount)
        except ValueError:
            return None

        desc_col = _find_col(headers, *_FIELD_ALIASES["description"])
        cp_col = _find_col(headers, *_FIELD_ALIASES["counterparty_name"])
        iban_col = _find_col(headers, *_FIELD_ALIASES["counterparty_iban"])
        curr_col = _find_col(headers, *_FIELD_ALIASES["currency"])

        return BankTransaction(
            transaction_id=generate_transaction_id(
                booking.isoformat(),
                amount,
                row.get(desc_col or "", ""),
                row.get(iban_col or "", "") or None,
            ),
            account_id=self.account_id,
            amount=amount,
            currency=(row.get(curr_col or "", "EUR") or "EUR").strip() or "EUR",
            booking_date=booking,
            description=(row.get(desc_col or "", "") or "").strip(),
            counterparty_name=(row.get(cp_col or "", "") or "").strip() or None,
            counterparty_iban=(row.get(iban_col or "", "") or "").strip() or None,
        )

    @staticmethod
    def _parse_date(raw: str) -> date | None:
        for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(raw, fmt).date()
            except ValueError:
                continue
        return None
