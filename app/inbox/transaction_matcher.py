"""Matching: extrahierter Beleg ↔ Bank-Transaktion.

Strategie (Priorität absteigend):
  1. Exakter Betrag + Datum im Fenster + Händler-Substring → 0.95
  2. Exakter Betrag + Datum im Fenster                     → 0.85
  3. Fuzzy-Betrag (±Toleranz) + Datum im Fenster           → 0.70
  4. Nur Betrag (innerhalb erweitertes Fenster)             → 0.50
  5. Kein Match                                              → 0.0

Robustheit:
  - Kein Exception nach außen — bei DB-Fehler: no_match + Warnung.
  - Nur ausgehende Buchungen (Negativbeträge) werden gematcht.
  - Bei mehreren Kandidaten: höchste confidence, dann jüngste TX.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config_loader import InboxMatchingConfig
from app.inbox.receipt_extractor import ExtractedReceipt
from app.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Datenmodell
# ---------------------------------------------------------------------------


@dataclass
class MatchResult:
    """Ergebnis des Matchings."""

    transaction_id: str | None
    confidence: float
    method: str  # "exact_amount_merchant" | "exact_amount_date" | "fuzzy" | "no_match"
    candidate_count: int
    raw: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


class TransactionMatcher:
    """Matched einen :class:`ExtractedReceipt` gegen ``transactions``."""

    def __init__(self, engine: Engine, config: InboxMatchingConfig) -> None:
        self._engine = engine
        self._config = config

    def find_match(self, receipt: ExtractedReceipt) -> MatchResult:
        """Sucht die beste Transaktion für einen Beleg.

        Returns:
            :class:`MatchResult`. Niemals Exception.
        """
        if receipt.amount is None or not receipt.date:
            return MatchResult(None, 0.0, "no_match", 0)

        try:
            target_date = date.fromisoformat(receipt.date)
        except ValueError:
            return MatchResult(None, 0.0, "no_match", 0)

        try:
            candidates = self._fetch_candidates(target_date, abs(receipt.amount))
        except Exception as err:  # noqa: BLE001
            logger.warning("DB-Fehler bei Kandidaten-Abfrage: %s", err)
            return MatchResult(None, 0.0, "no_match", 0)

        if not candidates:
            return MatchResult(None, 0.0, "no_match", 0)

        return self._score_and_select(receipt, target_date, candidates)

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------

    def _fetch_candidates(self, target: date, amount_eur: float) -> list[dict[str, Any]]:
        date_min = target - timedelta(days=self._config.lookback_days)
        date_max = target + timedelta(days=self._config.date_tolerance_days)
        # 5% Toleranzfenster, engere Auswahl in SQL
        amount_min = -abs(amount_eur) * 1.05
        amount_max = -abs(amount_eur) * 0.95
        sql = text(
            """
            SELECT transaction_id, booking_date, amount,
                   description, counterparty_name, counterparty_iban
            FROM transactions
            WHERE amount BETWEEN :amount_min AND :amount_max
              AND booking_date BETWEEN :date_min AND :date_max
              AND (is_internal IS NULL OR is_internal = 0)
            ORDER BY booking_date DESC
            """
        )
        with self._engine.begin() as conn:
            rows = conn.execute(
                sql,
                {
                    "amount_min": amount_min,
                    "amount_max": amount_max,
                    "date_min": date_min,
                    "date_max": date_max,
                },
            ).fetchall()
        return [dict(row._mapping) for row in rows]

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _score_and_select(
        self,
        receipt: ExtractedReceipt,
        target_date: date,
        candidates: list[dict[str, Any]],
    ) -> MatchResult:
        target_amount = abs(float(receipt.amount or 0.0))
        scored: list[tuple[float, dict[str, Any]]] = []
        for cand in candidates:
            score = self._score(receipt, target_date, target_amount, cand)
            if score > 0:
                scored.append((score, cand))
        if not scored:
            return MatchResult(None, 0.0, "no_match", len(candidates))
        scored.sort(key=lambda x: (-x[0], -self._cand_date(x[1]).toordinal()))
        best_score, best_cand = scored[0]
        method = self._method_for_score(best_score, receipt, best_cand)
        return MatchResult(
            transaction_id=best_cand.get("transaction_id"),
            confidence=round(best_score, 3),
            method=method,
            candidate_count=len(candidates),
            raw=best_cand,
        )

    def _score(
        self,
        receipt: ExtractedReceipt,
        target_date: date,
        target_amount: float,
        cand: dict[str, Any],
    ) -> float:
        cand_amount = abs(float(cand.get("amount", 0.0) or 0.0))
        cand_date = self._cand_date(cand)
        amount_exact = abs(cand_amount - target_amount) < 0.005
        amount_fuzzy = self._amount_matches(target_amount, cand_amount)
        date_ok = abs((cand_date - target_date).days) <= self._config.date_tolerance_days
        merchant_ok = self._merchant_matches(receipt.merchant, cand)

        if amount_exact and date_ok and merchant_ok:
            return 0.95
        if amount_exact and date_ok:
            return 0.85
        if amount_fuzzy and date_ok:
            return 0.70
        if amount_exact:
            return 0.50
        return 0.0

    def _method_for_score(
        self, score: float, receipt: ExtractedReceipt, cand: dict[str, Any]
    ) -> str:
        if score >= 0.95:
            return "exact_amount_merchant"
        if score >= 0.85:
            return "exact_amount_date"
        if score >= 0.70:
            return "fuzzy"
        return "amount_only"

    def _amount_matches(self, receipt_amount: float, tx_amount: float) -> bool:
        diff_eur = abs(receipt_amount - tx_amount)
        if diff_eur <= self._config.amount_tolerance_eur:
            return True
        pct = diff_eur / max(abs(receipt_amount), 1e-6)
        return pct <= self._config.amount_tolerance_percent

    def _date_distance(self, receipt_date: date, tx_date: date) -> int:
        return abs((receipt_date - tx_date).days)

    def _merchant_matches(
        self, merchant: str | None, cand: dict[str, Any]
    ) -> bool:
        if not merchant:
            return False
        needle = self._normalize(merchant)
        if not needle:
            return False
        haystacks = [
            str(cand.get("description", "")),
            str(cand.get("counterparty_name", "")),
            str(cand.get("counterparty_iban", "")),
        ]
        return any(needle in self._normalize(h) for h in haystacks)

    @staticmethod
    def _normalize(s: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", "", s.lower())).strip()

    @staticmethod
    def _cand_date(cand: dict[str, Any]) -> date:
        bd = cand.get("booking_date")
        if isinstance(bd, date):
            return bd
        if isinstance(bd, str):
            try:
                return date.fromisoformat(bd)
            except ValueError:
                return date(1970, 1, 1)
        return date(1970, 1, 1)


__all__ = ["MatchResult", "TransactionMatcher"]


# Alias für externe Nutzung; nicht im Hauptpfad verwendet
_ = Decimal  # noqa: F841 — bewusst importiert, falls Decimal-Support nötig
