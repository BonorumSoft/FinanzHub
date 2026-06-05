"""Tests für ``app.core.portfolio_engine``."""

from __future__ import annotations

from app.banking.base import BankBalance
from app.config_loader import AssetsConfig
from app.core.portfolio_engine import calculate


def _bal(account_id: str, balance: float) -> BankBalance:
    return BankBalance(
        account_id=account_id,
        account_name=account_id,
        iban=None,
        balance=balance,
        currency="EUR",
    )


class TestPortfolio:
    def test_sums_banks_securities_real_estate(self) -> None:
        assets = AssetsConfig.model_validate(
            {
                "securities": [
                    {"isin": "X", "quantity": 10, "purchase_price": 100},
                ],
                "real_estate": [
                    {
                        "name": "R",
                        "current_value": 500_000,
                        "purchase_price": 400_000,
                        "value_growth": 0.02,
                        "rent_monthly": 0,
                        "loan_remaining": 100_000,
                        "interest_rate": 0.03,
                        "loan_payment_monthly": 500,
                    }
                ],
            }
        )
        valuations = [{"isin": "X", "name": "X", "quantity": 10, "purchase_price": 100, "current_price": 150, "value": 1500}]
        nw = calculate(assets, [_bal("A", 1000)], valuations)
        # Bank 1000 + Depot 1500 + RE-EK (500k - 100k) = 402.500
        assert nw.bank_total == 1000.0
        assert nw.securities_total == 1500.0
        assert nw.real_estate_equity == 400_000.0
        assert nw.net_worth == 402_500.0

    def test_position_pnl(self) -> None:
        assets = AssetsConfig.model_validate(
            {"securities": [{"isin": "X", "quantity": 2, "purchase_price": 50}]}
        )
        valuations = [
            {"isin": "X", "name": "X", "quantity": 2, "purchase_price": 50, "current_price": 75, "value": 150}
        ]
        nw = calculate(assets, [], valuations)
        pos = nw.positions[0]
        assert pos.pnl == 50.0
        assert pos.pnl_percent == 50.0

    def test_empty(self) -> None:
        nw = calculate(AssetsConfig(), [], [])
        assert nw.net_worth == 0
        assert nw.positions == []
        assert nw.bank_accounts == []
