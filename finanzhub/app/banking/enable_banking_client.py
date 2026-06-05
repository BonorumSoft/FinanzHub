"""Enable-Banking-API-Adapter.

Implementiert die Authentifizierung per RS256 (RSA-2048) JWT und
Konto-/Buchungs-Abfragen gegen die Enable-Banking REST-API. Bei Session-
Ablauf (HTTP 401) wird eine Warnung geloggt und eine leere Liste
zurückgegeben — kein Absturz.
"""

from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

import jwt
import requests
from requests.exceptions import HTTPError, RequestException, Timeout

from app.banking.base import BankAdapter, BankBalance, BankTransaction
from app.logger import get_logger

logger = get_logger(__name__)

DEFAULT_BASE_URL = "https://api.enablebanking.com"
REQUEST_TIMEOUT = 20  # Sekunden


def _retry(max_attempts: int = 3):
    """Decorator: exponentielles Backoff 1s/4s/16s."""

    def decorator(fn):
        def wrapper(*args, **kwargs):
            delay = 1.0
            last_err: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except (Timeout, ConnectionError, RequestException) as err:
                    last_err = err
                    logger.warning(
                        "EnableBanking: %s fehlgeschlagen (Versuch %d/%d): %s",
                        fn.__name__,
                        attempt,
                        max_attempts,
                        err,
                    )
                    if attempt < max_attempts:
                        time.sleep(delay)
                        delay *= 4
            raise last_err  # type: ignore[misc]

        return wrapper

    return decorator


class EnableBankingClient(BankAdapter):
    """Adapter für die Enable-Banking-API (PSD2-Aggregator)."""

    name = "enable_banking"

    def __init__(
        self,
        key_id: str,
        private_key_path: str,
        app_id: str,
        base_url: str = DEFAULT_BASE_URL,
        own_ibans: list[str] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        if not (key_id and private_key_path and app_id):
            raise ValueError(
                "EnableBankingClient benötigt key_id, private_key_path und app_id."
            )
        self.key_id = key_id
        self.private_key = Path(private_key_path).read_text(encoding="utf-8")
        self.app_id = app_id
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._cached_ibans = set(own_ibans or [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        try:
            self._auth_get("/application")
            return True
        except (HTTPError, Timeout, RequestException) as err:
            logger.error("EnableBanking: test_connection fehlgeschlagen: %s", err)
            return False

    def get_balances(self) -> list[BankBalance]:
        try:
            accounts = self._auth_get("/accounts")
        except HTTPError as err:
            if err.response is not None and err.response.status_code == 401:
                logger.warning("EnableBanking: Session abgelaufen, überspringe Saldo-Abfrage")
                return []
            raise

        balances: list[BankBalance] = []
        for acc in accounts.get("accounts", []):
            acc_id = acc.get("uid") or acc.get("account_id") or acc.get("iban")
            try:
                data = self._auth_get(f"/accounts/{acc_id}/balances")
            except HTTPError as err:
                if err.response is not None and err.response.status_code == 401:
                    logger.warning("EnableBanking: 401 bei /balances, leerer Saldo")
                    continue
                raise
            for bal in data.get("balances", []):
                amount_raw = bal.get("balance_amount") or bal.get("amount", {})
                if isinstance(amount_raw, dict):
                    amount = float(amount_raw.get("amount", 0))
                    currency = amount_raw.get("currency", "EUR")
                else:
                    amount = float(amount_raw)
                    currency = bal.get("currency", "EUR")
                balances.append(
                    BankBalance(
                        account_id=str(acc_id),
                        account_name=acc.get("name", ""),
                        iban=acc.get("iban"),
                        balance=amount,
                        currency=currency,
                        recorded_at=date.today(),
                    )
                )
                if acc.get("iban"):
                    self._cached_ibans.add(acc["iban"])
        return balances

    def get_transactions(self, since: date) -> list[BankTransaction]:
        try:
            accounts = self._auth_get("/accounts")
        except HTTPError as err:
            if err.response is not None and err.response.status_code == 401:
                logger.warning("EnableBanking: Session abgelaufen, überspringe Tx-Abfrage")
                return []
            raise

        all_tx: list[BankTransaction] = []
        for acc in accounts.get("accounts", []):
            acc_id = acc.get("uid") or acc.get("account_id") or acc.get("iban")
            try:
                data = self._auth_get(
                    f"/accounts/{acc_id}/transactions",
                    params={"date_from": since.isoformat()},
                )
            except HTTPError as err:
                if err.response is not None and err.response.status_code == 401:
                    logger.warning("EnableBanking: 401 bei /transactions, überspringe")
                    continue
                raise

            for entry in data.get("transactions", []):
                amt = entry.get("transaction_amount") or entry.get("amount") or {}
                if isinstance(amt, dict):
                    amount = float(amt.get("amount", 0))
                    currency = amt.get("currency", "EUR")
                else:
                    amount = float(amt)
                    currency = entry.get("currency", "EUR")

                cp = entry.get("counterparty") or {}
                cp_iban = cp.get("iban") or entry.get("counterparty_iban")
                is_internal = bool(cp_iban and cp_iban in self._cached_ibans)
                all_tx.append(
                    BankTransaction(
                        transaction_id=entry.get("transaction_id")
                        or entry.get("entry_id")
                        or f"eb-{entry.get('booking_date','')}-{amount}",
                        account_id=str(acc_id),
                        amount=amount,
                        currency=currency,
                        booking_date=date.fromisoformat(entry["booking_date"]),
                        description=entry.get("description") or entry.get("remittance_information") or "",
                        counterparty_name=cp.get("name") or entry.get("counterparty_name"),
                        counterparty_iban=cp_iban,
                        is_internal=is_internal,
                        value_date=(
                            date.fromisoformat(entry["value_date"])
                            if entry.get("value_date")
                            else None
                        ),
                        raw=entry,
                    )
                )
        return all_tx

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def own_ibans(self) -> list[str]:
        return list(self._cached_ibans)

    @_retry(max_attempts=3)
    def _auth_get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        token = self._make_jwt()
        url = f"{self.base_url}{path}"
        resp = self._session.get(
            url,
            params=params or {},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        if not resp.content:
            return {}
        return resp.json()

    def _make_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iss": "enablebanking.com",
            "aud": "api.enablebanking.com",
            "iat": now,
            "exp": now + 3600,
        }
        return jwt.encode(
            payload,
            self.private_key,
            algorithm="RS256",
            headers={"kid": self.key_id, "app_id": self.app_id},
        )
