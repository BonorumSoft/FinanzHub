"""Marktdaten-Service: löst ISIN zu Ticker auf und holt aktuelle Kurse.

Auflösungsreihenfolge:

1. statische Karte (schnellster Pfad, kein Netzwerk)
2. DB-Cache (``price_history``, letzter Eintrag < 1h)
3. OpenFIGI API (API-Key optional)
4. ``yfinance`` als universelles Fallback (per Ticker)
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)

import requests
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from app.config_loader import AssetsConfig
from app.data.db import execute
from app.logger import get_logger

logger = get_logger(__name__)

# ISIN -> bevorzugter Ticker (Yahoo-Finance-kompatibel)
STATIC_ISIN_MAP: dict[str, str] = {
    "US0378331005": "AAPL",
    "US5949181045": "MSFT",
    "US02079K3059": "GOOGL",
    "US0231351067": "AMZN",
    "US67066G1040": "NVDA",
    "US30303M1027": "META",
    "IE00B4L5Y983": "IWDA.AS",
    "IE00B3XXRP09": "CSPX.L",
    "IE00B3RBWM25": "VWRL.L",
    "DE0005933931": "EXS1.DE",
    "LU0392494562": "C300.DE",
    "IE00BFM6TC58": "AMZN",
    "IE00B5BMR087": "EUNL.DE",
    "IE00B4K48X80": "IUSE.L",
    "IE00B53SZB19": "SGLN.L",
    "IE00B579F325": "AGGH.MI",
    "DE000A0Q4R36": "EUNL.DE",
    "US4642863926": "VOO",
    "US4642876555": "VTI",
    "US4642872000": "IVV",
}

CACHE_TTL = timedelta(hours=1)
PRICE_TTL = timedelta(hours=1)
DEFAULT_TIMEOUT = 15


# ---------------------------------------------------------------------------
# Auflösung ISIN -> Ticker
# ---------------------------------------------------------------------------


def resolve_ticker(isin: str, openfigi_key: str | None = None) -> str | None:
    """Liefert einen Yahoo-Finance-Ticker für die gegebene ISIN."""
    if isin in STATIC_ISIN_MAP:
        return STATIC_ISIN_MAP[isin]

    if openfigi_key:
        try:
            resp = requests.post(
                "https://api.openfigi.com/v3/mapping",
                headers={"X-OPENFIGI-APIKEY": openfigi_key, "Content-Type": "application/json"},
                json=[{"idType": "ID_ISIN", "idValue": isin}],
                timeout=DEFAULT_TIMEOUT,
            )
            resp.raise_for_status()
            data = resp.json()
            if data and data[0].get("data"):
                ticker = data[0]["data"][0].get("ticker")
                if ticker:
                    logger.info("OpenFIGI: %s -> %s", isin, ticker)
                    return ticker
        except (requests.RequestException, ValueError, KeyError) as err:
            logger.warning("OpenFIGI lookup für %s fehlgeschlagen: %s", isin, err)

    return None


# ---------------------------------------------------------------------------
# Kursabruf
# ---------------------------------------------------------------------------


def _fetch_yfinance_price(ticker: str) -> tuple[float | None, str | None]:
    try:
        import yfinance as yf
    except ImportError as err:  # pragma: no cover - optional
        logger.error("yfinance ist nicht installiert: %s", err)
        return None, None

    try:
        info = yf.Ticker(ticker)
        last = info.fast_info.last_price
        if last is not None and last > 0:
            currency = getattr(info.fast_info, "currency", None) or "USD"
            return float(last), currency
    except Exception as err:  # yfinance wirft verschiedene Exception-Typen
        logger.warning("yfinance fast_info für %s fehlgeschlagen: %s", ticker, err)

    try:
        import yfinance as yf

        hist = yf.Ticker(ticker).history(period="1d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1]), None
    except Exception as err:
        logger.warning("yfinance history für %s fehlgeschlagen: %s", ticker, err)

    return None, None


def _fx_rate_to_eur(currency: str) -> float:
    if currency.upper() == "EUR":
        return 1.0
    try:
        import yfinance as yf

        rate = yf.Ticker(f"{currency}EUR=X").fast_info.last_price
        if rate and rate > 0:
            return float(rate)
    except Exception as err:
        logger.warning("FX-Rate %s->EUR fehlgeschlagen: %s", currency, err)
    return 1.0


# ---------------------------------------------------------------------------
# Service-Klasse
# ---------------------------------------------------------------------------


class PriceService:
    """Stellt aktuelle Kurse für alle Positionen bereit (mit Caching)."""

    def __init__(
        self,
        engine: Engine | None = None,
        openfigi_key: str | None = None,
        sleep_between_calls: float = 0.0,
    ) -> None:
        self.engine = engine
        self.openfigi_key = openfigi_key
        self.sleep_between_calls = sleep_between_calls

    # ------------------------------------------------------------------

    def get_price(self, isin: str) -> tuple[float | None, str]:
        """Liefert ``(price_eur, currency)`` oder ``(None, 'EUR')`` bei Fehler."""
        cached = self._from_cache(isin) if self.engine else None
        if cached is not None:
            return cached

        ticker = self._ticker_for(isin)
        if not ticker:
            logger.warning("Kein Ticker für ISIN %s gefunden, Position wird übersprungen", isin)
            return None, "EUR"

        price, currency = _fetch_yfinance_price(ticker)
        if price is None:
            return None, "EUR"

        if self.sleep_between_calls:
            time.sleep(self.sleep_between_calls)

        rate = _fx_rate_to_eur(currency or "USD")
        price_eur = price * rate
        self._store_price(isin, ticker, price, currency or "USD", price_eur)
        return price_eur, currency or "USD"

    def enrich_assets(self, assets: AssetsConfig) -> list[dict[str, Any]]:
        """Berechnet für jede Security-Position aktuellen Wert und P&L."""
        result: list[dict[str, Any]] = []
        for sec in assets.securities:
            price_eur, currency = self.get_price(sec.isin)
            if price_eur is None:
                logger.warning("Position %s (%s) konnte nicht bewertet werden", sec.name, sec.isin)
                continue
            value = price_eur * sec.quantity
            pnl = (price_eur - sec.purchase_price) * sec.quantity
            result.append(
                {
                    "isin": sec.isin,
                    "name": sec.name,
                    "quantity": sec.quantity,
                    "purchase_price": sec.purchase_price,
                    "current_price": price_eur,
                    "currency": currency,
                    "value": value,
                    "pnl": pnl,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _ticker_for(self, isin: str) -> str | None:
        if isin in STATIC_ISIN_MAP:
            return STATIC_ISIN_MAP[isin]
        return resolve_ticker(isin, self.openfigi_key)

    def _from_cache(self, isin: str) -> tuple[float, str] | None:
        if self.engine is None:
            return None
        try:
            rows = execute(
                self.engine,
                "SELECT price_eur, currency, recorded_at FROM price_history "
                "WHERE isin = :i ORDER BY recorded_at DESC LIMIT 1",
                {"i": isin},
            )
        except SQLAlchemyError as err:
            logger.debug("Cache-Read für %s fehlgeschlagen: %s", isin, err)
            return None
        if not rows:
            return None
        row = rows[0]
        recorded_at = row.get("recorded_at")
        if isinstance(recorded_at, str):
            try:
                recorded_at = datetime.fromisoformat(recorded_at)
            except ValueError:
                return None
        if not recorded_at or _utcnow() - recorded_at > PRICE_TTL:
            return None
        return float(row["price_eur"]), str(row["currency"])

    def _store_price(
        self, isin: str, ticker: str, price: float, currency: str, price_eur: float
    ) -> None:
        if self.engine is None:
            return
        try:
            with self.engine.begin() as conn:
                from sqlalchemy import text

                conn.execute(
                    text(
                        "INSERT INTO price_history (isin, ticker, price, currency, price_eur) "
                        "VALUES (:i, :t, :p, :c, :pe)"
                    ),
                    {
                        "i": isin,
                        "t": ticker,
                        "p": f"{price:.4f}",
                        "c": currency,
                        "pe": f"{price_eur:.4f}",
                    },
                )
        except SQLAlchemyError as err:
            logger.warning("Konnte Preis-Cache nicht aktualisieren: %s", err)
