"""Tests für ``app.data.price_service`` (mit gemocktem yfinance)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.config_loader import AssetsConfig
from app.data.price_service import PriceService, resolve_ticker


class TestResolveTicker:
    def test_static_map_hit(self) -> None:
        assert resolve_ticker("IE00B4L5Y983") == "IWDA.AS"
        assert resolve_ticker("US0378331005") == "AAPL"

    def test_unknown_isin_returns_none(self) -> None:
        with patch("app.data.price_service.requests.post") as post:
            post.side_effect = Exception("network")
            assert resolve_ticker("XX9999999999") is None


class _FakeFastInfo:
    last_price = 100.0
    currency = "USD"


def _fake_ticker_factory(prices: dict[str, float]):
    def factory(symbol: str):
        m = MagicMock()
        m.fast_info = _FakeFastInfo()
        # Patch: nutze den USD->EUR Faktor 0.9
        m.fast_info.last_price = prices.get(symbol, 100.0)
        return m

    return factory


class TestPriceService:
    def test_get_price_from_static_map(self) -> None:
        """Bei einem ISIN aus STATIC_ISIN_MAP wird direkt der Ticker verwendet."""
        with patch("app.data.price_service._fetch_yfinance_price") as fetch, \
             patch("app.data.price_service._fx_rate_to_eur", return_value=0.9):
            fetch.return_value = (200.0, "USD")
            service = PriceService(engine=None)
            price, currency = service.get_price("US0378331005")
            assert price == 200.0 * 0.9
            assert currency == "USD"

    def test_get_price_uses_cache(self) -> None:
        """Wenn der DB-Cache < 1h alt ist, wird kein Netzwerk-Call gemacht."""
        from datetime import datetime, timezone

        from sqlalchemy import create_engine, text

        engine = create_engine("sqlite:///:memory:", future=True)
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE price_history ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "isin TEXT, ticker TEXT, price NUMERIC, currency TEXT, price_eur NUMERIC, "
                    "recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO price_history (isin, ticker, price, currency, price_eur, recorded_at) "
                    "VALUES (:i, :t, :p, :c, :pe, :r)"
                ),
                {
                    "i": "US0378331005",
                    "t": "AAPL",
                    "p": "150.0",
                    "c": "USD",
                    "pe": "135.0",
                    "r": datetime.now(timezone.utc),
                },
            )

        service = PriceService(engine=engine)
        # Kein yfinance-Patch nötig: Cache wird vor yfinance geprüft
        price, currency = service.get_price("US0378331005")
        assert price == 135.0
        assert currency == "USD"

    def test_get_price_returns_none_for_unknown(self) -> None:
        service = PriceService(engine=None)
        with patch("app.data.price_service._fetch_yfinance_price", return_value=(None, None)):
            price, currency = service.get_price("XX0000000000")
            assert price is None

    def test_enrich_assets(self) -> None:
        assets = AssetsConfig.model_validate(
            {"securities": [{"isin": "US0378331005", "quantity": 1, "purchase_price": 100}]}
        )
        service = PriceService(engine=None)
        with patch("app.data.price_service._fetch_yfinance_price") as fetch, \
             patch("app.data.price_service._fx_rate_to_eur", return_value=0.9):
            fetch.return_value = (200.0, "USD")
            result = service.enrich_assets(assets)
            assert len(result) == 1
            assert result[0]["value"] == 200.0 * 0.9
            assert result[0]["pnl"] == (200.0 * 0.9 - 100)

    def test_enrich_assets_skips_failed(self) -> None:
        assets = AssetsConfig.model_validate(
            {"securities": [{"isin": "XX", "quantity": 1, "purchase_price": 100}]}
        )
        service = PriceService(engine=None)
        with patch("app.data.price_service._fetch_yfinance_price", return_value=(None, None)):
            result = service.enrich_assets(assets)
            assert result == []
