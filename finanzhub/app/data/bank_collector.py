"""Bank-Collector: orchestriert den Abruf, die Deduplizierung und das
Schreiben von Bank-Daten in die Datenbank.

Kennt ausschließlich das :class:`BankAdapter`-Interface — niemals
konkrete Adapter. Bei einem Adapter-Ausfall wird ein ``CollectionResult``
mit ``fallback_used=True`` zurückgegeben, und der zuletzt bekannte Saldo
aus der ``balances``-Tabelle dient als Notnagel.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
from collections.abc import Callable
from typing import Any

from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.banking.base import BankAdapter, BankBalance, BankTransaction
from app.config_loader import BanksConfig
from app.data.db import CollectionResult, execute, insert_or_ignore
from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Adapter-Factory
# ---------------------------------------------------------------------------


AdapterFactory = Callable[[dict[str, Any]], BankAdapter]


def default_adapter_factory(provider: str, options: dict[str, Any]) -> BankAdapter:
    """Erzeugt den zur ``provider``-Kennung passenden Adapter."""
    if provider == "demo":
        from app.banking.demo_client import DemoClient

        return DemoClient(
            seed=int(options.get("seed", 42)),
            history_days=int(options.get("history_days", 90)),
        )
    if provider == "csv":
        from app.banking.csv_adapter import CSVAdapter

        return CSVAdapter(
            csv_path=options["csv_path"],
            account_id=options.get("account_id", "CSV_IMPORT"),
        )
    if provider == "enable_banking":
        from app.banking.enable_banking_client import EnableBankingClient

        return EnableBankingClient(
            key_id=options["key_id"],
            private_key_path=options["private_key_path"],
            app_id=options["app_id"],
            base_url=options.get("base_url", "https://api.enablebanking.com"),
        )
    if provider == "fints":
        from app.banking.fints_adapter import FinTSAdapter

        return FinTSAdapter(
            blz=options["blz"],
            endpoint=options["endpoint"],
            username=options["username"],
            pin=options["pin"],
            iban=options["iban"],
        )
    raise ValueError(f"Unbekannter Provider: {provider}")


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class BankCollector:
    """Orchestrator zwischen Adapter und DB."""

    def __init__(
        self,
        engine: Engine,
        banks_config: BanksConfig,
        factory: AdapterFactory | None = None,
    ) -> None:
        self.engine = engine
        self.banks_config = banks_config
        self.factory: AdapterFactory = factory or default_adapter_factory

    def _build_adapter(self) -> tuple[BankAdapter, str]:
        active = self.banks_config.active_adapter
        chosen = next(
            (a for a in self.banks_config.adapters if a.name == active and a.enabled),
            None,
        ) or next((a for a in self.banks_config.adapters if a.enabled), None)
        if chosen is None:
            raise RuntimeError("Kein aktiver Bank-Adapter konfiguriert")
        adapter = self.factory(chosen.provider, chosen.options)
        logger.info("Bank-Adapter: %s (provider=%s)", chosen.name, chosen.provider)
        return adapter, chosen.name

    def collect_and_persist(self, since: date | None = None) -> CollectionResult:
        """Sammelt Salden und Buchungen und schreibt sie in die DB."""
        period_end = date.today()
        period_start = since or (period_end - timedelta(days=90))

        try:
            adapter, name = self._build_adapter()
        except (ValueError, KeyError, RuntimeError) as err:
            logger.error("Adapter-Konfiguration ungültig: %s", err)
            return CollectionResult(
                success=False,
                transactions_imported=0,
                balances_imported=0,
                fallback_used=True,
                error_message=str(err),
            )

        try:
            if not adapter.test_connection():
                raise RuntimeError(f"Adapter {name}: test_connection fehlgeschlagen")
            balances = adapter.get_balances()
            transactions = adapter.get_transactions(since=period_start)
        except Exception as err:  # bewusst breit: alle Provider-Fehler
            logger.warning(
                "Adapter %s fehlgeschlagen, verwende Fallback: %s", name, err, exc_info=False
            )
            return CollectionResult(
                success=False,
                transactions_imported=0,
                balances_imported=0,
                fallback_used=True,
                error_message=str(err),
                adapter_name=name,
                period_start=period_start,
                period_end=period_end,
            )

        try:
            tx_inserted = self._persist_transactions(transactions)
            bal_inserted = self._persist_balances(balances)
        except SQLAlchemyError as err:
            logger.error("DB-Fehler beim Persistieren: %s", err)
            return CollectionResult(
                success=False,
                transactions_imported=0,
                balances_imported=0,
                fallback_used=True,
                error_message=f"DB-Fehler: {err}",
                adapter_name=name,
                period_start=period_start,
                period_end=period_end,
            )

        logger.info(
            "Adapter %s: %d Buchungen, %d Salden geschrieben",
            name,
            tx_inserted,
            bal_inserted,
        )
        return CollectionResult(
            success=True,
            transactions_imported=tx_inserted,
            balances_imported=bal_inserted,
            adapter_name=name,
            period_start=period_start,
            period_end=period_end,
        )

    # ------------------------------------------------------------------
    # Persistenz
    # ------------------------------------------------------------------

    def _persist_transactions(self, txs: list[BankTransaction]) -> int:
        inserted = 0
        for tx in txs:
            row = {
                "transaction_id": tx.transaction_id,
                "account_id": tx.account_id,
                "booking_date": tx.booking_date.isoformat(),
                "value_date": tx.value_date.isoformat() if tx.value_date else None,
                "amount": f"{tx.amount:.2f}",
                "currency": tx.currency,
                "description": tx.description,
                "counterparty_name": tx.counterparty_name,
                "counterparty_iban": tx.counterparty_iban,
                "is_internal": tx.is_internal,
            }
            try:
                if insert_or_ignore(self.engine, "transactions", ("transaction_id",), row):
                    inserted += 1
            except SQLAlchemyError as err:
                logger.error("Konnte Tx %s nicht einfügen: %s", tx.transaction_id, err)
        return inserted

    def _persist_balances(self, balances: list[BankBalance]) -> int:
        inserted = 0
        for bal in balances:
            recorded_at = (
                bal.recorded_at.isoformat() if bal.recorded_at else _utcnow().isoformat()
            )
            try:
                with self.engine.begin() as conn:
                    from sqlalchemy import text

                    conn.execute(
                        text(
                            "INSERT INTO balances (account_id, balance, currency, recorded_at) "
                            "VALUES (:account_id, :balance, :currency, :recorded_at)"
                        ),
                        {
                            "account_id": bal.account_id,
                            "balance": f"{bal.balance:.2f}",
                            "currency": bal.currency,
                            "recorded_at": recorded_at,
                        },
                    )
                    inserted += 1
            except SQLAlchemyError as err:
                logger.error("Konnte Saldo %s nicht einfügen: %s", bal.account_id, err)
        return inserted


# ---------------------------------------------------------------------------
# Hilfsfunktion: letzter bekannter Saldo (für Fallback-Anzeige)
# ---------------------------------------------------------------------------


def last_known_balance(engine: Engine, account_id: str) -> float | None:
    rows = execute(
        engine,
        "SELECT balance FROM balances WHERE account_id = :a "
        "ORDER BY recorded_at DESC LIMIT 1",
        {"a": account_id},
    )
    return float(rows[0]["balance"]) if rows else None
