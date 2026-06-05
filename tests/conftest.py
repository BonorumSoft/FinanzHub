"""Zentrale Test-Fixtures für FinanzHub.

Strikte Trennung: kein Test berührt echtes Netzwerk, echte DB oder
echten SMTP. Externe Abhängigkeiten werden via ``mocker``/``monkeypatch``
ersetzt; die DB ist immer SQLite in-memory.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

FIXTURES_DIR = Path(__file__).parent / "fixtures"

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("CONFIG_DIR", str(FIXTURES_DIR))


# ---------------------------------------------------------------------------
# Engine / DB
# ---------------------------------------------------------------------------


@pytest.fixture
def db() -> Engine:
    """SQLite in-memory DB mit angewendeten Migrationen."""
    engine = create_engine("sqlite:///:memory:", future=True)
    # Migrationen relativ zum Projekt-Root auflösen
    project_root = Path(__file__).resolve().parents[1]
    from app.data.db import apply_migrations

    apply_migrations(engine, migrations_dir=project_root / "migrations")
    yield engine
    engine.dispose()


@pytest.fixture
def demo_transactions() -> list[dict[str, Any]]:
    """Lädt 90 Tage synthetischer Transaktionen vom DemoClient."""
    from app.banking.demo_client import DemoClient

    client = DemoClient()
    since = date.today() - timedelta(days=90)
    txs = client.get_transactions(since)
    return [
        {
            "id": t.transaction_id,
            "booking_date": t.booking_date.isoformat(),
            "amount": t.amount,
            "description": t.description,
            "counterparty_iban": t.counterparty_iban,
            "counterparty_name": t.counterparty_name,
        }
        for t in txs
    ]


# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_assets() -> Any:
    from app.config_loader import load_assets

    return load_assets(FIXTURES_DIR)


@pytest.fixture
def app_settings() -> Any:
    from app.config_loader import AppSettings

    return AppSettings()


@pytest.fixture
def forecast_config() -> Any:
    from app.config_loader import ForecastConfig

    return ForecastConfig(current_age=35, retirement_age=65)


# ---------------------------------------------------------------------------
# Bank-Adapter
# ---------------------------------------------------------------------------


@pytest.fixture
def demo_client() -> Any:
    from app.banking.demo_client import DemoClient

    return DemoClient()


# ---------------------------------------------------------------------------
# Hilfs-Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fixed_today() -> date:
    """Ein fixes 'heute'-Datum für deterministische Tests."""
    return date(2026, 6, 15)


@pytest.fixture
def freezegun_date():
    """Setzt ``date.today()`` auf einen festen Wert."""
    from freezegun import freeze_time

    with freeze_time("2026-06-15"):
        yield date(2026, 6, 15)
