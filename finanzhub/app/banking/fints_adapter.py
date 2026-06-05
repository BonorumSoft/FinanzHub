"""FinTS-Adapter (optional, nicht-standardmäßig aktiv).

FinTS ist ein komplexes Protokoll mit starker TLS-Client-Auth. Diese
Implementierung ist absichtlich dünn gehalten: das schwere Heben
übernimmt ``python-fints``. Wenn die Bibliothek nicht installiert ist,
schlägt der Import mit einer klaren Fehlermeldung fehl.
"""

from __future__ import annotations

import importlib
from datetime import date
from typing import Any

from app.banking.base import BankAdapter, BankBalance, BankTransaction
from app.logger import get_logger

logger = get_logger(__name__)


class FinTSAdapter(BankAdapter):
    """Optionaler FinTS-Adapter (python-fints)."""

    name = "fints"

    def __init__(
        self,
        blz: str,
        endpoint: str,
        username: str,
        pin: str,
        iban: str,
        product_id: str = "FHHB12345",
    ) -> None:
        self.blz = blz
        self.endpoint = endpoint
        self.username = username
        self.pin = pin
        self.iban = iban
        self.product_id = product_id

    def _get_client(self) -> Any:
        try:
            fints = importlib.import_module("fints")
        except ImportError as err:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "FinTS-Adapter benötigt 'python-fints': pip install python-fints"
            ) from err
        return fints

    def test_connection(self) -> bool:
        try:
            self._get_client()
        except RuntimeError as err:
            logger.error("FinTS-Adapter nicht verfügbar: %s", err)
            return False
        return True

    def get_balances(self) -> list[BankBalance]:
        logger.warning("FinTS-Adapter: get_balances ist als Stub implementiert")
        return []

    def get_transactions(self, since: date) -> list[BankTransaction]:
        logger.warning("FinTS-Adapter: get_transactions ist als Stub implementiert")
        return []
