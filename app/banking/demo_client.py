"""Demo-Banking-Adapter für Tests und lokale Entwicklung.

Erzeugt drei synthetische Konten mit 90 Tagen realistischer
Transaktionshistorie. Sehr nützlich für CI-Tests und für Endanwender,
die FinanzHub erstmal ohne echte Bankverbindung ausprobieren wollen.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.banking.base import BankAdapter, BankBalance, BankTransaction
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class _DemoAccount:
    account_id: str
    account_name: str
    iban: str
    opening_balance: float
    currency: str = "EUR"
    kind: str = "giro"  # "giro" | "tagesgeld" | "checking"


@dataclass
class DemoClient(BankAdapter):
    """In-Memory-Bank mit deterministisch erzeugten Demo-Daten.

    Ein optionaler ``seed`` macht die Daten reproduzierbar — wichtig für
    stabile Tests.
    """

    name: str = "demo"
    seed: int = 42
    history_days: int = 90

    accounts: list[_DemoAccount] = field(
        default_factory=lambda: [
            _DemoAccount("DE_GIRO", "N26 Girokonto", "DE12500105170648489890", opening_balance=1850.0),
            _DemoAccount("DE_TAGESGELD", "ING Tagesgeld", "DE50500105170123456789", opening_balance=12500.0, kind="tagesgeld"),
            _DemoAccount("DE_CBK", "Commerzbank", "DE89370400440532013000", opening_balance=3200.0, kind="checking"),
        ]
    )

    def __post_init__(self) -> None:
        self._rng = random.Random(self.seed)
        self._tx_cache: list[BankTransaction] = []
        self._bal_cache: list[BankBalance] = []
        self._generate()

    # ------------------------------------------------------------------
    # BankAdapter
    # ------------------------------------------------------------------

    def test_connection(self) -> bool:
        return True

    def get_balances(self) -> list[BankBalance]:
        return list(self._bal_cache)

    def get_transactions(self, since: date) -> list[BankTransaction]:
        return [t for t in self._tx_cache if t.booking_date >= since]

    def own_ibans(self) -> list[str]:
        return [a.iban for a in self.accounts]

    # ------------------------------------------------------------------
    # Generierung
    # ------------------------------------------------------------------

    def _generate(self) -> None:
        today = date.today()
        start = today - timedelta(days=self.history_days)

        tx: list[BankTransaction] = []
        running_balances: dict[str, float] = {a.account_id: a.opening_balance for a in self.accounts}

        cursor = start
        seq = 0
        while cursor <= today:
            seq += 1
            for acc in self.accounts:
                if acc.kind == "tagesgeld":
                    continue  # Tagesgeld bekommt nur manuelle Transfers
                # Gehalt am 25. auf das Girokonto
                if cursor.day == 25 and acc.account_id == "DE_GIRO":
                    amount = round(3500 * (1 + self._rng.uniform(-0.02, 0.02)), 2)
                    tx.append(
                        self._mk_tx(
                            seq=seq,
                            account=acc,
                            booking=cursor,
                            amount=amount,
                            desc="ARBEITGEBER GEHALT",
                            counterparty="Arbeitgeber GmbH",
                            counterparty_iban="DE89370400440532013999",
                        )
                    )
                    running_balances[acc.account_id] += amount
                    continue

                # 1–3 zufällige Buchungen pro Tag
                n = self._rng.choices([0, 1, 2, 3], weights=[40, 35, 18, 7])[0]
                for _ in range(n):
                    seq += 1
                    kind = self._rng.choices(
                        ["miete", "strom", "lebensmittel", "versicherung", "abo", "gross"],
                        weights=[5, 5, 35, 5, 10, 5],
                    )[0]
                    amount = self._sample_amount(kind)
                    desc, cp_name, cp_iban = self._sample_counterparty(kind)
                    is_internal = cp_iban in self.own_ibans()
                    tx.append(
                        self._mk_tx(
                            seq=seq,
                            account=acc,
                            booking=cursor,
                            amount=-amount,
                            desc=desc,
                            counterparty=cp_name,
                            counterparty_iban=cp_iban,
                            is_internal=is_internal,
                        )
                    )
                    running_balances[acc.account_id] -= amount

            # Mieteingang am 1.–3. des Monats auf das Girokonto
            giro = self._acc_by_id("DE_GIRO")
            if 1 <= cursor.day <= 3 and giro is not None:
                acc = giro
                tenants = [
                    ("Mieter A", "DE11111111111111111111", 800.0),
                    ("Mieter B", "DE22222222222222222222", 1100.0),
                    ("Mieter C", "DE33333333333333333333", 950.0),
                ]
                for name, iban, base in tenants:
                    seq += 1
                    amount = round(base * (1 + self._rng.uniform(-0.05, 0.05)), 2)
                    tx.append(
                        self._mk_tx(
                            seq=seq,
                            account=acc,
                            booking=cursor,
                            amount=amount,
                            desc=f"MIETE {name.upper()}",
                            counterparty=name,
                            counterparty_iban=iban,
                        )
                    )
                    running_balances[acc.account_id] += amount
            cursor += timedelta(days=1)

        self._tx_cache = sorted(tx, key=lambda t: (t.booking_date, t.transaction_id))
        # Letzter bekannter Saldo wird auf heute gesetzt, mit kleiner Schwankung
        for acc in self.accounts:
            drift = running_balances[acc.account_id]
            self._bal_cache.append(
                BankBalance(
                    account_id=acc.account_id,
                    account_name=acc.account_name,
                    iban=acc.iban,
                    balance=round(drift, 2),
                    currency=acc.currency,
                    recorded_at=today,
                )
            )
        logger.info(
            "DemoClient: %d Buchungen über %d Tage generiert",
            len(self._tx_cache),
            self.history_days,
        )

    def _acc_by_id(self, acc_id: str) -> _DemoAccount | None:
        for a in self.accounts:
            if a.account_id == acc_id:
                return a
        return None

    def _sample_amount(self, kind: str) -> float:
        if kind == "miete":
            return 1200.0
        if kind == "strom":
            return self._rng.uniform(60, 120)
        if kind == "lebensmittel":
            return self._rng.uniform(15, 110)
        if kind == "versicherung":
            return self._rng.uniform(40, 180)
        if kind == "abo":
            return self._rng.uniform(8, 35)
        if kind == "gross":
            return self._rng.uniform(500, 1500)
        return self._rng.uniform(10, 200)

    def _sample_counterparty(self, kind: str) -> tuple[str, str, str]:
        table: dict[str, list[tuple[str, str, str]]] = {
            "lebensmittel": [
                ("REWE", "DE99000000000000000001", "REWE SAGT DANKE"),
                ("EDEKA", "DE99000000000000000002", "EDEKA MARKT"),
                ("LIDL", "DE99000000000000000003", "LIDL SAGT DANKE"),
            ],
            "strom": [("STADTWERKE", "DE99000000000000000010", "STADTWERKE STROM")],
            "versicherung": [
                ("HUK", "DE99000000000000000020", "HUK COBURG BEITRAG"),
                ("ALLIANZ", "DE99000000000000000021", "ALLIANZ VERSICHERUNG"),
            ],
            "abo": [
                ("SPOTIFY", "NL99INGB0000000001", "SPOTIFY ABBO"),
                ("NETFLIX", "NL99INGB0000000002", "NETFLIX.COM"),
                ("AMAZON PRIME", "DE99000000000000000030", "AMAZON PRIME"),
            ],
            "gross": [
                ("MEDIAMARKT", "DE99000000000000000040", "MEDIAMARKT"),
                ("IKEA", "DE99000000000000000041", "IKEA EINRICHAUS"),
                ("APOTHEKE", "DE99000000000000000042", "APOTHEKE ZENTRUM"),
            ],
            "miete": [("VERMIETER", "DE99000000000000000050", "MIETE WOHNUNG")],
        }
        return self._rng.choice(table[kind])

    def _mk_tx(
        self,
        seq: int,
        account: _DemoAccount,
        booking: date,
        amount: float,
        desc: str,
        counterparty: str | None,
        counterparty_iban: str | None,
        is_internal: bool = False,
    ) -> BankTransaction:
        from app.data.dedup import generate_transaction_id

        return BankTransaction(
            transaction_id=generate_transaction_id(
                booking.isoformat(), amount, desc, counterparty_iban
            ),
            account_id=account.account_id,
            amount=amount,
            currency=account.currency,
            booking_date=booking,
            description=desc,
            counterparty_name=counterparty,
            counterparty_iban=counterparty_iban,
            is_internal=is_internal,
        )
