# Entwickler­dokumentation (Development Guide)

Diese Dokumentation richtet sich an Entwickler, die FinanzHub **erweitern, debuggen oder als Bibliothek nutzen** möchten. Sie ergänzt die [Inbetriebnahmeanleitung](../README.md#3-inbetriebnahmeanleitung) und die [Nutzeranleitung](../README.md#4-nutzeranleitung) im README.

## Inhaltsverzeichnis

1. [Architektur-Überblick](#1-architektur-überblick)
2. [Layer-Regeln](#2-layer-regeln)
3. [Datenmodell & Migrationen](#3-datenmodell--migrationen)
4. [Module im Detail](#4-module-im-detail)
5. [FinanzHub erweitern](#5-finanzhub-erweitern)
6. [Tests & Qualität](#6-tests--qualität)
7. [Style-Guide](#7-style-guide)
8. [Debugging & Logging](#8-debugging--logging)
9. [Release- & Versionierungs­prozess](#9-release--versionsprozess)

---

## 1. Architektur-Überblick

FinanzHub folgt einer **strikt geschichteten Architektur** mit unidirektionalen Abhängigkeiten:

```
                  ┌──────────────────────────────────────┐
                  │  Presentation:  app/main.py          │
                  │  Scheduler:      app/scheduler.py     │
                  │  CLI:            app/cli.py           │
                  └────────────┬─────────────────────────┘
                               │
        ┌──────────────────────┼──────────────────────┐
        │                      │                      │
┌───────▼─────────┐   ┌─────────▼────────┐   ┌────────▼─────────┐
│ app/notifications│   │  app/alerts       │   │  app/core        │
│ (E-Mail-Templ.,  │   │  (rent, payment,  │   │  (engines:       │
│  notification_   │   │   substance)      │   │   portfolio,     │
│  engine)         │   │                   │   │   forecast,      │
└───────┬──────────┘   └─────────┬────────┘   │   real_estate,   │
        │                      │              │   nk, cashflow,  │
        │                      │              │   rentability)   │
        │                      │              └────────┬────────┘
        │                      │                       │
        └──────────────────────┼───────────────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │  app/data                │
                  │  db, bank_collector,     │
                  │  price_service,          │
                  │  event_detector,         │
                  │  dedup                   │
                  └────────────┬─────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │  app/banking             │
                  │  BankAdapter (ABC)       │
                  │  DemoClient, EnableBanking│
                  │  Client, FinTSAdapter,   │
                  │  CsvAdapter              │
                  └──────────────────────────┘
                               │
                  ┌────────────▼─────────────┐
                  │  External:  Banken,      │
                  │  yfinance, OpenFIGI,     │
                  │  SMTP-Server             │
                  └──────────────────────────┘
```

### 1.1 Warum diese Struktur?

| Anforderung                            | Architektur-Antwort                                    |
| -------------------------------------- | ------------------------------------------------------ |
| „Read-only, sicher gegen Bankänderungen" | `banking/`-Layer kennt **nur** BankAdapter-Interface  |
| „Konfigurierbar ohne Code-Änderungen"  | `core/` ist pure functions + Pydantic-Config          |
| „Deterministische Tests ohne Internet" | Alle Externals hinter Interfaces + `app/data/`-Mocks  |
| „Idempotente Migrationen"              | `migrations/*.sql` + `schema_migrations`-Tracking      |
| „Append-only Audit-Trail"              | Events werden niemals mutiert, nur `ack` markiert      |

---

## 2. Layer-Regeln

Diese Regeln sind **nicht** nur Konvention — sie werden vom `pyproject.toml` (Ruff-Konfiguration) und in CI erzwungen.

### 2.1 Erlaubte Importe pro Layer

| Layer             | Darf importieren                                               | Darf NICHT importieren                        |
| ----------------- | -------------------------------------------------------------- | ---------------------------------------------- |
| `app/banking/`    | `base`, `core/`-Datentypen, `config_loader`, `logger`         | `app/data/`, `app/notifications/`, `app/alerts/`, `app/inbox/` |
| `app/data/`       | `banking/`, `core/`, `config_loader`, `logger`                 | `app/notifications/`, `app/alerts/`, `app/inbox/`, `app/main.py` |
| `app/core/`       | `config_loader`, `logger`, `datetime`/Standard-Lib            | `app/banking/`, `app/data/`, `app/notifications/`, `app/alerts/`, `app/inbox/` |
| `app/alerts/`     | `core/`, `data/db` (nur lesend), `config_loader`, `logger`     | `app/banking/`, `app/notifications/`, `app/inbox/` |
| `app/notifications/` | `core/`, `data/`, `config_loader`, `logger`, `templates`     | `app/banking/`, `app/alerts/`, `app/inbox/`   |
| `app/inbox/`      | `core/`, `data/db` (lesend + schreibend), `config_loader`, `logger` | `app/banking/`, `app/alerts/`, `app/notifications/` |
| `app/cli.py`      | alles                                                          | —                                             |
| `app/main.py`     | alles (einziger Ort für Scheduler-Instanziierung)              | —                                             |

> **Hinweis `app/inbox/`:** Die Inbox-Schicht darf `data/db` schreibend nutzen (für `receipts` + `receipt_tags`), aber **keine** Bank-Adapter direkt kennen. Das Bank-Matching erfolgt über SQL-Lesen von `transactions` (in `transaction_matcher.py`), nicht durch Import der `banking/`-Adapter.

### 2.2 Globale Konstanten vermeiden

```python
# FALSCH
DEFAULT_CURRENCY = "EUR"     # globale Mutation möglich

# RICHTIG
def calculate(settings: AppSettings) -> Decimal:
    return settings.forecast.baseline * (1 + Decimal("0.06"))
```

### 2.3 Logger-Konvention

```python
import logging
logger = logging.getLogger(__name__)   # NICHT logging.getLogger("finanzhub")
```

`logging.getLogger(__name__)` ergibt automatisch `app.banking.csv_adapter` o. Ä. — so können Filter gezielt pro Modul greifen.

### 2.4 Sensible Felder nie loggen

`app/logger.py` registriert einen Filter, der diese Felder aus Log-Records entfernt:

```python
SENSITIVE_FIELDS = {"password", "pin", "iban", "token", "api_key", "secret"}
```

Eigene Felder können in `settings.yaml` ergänzt werden:

```yaml
logging:
  sensitive_fields:
    - steuer_id
    - kreditkartennummer
```

---

## 3. Datenmodell & Migrationen

### 3.1 ER-Diagramm

```
                ┌──────────────┐
                │   accounts   │  ◄─────────┐
                │──────────────│            │
                │ id           │            │
                │ bank_name    │            │
                │ iban         │            │
                │ name         │            │
                │ type         │            │
                │ last_synced  │            │
                └──────┬───────┘            │
                       │                    │
                       │ 1:N                │
                       ▼                    │
                ┌──────────────┐            │
                │ transactions │            │
                │──────────────│            │
                │ id           │            │
                │ account_id   │            │
                │ booking_date │            │
                │ amount       │            │
                │ purpose      │            │
                │ counterparty │            │
                │ hash (UNIQUE)│            │
                └──────────────┘            │
                                            │
                ┌──────────────┐            │
                │   positions  │            │
                │──────────────│            │
                │ id           │            │
                │ isin         │            │
                │ name         │            │
                │ anzahl       │            │
                │ einstands-   │            │
                │   preis      │            │
                │ last_price   │            │
                │ last_synced  │            │
                └──────────────┘            │
                                            │
                ┌──────────────┐            │
                │  snapshots   │            │
                │──────────────│            │
                │ id           │            │
                │ recorded_at  │            │
                │ net_worth    │            │
                │ bank_total   │            │
                │ sec_total    │            │
                │ re_equity    │            │
                └──────────────┘            │
                                            │
                ┌──────────────┐            │
                │    events    │            │
                │──────────────│            │
                │ id           │            │
                │ type         │            │
                │ severity     │            │
                │ detected_at  │            │
                │ payload(JSON)│            │
                │ acked        │            │
                │ UNIQUE(type, │            │
                │   dedup_key) │            │
                └──────────────┘            │
                                            │
                ┌──────────────┐            │
                │ notification │            │
                │    _log      │            │
                │──────────────│            │
                │ id           │            │
                │ template     │            │
                │ recipients[] │            │
                │ sent_at      │            │
                │ success      │            │
                │ error        │            │
                └──────────────┘            │
                                            │
                ┌──────────────┐            │
                │  rent_       │            │
                │  expected    │            │
                │──────────────│            │
                │ property     │            │
                │ period       │            │
                │ amount       │            │
                │ tenant       │            │
                │ UNIQUE(      │            │
                │  property,   │            │
                │  period)     │            │
                └──────────────┘            │
                                            │
                ┌──────────────┐            │
                │  prices      │            │
                │──────────────│            │
                │ isin         │            │
                │ price        │            │
                │ currency     │            │
                │ fetched_at   │            │
                └──────────────┘            │
                                            │
                ┌──────────────┐            │
                │  schema_     │            │
                │  migrations  │            │
                │──────────────│            │
                │ version      │            │
                │ applied_at   │            │
                └──────────────┘            │
```

### 3.2 Migrationen schreiben

Neue Datei `migrations/00X_<name>.sql`:

```sql
-- 00X_add_field_x.sql
ALTER TABLE accounts ADD COLUMN custody BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX idx_accounts_custody ON accounts(custody);
```

Wichtig:

- **Idempotent**: `IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS` (in MySQL/PG)
- **Keine DROP TABLE** — nur soft-deprecate
- **Backfill** in einer separaten Migration
- **Tester**: Tabelle `schema_migrations` trackt die angewendete Version

Trigger für `app/data/db.py`:

```python
async def apply_migrations(engine):
    applied = await fetch_applied_versions(engine)
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        version = path.stem
        if version in applied:
            continue
        sql = path.read_text()
        await engine.execute(text(sql))
        await engine.execute(
            text("INSERT INTO schema_migrations (version) VALUES (:v)"),
            {"v": version},
        )
```

### 3.3 SQLite vs. PostgreSQL

`app/data/db.py` enthält `_adapt_sql_for_sqlite()`, das automatisch:

| PostgreSQL          | SQLite (Test)              |
| ------------------- | -------------------------- |
| `SERIAL`            | `INTEGER PRIMARY KEY AUTOINCREMENT` |
| `TIMESTAMPTZ`       | `TIMESTAMP`                |
| `JSONB`             | `TEXT`                     |
| `BOOLEAN`           | `INTEGER` (0/1)            |
| `DISTINCT ON (x)`   | Sub-Query mit `MAX(x)`     |

Dies ermöglicht Tests gegen In-Memory-SQLite bei voller PG-Kompatibilität in Produktion.

---

## 4. Module im Detail

### 4.1 `app/banking/` — Bank-Adapter

#### `base.py` — `BankAdapter` ABC

```python
class BankAdapter(ABC):
    @abstractmethod
    def authenticate(self) -> None: ...

    @abstractmethod
    def fetch_accounts(self) -> list[BankAccount]: ...

    @abstractmethod
    def fetch_transactions(
        self, account_id: str, since: date
    ) -> list[BankTransaction]: ...

    @abstractmethod
    def fetch_balances(self, account_id: str) -> Decimal: ...
```

Jeder Adapter MUSS:

- `RuntimeError` werfen, wenn der externe Service nicht erreichbar ist
- `BankAuthError`, `BankRateLimitError` für spezifische Fehler­szenarien
- Idempotent sein — derselbe `since`-Zeitpunkt liefert konsistente Daten
- **Keine** Retries implementieren (zentral in `bank_collector.py`)

#### Demo-Client

`demo_client.py` liefert deterministische Test-Daten (Seed 42), damit CI-Tests reproduzierbar laufen.

### 4.2 `app/core/` — Pure Engines

Alle Engines sind **pure functions** ohne Side-Effects. Input = Pydantic-Modelle, Output = Decimal/Pydantic.

#### `portfolio_engine.py`

```python
def calculate(
    balances: list[BalanceRow],
    positions: list[Position],
    properties: list[RealEstate],
) -> PortfolioSnapshot: ...
```

- Aggregiert Bank­bestände, Depot-Marktwerte, Immobilien-Equity
- Sortiert nach Liquidität (Bank → Depot → RE)
- Berücksichtigt verbleibende Tilgung (über `real_estate_model.equity()`)

#### `forecast_engine.py`

```python
def forecast(
    *,
    current_net_worth: Decimal,
    monthly_savings: Decimal,
    expected_return: Decimal,
    inflation: Decimal,
    years: int = 30,
) -> list[YearlyProjection]: ...
```

- Deterministische Berechnung: `NW(t) = NW(t-1) * (1+r) + 12*S - I`
- `expected_return` als Dezimal, nicht Prozent (`0.06`, nicht `6`)
- Edge cases: `years < 1` → leere Liste, `monthly_savings < 0` wird zugelassen (Vermögens­verzehr)

#### `real_estate_model.py`

```python
def annuity(principal: Decimal, rate: Decimal, years: int) -> Decimal:
    """Standard-Annuitätenformel."""

def equity(
    *,
    current_value: Decimal,
    restschuld: Decimal,
    payback_until: date,
) -> Decimal: ...
```

- Exakte Berechnung mit `Decimal` (keine `float`-Rundung)
- Kein Interpolation — entweder exakt oder None (für unzureichende Daten)

#### `nk_calculator.py`

Berechnung der 4 Umlageschlüssel:

| Schlüssel | Formel                                          |
| --------- | ----------------------------------------------- |
| `m²`      | `kosten * anteil_m² / summe_m²`                 |
| `personen`| `kosten * anteil_personen / summe_personen`     |
| `verbrauch`| `kosten * anteil_verbrauch / summe_verbrauch`  |
| `pauschal`| `kosten / anzahl_einheiten`                     |

Plus `summenprobe` — Summe aller Anteile muss ≈ Gesamtkosten sein (Toleranz: 0,01 €).

#### `cashflow_engine.py`

Berechnet 12-Monats-Liquiditäts­planung:

```
month[i] = month[i-1]
         + monthly_income[i]
         - fixed_costs[i]
         - loan_payments[i]
         + expected_rent[i]
```

#### `rentability_engine.py`

Folgende Kennzahlen:

| KPI                       | Formel                                            |
| ------------------------- | ------------------------------------------------- |
| `brutto_rendite`          | `jahres_miete / kaufpreis`                        |
| `netto_rendite`           | `(jahres_miete - bewirtschaftung) / eigenkapital` |
| `cash_on_cash`            | `jahres_miete / eigenkapital`                     |
| `peters_formel`           | `(jahres_miete - 0.20*kp) / 0.80*kp * 100`        |
| `roi_tax_adjusted`        | Berücksichtigt AfA und Steuerlast                 |
| `irr_10y`                 | Interner Zinsfuß 10-Jahres-Horizont                |

### 4.3 `app/data/` — IO, Detection, Caching

#### `bank_collector.py`

```python
def collect_all(
    adapters: list[BankAdapter],
    db: Engine,
    retry_policy: RetryPolicy = RetryPolicy(),
) -> CollectionResult: ...
```

Workflow:

1. Pro Adapter: `authenticate()` mit Retry (exponential backoff)
2. `fetch_accounts()` → upsert in `accounts` (matched per `(bank_name, iban)`)
3. `fetch_transactions(since=last_synced)` → dedupliziert via SHA-256-Hash von `(date, amount, purpose, counterparty)`
4. `fetch_balances()` → Snapshot schreiben

#### `event_detector.py`

14+ Ereignistypen:

| Typ                     | Trigger                                   |
| ----------------------- | ----------------------------------------- |
| `rent_late`             | Erwartete Miete nicht eingegangen         |
| `rent_overpaid`         | Mehr Miete als erwartet                   |
| `rent_partial`          | Teilbetrag der Miete                      |
| `rent_split`            | Miete auf mehrere Buchungen verteilt      |
| `duplicate_charge`      | Zwei identische Buchungen in 7 Tagen      |
| `unusual_high`          | Buchung > 3× Durchschnitt der letzten 90 Tage |
| `new_recurring`         | Neuer Dauerauftrag erkannt                |
| `substance_decline`     | Netto­vermögen < 20% und < 30 Tage Historie |
| `consecutive_decline`   | 3+ Monate in Folge Vermögens­rückgang     |
| `loan_payoff_milestone` | Restschuld fällt unter 25%                |
| `property_value_drop`   | Geschätzter Marktwert sinkt > 5% in Q.    |
| `forecast_below_target` | Forecast im Renteneintrittsalter < X       |
| `cashflow_negative`     | Geplanter Cashflow wird negativ           |
| `mail_send_failed`      | Notification-Versand fehlgeschlagen       |

Alle Detektoren geben `list[EventCandidate]` zurück, `event_detector` dedupliziert und persistiert.

#### `price_service.py`

- Primär: `yfinance` (optional — fehlt → WARNING, kein Crash)
- Fallback: `OpenFIGI` (Mapping ISIN → Ticker)
- Cache: 1 h TTL in Tabelle `prices`
- `STATIC_ISIN_MAP` als Hardcoded-Fallback für gängige deutsche ETFs (Aktualisierung halbjährlich)

### 4.4 `app/alerts/` — Höhere Logik

| Modul               | Aufgabe                                                       |
| ------------------- | ------------------------------------------------------------- |
| `rent_matcher.py`   | Vergleicht `rent_expected` mit `transactions`-Aggregat       |
| `payment_monitor.py`| Statistische Anomalie-Erkennung (Z-Score, IQR)               |
| `substance_monitor.py`| Vermögens­verzehr-Detection (Schwellwert + Konsekutiv-Monate) |

### 4.5 `app/notifications/` — Mail + Templates

#### `engine.py`

```python
def run_due(now: datetime) -> list[NotificationResult]:
    """Alle fälligen Cron-Jobs ausführen, senden, loggen."""

def send_test(template_name: str, recipient: str) -> NotificationResult:
    """Render Test, send via Mail, log to notification_log."""
```

#### `config.py` (Template-Verzeichnis)

Lädt alle `*.html.j2` aus `app/templates/`, validiert die Sektionen `{% block content %}`.

### 4.6 `app/cli.py` — Click-Interface

Verwendet `Click 8.x` mit folgenden Konventionen:

- **Exit-Codes** zentral in `app/exit_codes.py`
- **Lazy imports** für schwere Module (yfinance, EnableBankingClient)
- **`--config-dir`**, **`--output-dir`**, **`--verbose`** als globale Flags
- **Rich-Output** für `wealth`, `forecast` (Tabulate)
- **JSON-Output** mit `--json` für Skripting

### 4.7 `app/main.py` — Bootstrap

- **Config-Auto-Init**: `_ensure_config_dir()` kopiert beim ersten Start alle `config.example/*`-Dateien nach `/app/config/`, wenn dort noch keine YAML-Dateien liegen. So funktioniert ein leerer Volume-Mount sofort.
- Lädt `settings.yaml` zuerst, validiert via Pydantic
- Instanziiert Engine + DB-Pool
- Startet APScheduler mit konfigurierten Cron-Jobs
- Signal-Handler: `SIGTERM` → `scheduler.shutdown(wait=False)`, dann `engine.dispose()`

### 4.8 `app/inbox/` — Beleg-Inbox

Verarbeitet eingehende E-Mails, extrahiert Kassenbon-Daten via KI und matcht sie gegen Banktransaktionen. Module:

| Datei                       | Verantwortung                                            |
| --------------------------- | --------------------------------------------------------- |
| `mail_fetcher.py`           | IMAP-Polling, Whitelist, MIME-Filter, Header-Parsing     |
| `image_converter.py`        | JPEG/PNG/WEBP/HEIC → PDF (via `img2pdf` + `pillow-heif`) |
| `receipt_extractor.py`      | LM Studio / Ollama / OpenAI / Anthropic — JSON-Extraktion |
| `transaction_matcher.py`    | 5-stufiges Scoring (Datum ±3d, Betrag, Händler, …)       |
| `attachment_handler.py`     | Routing: Original speichern, konvertiertes PDF, Hash     |
| `inbox_engine.py`           | Orchestrator mit State-Machine (pending → extracted → matched) |

**Wichtige Designentscheidungen:**

- **Provider-Fallback-Kette**: `lmstudio → anthropic → openai` (lokal → Cloud) — siehe `receipt_extractor._build_provider_chain()`
- **Validierung der KI-Antwort**: Betrag wird auf 0–100.000 € geclampt, Datum darf nicht in der Zukunft liegen, Konfidenz auf 0.0–1.0 normalisiert
- **Defensive Whitelist**: `inbox_engine` prüft Whitelist UNABHÄNGIG vom `mail_fetcher` (doppelt-geprüft, da Tests den Fetcher mocken)
- **Original zuerst**: Anhang wird **immer** im Original-Format gespeichert, **bevor** KI-Extraktion stattfindet — bei Fehler in der KI ist das Original audit-fähig
- **Multimodal-Pflicht**: `receipt_extractor.__init__` warnt, wenn der Modell-Name nicht auf `vl`/`vision`/`llava`/`4o`/`haiku`/`opus`/`sonnet` matcht
- **DB-Schema**: zwei Tabellen (`receipts`, `receipt_tags`) mit 4 Indizes; siehe `migrations/005_add_receipts.sql`
- **Scheduler-Integration**: `build_scheduler(inbox_poll=True, inbox_poll_seconds=60)` registriert Job mit `IntervalTrigger`, `max_instances=1`, `coalesce=True` — keine Doppel-Polling bei Überlappung

**Tests:** 53 neue Tests (5 Dateien in `tests/unit/` + `tests/integration/test_inbox_engine.py`). Detail-Doku: [INBOX.md](INBOX.md).

### 4.9 `app/web/` — Web-UI Dashboard

Flask-basiertes Dashboard mit Chart.js und Passwort-Login. Läuft in einem **Daemon-Thread** parallel zum Scheduler.

| Datei                             | Verantwortung                                  |
| --------------------------------- | ---------------------------------------------- |
| `server.py`                       | Flask-App, 5 Routes + DB-Queries               |
| `auth.py`                         | Session-Login, Passwort aus `WEB_PASSWORD`     |
| `static/web.css`                  | Minimales CSS (kein Framework)                 |
| `templates/web/layout.html`       | Basis-Layout mit Navigation                    |
| `templates/web/dashboard.html`    | Übersicht: Vermögen, Chart, Letzte Buchungen   |
| `templates/web/transactions.html` | Buchungsliste mit Zeitfilter (7d/30d/90d/1J)   |
| `templates/web/inbox.html`        | Beleg-Inbox mit Status-Filter                  |
| `templates/web/settings.html`     | Config-Anzeige (read-only)                     |
| `templates/web/login.html`        | Login-Seite                                    |

**Auth:** Einfaches Shared-Password aus `WEB_PASSWORD` env. Wenn nicht gesetzt: temporäres Passwort im Log (`WARNING`).

**Steuerung via Env-Vars:**
- `WEB_ENABLED=true` – Web-UI aktivieren (default: true)
- `WEB_PORT=8080` – Port (default: 8080)
- `WEB_HOST=0.0.0.0` – Bind-Addresse (default: 0.0.0.0)
- `WEB_PASSWORD=<pass>` – Login-Passwort (sonst: temporär im Log)

---

## 5. FinanzHub erweitern

### 5.1 Neuen Bank-Adapter hinzufügen

**Beispiel:** Wir fügen einen `MockAdapter` für lokale Tests hinzu.

**Schritt 1:** `app/banking/mock_adapter.py` anlegen

```python
from __future__ import annotations
from datetime import date
from decimal import Decimal
from .base import BankAdapter, BankAccount, BankTransaction, BankBalance


class MockAdapter(BankAdapter):
    """In-Memory-Adapter für Tests und Demos."""

    def __init__(self, name: str, config: dict):
        self._name = name
        self._config = config

    def authenticate(self) -> None:
        # keine Auth nötig
        pass

    def fetch_accounts(self) -> list[BankAccount]:
        return [
            BankAccount(
                external_id="acc-1",
                iban="DE00000000000000000000",
                name="Mock-Konto",
                type="giro",
                bank_name=self._name,
            )
        ]

    def fetch_transactions(
        self, account_id: str, since: date
    ) -> list[BankTransaction]:
        return []

    def fetch_balances(self, account_id: str) -> BankBalance:
        return BankBalance(
            account_id=account_id,
            available=Decimal("0"),
            booked=Decimal("0"),
            as_of=date.today(),
        )
```

**Schritt 2:** Registrierung in `app/banking/__init__.py`

```python
def build_adapter(bank_config: dict) -> BankAdapter:
    t = bank_config["type"]
    if t == "demo":
        return DemoClient(**bank_config)
    if t == "enable_banking":
        return EnableBankingClient(**bank_config)
    if t == "fints":
        return FinTSAdapter(**bank_config)
    if t == "csv":
        return CsvAdapter(**bank_config)
    if t == "mock":                                # NEU
        return MockAdapter(**bank_config)          # NEU
    raise ValueError(f"Unbekannter Bank-Typ: {t}")
```

**Schritt 3:** Test in `tests/unit/test_banking_adapters.py`

```python
def test_mock_adapter_fetch_accounts():
    adapter = MockAdapter("mock-bank", {})
    accounts = adapter.fetch_accounts()
    assert len(accounts) == 1
    assert accounts[0].iban == "DE00000000000000000000"
```

**Schritt 4:** Konfiguration in `config.example/banks.yaml`

```yaml
banks:
  - name: mock
    type: mock
```

### 5.2 Neuen Event-Typ hinzufügen

**Schritt 1:** Konstanten in `app/data/event_detector.py`

```python
class EventType:
    RENT_LATE = "rent_late"
    RENT_OVERPAID = "rent_overpaid"
    # ... bestehend ...
    LOAN_EARLY_REPAID = "loan_early_repaid"  # NEU
```

**Schritt 2:** Detektor implementieren

```python
def detect_loan_early_repaid(
    settings: AppSettings,
    loans: list[LoanSnapshot],
) -> list[EventCandidate]:
    candidates = []
    for loan in loans:
        if loan.restschuld <= Decimal("0") and loan.paid_off_at:
            candidates.append(
                EventCandidate(
                    type=EventType.LOAN_EARLY_REPAID,
                    severity="info",
                    detected_at=_utcnow(),
                    payload={
                        "loan_id": loan.id,
                        "property": loan.property_name,
                        "paid_off_at": loan.paid_off_at.isoformat(),
                    },
                    dedup_key=f"loan_early_repaid:{loan.id}",
                )
            )
    return candidates
```

**Schritt 3:** In `detect_all()` einhängen

```python
def detect_all(settings: AppSettings, **deps) -> list[Event]:
    candidates = []
    candidates.extend(detect_rent_late(...))
    candidates.extend(detect_payment_anomalies(...))
    candidates.extend(detect_substance_decline(...))
    candidates.extend(detect_loan_early_repaid(...))  # NEU
    return _deduplicate_and_persist(candidates, settings)
```

**Schritt 4:** Template `app/templates/loan_early_repaid.html.j2`

```html
{% extends "base.html.j2" %}
{% block content %}
  <h1 style="color:#16a34a">Darlehen zurückgezahlt</h1>
  <p>Das Darlehen für <strong>{{ event.payload.property }}</strong>
     wurde am {{ event.payload.paid_off_at }} vollständig zurückgezahlt.</p>
{% endblock %}
```

**Schritt 5:** Test in `tests/unit/test_event_detector.py`

```python
def test_loan_early_repaid_detected():
    loans = [LoanSnapshot(id="L1", restschuld=Decimal("0"),
                          paid_off_at=date(2026, 6, 1),
                          property_name="Berlin")]
    events = detect_loan_early_repaid(settings, loans)
    assert len(events) == 1
    assert events[0].type == "loan_early_repaid"
    assert events[0].dedup_key == "loan_early_repaid:L1"
```

### 5.3 Neues CLI-Kommando

```python
# in app/cli.py
@cli.command()
@click.option("--property", required=True, help="Property-Name")
@click.option("--json", "as_json", is_flag=True, help="JSON-Output")
def valuation(property: str, as_json: bool) -> None:
    """Aktuellen Schätzwert einer Immobilie anzeigen."""
    from app.core.real_estate_model import estimate_value
    from app.config_loader import load_assets

    assets = load_assets()
    re = next((p for p in assets.immobilien if p.name == property), None)
    if re is None:
        click.echo(f"Unbekannte Immobilie: {property}", err=True)
        sys.exit(EXIT_USAGE)

    result = estimate_value(re)
    if as_json:
        click.echo(json.dumps(result.model_dump(), indent=2))
    else:
        click.echo(f"{property}: {result.estimated_value:,.2f} € "
                   f"(± {result.uncertainty:,.0f} €)")
```

Registrierung erfolgt automatisch via `@cli.command()`.

### 5.4 Neues Template

1. Datei `app/templates/<name>.html.j2` anlegen
2. Sektionen verwenden, die in `base.html.j2` definiert sind: `{% block content %}`, optional `{% block footer %}`
3. Inline-CSS nutzen (für maximale Mail-Client-Kompatibilität)
4. Testen: `finanzhub notify test <name>`

### 5.5 Notification-Schedule anpassen

`config/notifications.yaml`:

```yaml
notifications:
  - name: weekly_digest
    template: weekly_digest
    schedule: "0 8 * * 1"          # Mo 08:00
    recipients: [ich@example.com, partner@example.com]
    enabled: true
    conditions:
      min_net_worth: 100000
      severity_threshold: warning
```

Cron-Syntax: 5 Felder (`min hour day month weekday`), Zeitzone via `TZ` env.

### 5.6 Neuen KI-Provider für die Inbox hinzufügen

**Schritt 1:** Provider-Klasse in `app/inbox/receipt_extractor.py` anlegen. Kontrakt:

```python
class MyProvider:
    def __init__(self, config: MyProviderConfig) -> None: ...
    def extract(self, image_or_pdf_path: Path) -> ReceiptExtractionResult: ...
```

**Schritt 2:** Config-Schema in `app/config_loader.py` (Pydantic) definieren:

```python
class MyProviderExtractionConfig(BaseModel):
    enabled: bool = False
    api_key: str = ""
    model: str = "my-model-vl"
    endpoint: str = "https://api.example.com/v1/extract"
```

**Schritt 3:** Provider in der Factory-Liste `receipt_extractor._build_provider_chain()` registrieren.

**Schritt 4:** Tests in `tests/unit/test_receipt_extractor.py` ergänzen. Pattern siehe `TestOpenAIProvider` — `_FakeResponse` und `mocker.patch` reichen.

**Schritt 5:** Doku in [INBOX.md §4](INBOX.md#4-ki-provider-wählen) ergänzen.

---

## 6. Tests & Qualität

### 6.1 Test-Pyramide

```
            ┌─────────────────────┐
            │  E2E / CLI-Tests    │   3 Suites, ~20 Tests
            ├─────────────────────┤
            │  Integration        │   DB + Engines, ~50 Tests
            ├─────────────────────┤
            │  Unit-Tests         │   Pure Functions, ~110 Tests
            └─────────────────────┘
```

> **Stand 2026-06:** **183 Tests**, alle grün, in ~1,7 s Laufzeit.

### 6.2 Konventionen

| Aspekt             | Konvention                                                |
| ------------------ | --------------------------------------------------------- |
| Datei­namen        | `test_<module>.py`                                        |
| Klassen            | `Test<Subject>`                                           |
| Methoden           | `test_<scenario>_<expected_outcome>`                      |
| Fixtures           | `conftest.py` (geräteübergreifend), `tests/fixtures/` (Daten) |
| Mocks              | `pytest-mock` (`mocker` Fixture), **niemals** `unittest.mock.patch` |
| Time               | `freezegun.freeze_time("2026-06-15")` für deterministische Daten |
| Externe Services   | Niemals echtes HTTP, SMTP, DB-Connections                  |
| DB                 | In-Memory-SQLite, Migrationen automatisch anwenden        |
| Zufall             | `random.seed(42)` wo nötig                                |

### 6.3 Beispiel-Test

```python
# tests/unit/test_rentability_engine.py
from decimal import Decimal
from freezegun import freeze_time
from app.core.rentability_engine import compute_kpis
from app.config_loader import RealEstate


@freeze_time("2026-06-15")
def test_brutto_rendite_for_berlin_mitte():
    re = RealEstate(
        name="Berlin-Mitte",
        kaufpreis=Decimal("450000"),
        eigenkapital=Decimal("120000"),
        wert=Decimal("600000"),
        value_growth=Decimal("0.025"),
        mieteinnahmen=Decimal("1800"),
        nebenkosten=Decimal("320"),
        rate=Decimal("950"),
        zinssatz=Decimal("0.031"),
        tilgung=Decimal("0.02"),
        restschuld=Decimal("270000"),
        notar=Decimal("8500"),
        grunderwerbsteuer=Decimal("22500"),
        makler=Decimal("13500"),
    )

    kpis = compute_kpis(re)

    assert kpis.brutto_rendite == pytest.approx(0.0480, abs=1e-4)
    assert kpis.netto_rendite > kpis.brutto_rendite  # Leverage-Effekt
```

### 6.4 Coverage-Anforderungen

| Bereich             | Mindest-Coverage | Aktuell |
| ------------------- | ---------------- | ------- |
| `app/core/`         | 90 %             | 82-100 % |
| `app/data/`         | 70 %             | ~76 %   |
| `app/banking/`      | 60 %             | 50-80 % |
| `app/notifications/`| 60 %             | ~70 %   |
| `app/alerts/`       | 70 %             | ~85 %   |
| `app/inbox/`        | 60 %             | ~75 %   |
| **Gesamt**          | **60 %**         | **73 %** |

### 6.5 Linting

```bash
ruff check app/ tests/        # schneller Lint
ruff format app/ tests/       # Auto-Format (PEP 8, kompatibel mit Black)
```

Ruff-Regeln: `E, F, W, I, N, B, UP, C4, SIM` (siehe `pyproject.toml`).

### 6.6 Pre-Commit-Hook (empfohlen)

`.pre-commit-config.yaml`:

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: check-yaml
      - id: end-of-file-fixer
      - id: trailing-whitespace
```

Install: `pip install pre-commit && pre-commit install`.

---

## 7. Style-Guide

### 7.1 Python-Stil

| Thema                | Regel                                                   |
| -------------------- | ------------------------------------------------------- |
| Python-Version       | 3.10+ Syntax (z. B. `match`, `\|` für Union)            |
| Type-Hints           | **Immer** (Funktions­signatur + öffentliche Klassen)     |
| Docstrings           | Google-Style, deutsch (Konsistenz)                      |
| Zeilenlänge          | 100 Zeichen (Ruff `E501` ignoriert)                    |
| Strings              | Doppelte Anführungszeichen, f-strings für Interpolation |
| Imports              | Absolute (`from app.core import X`), sortiert via Ruff  |
| Tests                | `pytest`, deutsche Test-Namen erlaubt                   |

### 7.2 Docstring-Template

```python
def function_name(arg1: str, arg2: Decimal) -> Result:
    """Kurze Zusammenfassung in einem Satz.

    Längere Beschreibung, falls nötig. Mehrere Absätze erlaubt.

    Args:
        arg1: Beschreibung des ersten Parameters.
        arg2: Beschreibung des zweiten Parameters.

    Returns:
        Beschreibung des Rückgabewerts.

    Raises:
        ValueError: Wann immer dieser Fehler auftritt.
    """
```

### 7.3 Commit-Konventionen

Wir folgen **Conventional Commits** auf Deutsch:

```
feat: NK-Abrechnung um IRR-Kennzahl erweitert
fix: Demo-Client liefert bei seed=42 immer gleiche Buchungen
docs: Inbetriebnahmeanleitung um systemd-Service ergänzt
test: rent-matcher deckt Mehrfach-Buchung ab
refactor: bank-collector in async-Funktionen zerlegt
chore: ruff-Version auf 0.6.0 angehoben
```

Prefixes: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`, `ci`, `build`.

### 7.4 Branch-Naming

- `feat/<ticket>-<slug>` (z. B. `feat/FIN-42-rent-overpaid`)
- `fix/<slug>` (z. B. `fix/double-detection-rent`)
- `docs/<slug>`, `chore/<slug>`, `test/<slug>`

---

## 8. Debugging & Logging

### 8.1 Log-Levels

| Level    | Verwendung                                                  |
| -------- | ----------------------------------------------------------- |
| DEBUG    | Detaillierte Diagnose (Datenbank-Queries, Adapter-Requests) |
| INFO     | Normale Workflow-Fortschritte (Pull, Forecast, Mail-Send)   |
| WARNING  | Behebbare Probleme (Cache-Miss, optionale Dep fehlt)        |
| ERROR    | Fehler, die die aktuelle Operation abbrechen               |
| CRITICAL | App kann nicht starten                                      |

### 8.2 Log-Verzeichnis

```
output/
├── logs/
│   ├── finanzhub.log          # aktuelles Log (rotiert)
│   ├── finanzhub.log.2026-06-14
│   └── ...
├── exports/                   # CSV-Exporte
└── reports/                   # gerenderte HTML-Reports
```

### 8.3 Debugging-Tipps

```bash
# Live-Logs in Docker
docker compose logs -f finanzhub

# Spezifisches Modul tracen
LOG_LEVEL=DEBUG python -c "from app.core.portfolio_engine import calculate; ..."

# In Python REPL
import logging
logging.basicConfig(level=logging.DEBUG)
from app.data.bank_collector import collect_all
result = collect_all(...)
```

### 8.4 Häufige Fehlerquellen

| Symptom                                | Ursache                                          |
| -------------------------------------- | ------------------------------------------------ |
| `EmptyResultError` bei Forecast        | `monthly_savings` ist None in Config             |
| Mail geht raus, aber `success=False`   | SMTP-Provider blockiert Port 587                |
| `BankAuthError: invalid_consent`       | `consent_id` abgelaufen, neu in enable-banking  |
| `psycopg2.errors.UndefinedTable`       | Migrationen nicht ausgeführt → `finanzhub init` |
| Doppelte Events                        | `dedup_key` nicht eindeutig → neu denken         |

---

## 9. Release- & Versions­prozess

### 9.1 Semantic Versioning

- `MAJOR.MINOR.PATCH` (z. B. `0.7.3`)
- `0.x.y` → Pre-1.0: API kann sich ändern
- Backward-Incompatible Changes erfordern MAJOR-Bump

### 9.2 Release-Checkliste

1. [ ] Alle Tests grün (`pytest --cov=app`)
2. [ ] Lint clean (`ruff check`)
3. [ ] `CHANGELOG.md` aktualisiert
4. [ ] `app/__init__.py` `__version__` erhöht
5. [ ] Git-Tag `v0.x.y` erstellt
6. [ ] CI baut und pusht Docker-Image
7. [ ] GitHub-Release mit Notizen erstellt
8. [ ] Migration in `migrations/` mitgeliefert (falls Schema-Änderung)

### 9.3 Beispiel `CHANGELOG.md`

```markdown
## [0.7.3] - 2026-06-15

### Added
- Neues Event `loan_early_repaid` mit Template
- CLI-Befehl `valuation --property <name>`

### Fixed
- `forecast_engine`: Rundungsfehler bei 30-Jahres-Horizont
- `rent_matcher`: Falsche Klassifikation bei Mehrfach-Buchung

### Changed
- yfinance-Import ist nun lazy (kein Crash mehr bei fehlendem Paket)
```

### 9.4 API-Stabilität

Da FinanzHub aktuell eine **interne** Anwendung ist, gilt:

- Interne `app/`-Module sind nicht API-stabil
- Konfigurations-YAMLs sind API-stabil (Breaking Changes → MAJOR-Bump)
- CLI-Kommandos sind API-stabil (Flags dürfen ergänzt, nicht entfernt werden)
- Datenbank-Schema ist **nicht** rückwärtskompatibel (Migrationen nötig)

---

**Weiterführend:**

- [Integrations­dokumentation](INTEGRATION.md) — Bank-APIs, SMTP, Datenbanken
- [Nutzungs­dokumentation](USAGE.md) — Workflows, Rezepte, Fehler­behebung
- [README](../README.md) — Projekt-Übersicht
