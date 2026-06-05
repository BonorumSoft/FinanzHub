"""Portfolio-Engine: berechnet das aktuelle Nettovermögen.

Stellt das zentrale :class:`NetWorth`-Dataclass bereit, das von
Report-Generator, Forecast-Engine und CLI-Befehlen gemeinsam genutzt wird.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
from collections.abc import Iterable

from app.banking.base import BankBalance
from app.config_loader import AssetsConfig
from app.core.real_estate_model import total_equity_now
from app.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SecurityValuation:
    isin: str
    name: str
    quantity: float
    purchase_price: float
    current_price: float
    value: float
    pnl: float
    pnl_percent: float


@dataclass
class RealEstateDetail:
    name: str
    current_value: float
    loan_balance: float
    equity: float
    equity_ratio: float


@dataclass
class NetWorth:
    bank_total: float
    securities_total: float
    real_estate_equity: float
    net_worth: float
    calculated_at: datetime
    positions: list[SecurityValuation] = field(default_factory=list)
    real_estate_details: list[RealEstateDetail] = field(default_factory=list)
    bank_accounts: list[BankBalance] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "bank_total": self.bank_total,
            "securities_total": self.securities_total,
            "real_estate_equity": self.real_estate_equity,
            "net_worth": self.net_worth,
            "calculated_at": self.calculated_at.isoformat(),
            "positions": [
                {
                    "isin": p.isin,
                    "name": p.name,
                    "quantity": p.quantity,
                    "purchase_price": p.purchase_price,
                    "current_price": p.current_price,
                    "value": p.value,
                    "pnl": p.pnl,
                    "pnl_percent": p.pnl_percent,
                }
                for p in self.positions
            ],
            "real_estate_details": [
                {
                    "name": d.name,
                    "current_value": d.current_value,
                    "loan_balance": d.loan_balance,
                    "equity": d.equity,
                    "equity_ratio": d.equity_ratio,
                }
                for d in self.real_estate_details
            ],
            "bank_accounts": [
                {
                    "account_id": b.account_id,
                    "account_name": b.account_name,
                    "iban": b.iban,
                    "balance": b.balance,
                    "currency": b.currency,
                }
                for b in self.bank_accounts
            ],
        }


def calculate(
    assets: AssetsConfig,
    bank_balances: Iterable[BankBalance],
    valuations: Iterable[dict],
) -> NetWorth:
    """Berechnet das Nettovermögen aus Bank-Salden, Depot-Bewertungen und Immobilien-EK.

    ``valuations`` ist eine Liste von Dicts, wie sie
    :meth:`PriceService.enrich_assets` liefert.
    """
    bank_list = list(bank_balances)
    bank_total = sum(b.balance for b in bank_list)

    positions: list[SecurityValuation] = []
    securities_total = 0.0
    for v in valuations:
        value = float(v.get("value", 0.0))
        securities_total += value
        purchase_total = float(v.get("purchase_price", 0.0)) * float(v.get("quantity", 0.0))
        pnl = value - purchase_total
        pnl_pct = (pnl / purchase_total * 100.0) if purchase_total else 0.0
        positions.append(
            SecurityValuation(
                isin=v.get("isin", ""),
                name=v.get("name") or v.get("isin", ""),
                quantity=float(v.get("quantity", 0.0)),
                purchase_price=float(v.get("purchase_price", 0.0)),
                current_price=float(v.get("current_price", 0.0)),
                value=round(value, 2),
                pnl=round(pnl, 2),
                pnl_percent=round(pnl_pct, 2),
            )
        )

    real_estate_details: list[RealEstateDetail] = []
    for re_asset in assets.real_estate:
        equity = max(0.0, re_asset.current_value - re_asset.loan_balance())
        ek_ratio = (equity / re_asset.purchase_price * 100.0) if re_asset.purchase_price else 0.0
        real_estate_details.append(
            RealEstateDetail(
                name=re_asset.name,
                current_value=re_asset.current_value,
                loan_balance=re_asset.loan_balance(),
                equity=round(equity, 2),
                equity_ratio=round(ek_ratio, 2),
            )
        )
    re_equity = total_equity_now(assets.real_estate)

    net_worth = bank_total + securities_total + re_equity

    return NetWorth(
        bank_total=round(bank_total, 2),
        securities_total=round(securities_total, 2),
        real_estate_equity=round(re_equity, 2),
        net_worth=round(net_worth, 2),
        calculated_at=_utcnow(),
        positions=positions,
        real_estate_details=real_estate_details,
        bank_accounts=bank_list,
    )


__all__ = ["NetWorth", "RealEstateDetail", "SecurityValuation", "calculate"]
