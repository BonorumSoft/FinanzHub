# FinanzHub

**FinanzHub** ist ein **self-hosted, on-premise Finanzmanagement-System** für technisch versierte Privatanleger und kleine Vermögensverwaltungen.

Es liest Bankkonten, Depots und Miet­einnahmen automatisiert aus, berechnet Netto­vermögen, Mietrenditen, Cashflow und einen deterministischen Vermögens­forecast, erkennt kritische Ereignisse (z. B. Substanzverzehr, Miet­ausfall, ungewöhnliche Transaktionen) und versendet HTML/Text-E-Mails auf Basis von Jinja2-Templates.

> **Design­prinzipien:** Read-only, Konfiguration statt Code, graceful degradation, idempotent, append-only, no global state, no hardcoded values.

---

## Inhaltsverzeichnis

1. [Funktionsumfang](#1-funktionsumfang)
2. [Schnellstart](#2-schnellstart)
3. [**Inbetriebnahmeanleitung**](#3-inbetriebnahmeanleitung)
4. [**Nutzeranleitung**](#4-nutzeranleitung)
5. [Architektur](#5-architektur)
6. [Entwicklung & Tests](#6-entwicklung--tests)
7. [Fehler­behebung](#7-fehlerbehebung)
8. [Sicherheit & Compliance](#8-sicherheit--compliance)
9. [Roadmap / Status](#9-roadmap--status)
10. [Lizenz](#10-lizenz)

## Ausführliche Dokumentation

Für tiefergehende Informationen siehe die Dokumentation im `docs/`-Verzeichnis:

- **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)** — Entwickler­dokumentation (Architektur, Module, Erweiterung, Tests, Style-Guide)
- **[docs/INTEGRATION.md](docs/INTEGRATION.md)** — Integrations­dokumentation (Bank-APIs, SMTP, Datenbank, Scheduler, Sicherheit)
- **[docs/USAGE.md](docs/USAGE.md)** — Nutzungs­dokumentation (CLI-Referenz, tägliche/wöchentliche/monatliche/jährliche Workflows, Rezepte, Fehlerbehebung)
- **[docs/README.md](docs/README.md)** — Dokumentations-Index

---

## 1. Funktionsumfang

| Modul                    | Funktion                                                                  |
| ------------------------ | ------------------------------------------------------------------------- |
| `bank_collector`         | Multi-Bank-Anbindung (enable-banking, FinTS, CSV, Demo)                  |
| `price_service`          | Live-Kurse via yfinance/OpenFIGI mit 1-h-Cache                            |
| `portfolio_engine`       | Netto­vermögen, Allokation, Liquidität                                    |
| `forecast_engine`        | Deterministischer 30-Jahres-Vermögens­forecast                           |
| `real_estate_model`      | Annuitäten, Restschuld, Equity                                            |
| `nk_calculator`          | Nebenkostenabrechnung mit 4 Schlüsseln + Summen­probe                     |
| `rentability_engine`     | Brutto/Netto-Mietrendite, Peters'che Formel, Steuer-Effekt                |
| `cashflow_engine`        | Liquiditäts­planung 12 Monate                                             |
| `rent_matcher`           | Erwartete vs. tatsächliche Miet­eingänge (bezahlt/ausgefallen/zu viel)    |
| `payment_monitor`        | Doppelte / ungewöhnlich hohe / neue Lastschriften                         |
| `substance_monitor`      | Substanz­verzehr, konsekutive monatliche Vermögens­rückgänge              |
| `event_detector`         | 14+ Ereignistypen, dedupliziert, append-only                              |
| `notification_engine`    | Geplante Reports, HTML/Text-Templates, Mailversand mit Retry              |
| `scheduler`              | APScheduler mit Cron-Jobs (Tages­abschluss, Monats­report, …)             |
| `cli`                    | 15+ Click-Kommandos für manuelle Workflows                                |

---

## 2. Schnellstart

```bash
# 1. Klonen
git clone https://github.com/bonorumsoft/finanzhub.git
cd finanzhub

# 2. Beispielkonfiguration übernehmen
cp -r config.example/ config/
# Passwörter in config/banks.yaml setzen oder Demo-Bank verwenden

# 3. Mitgelieferte Demo-Bank aktivieren
# In config/banks.yaml: `type: demo` (bereits Standard)

# 4. Lokal (Python 3.10+)
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
finanzhub init
finanzhub pull-all
finanzhub wealth
```

Oder mit Docker:

```bash
cp .env.example .env
echo "DB_PASSWORD=$(openssl rand -hex 16)" >> .env
docker compose up -d
docker compose logs -f finanzhub
```

Oder mit **Portainer**: siehe [`docs/PORTAINER.md`](docs/PORTAINER.md) — fertige Stack-Datei `docker-compose.portainer.yml` + Schritt-für-Schritt-Anleitung inkl. Secrets, Backups, Updates.

---

## 3. Inbetriebnahmeanleitung

Diese Anleitung richtet sich an den **Administrator**, der FinanzHub zum ersten Mal auf einem Server (Bare-Metal, VM, NAS, Raspberry Pi 4+, Heimserver) in Betrieb nimmt.

### 3.1 Voraussetzungen prüfen

| Komponente   | Mindest­anforderung                       |
| ------------ | ------------------------------------------ |
| OS           | Linux (Debian 12 / Ubuntu 22.04+), macOS 12+, Windows 11 mit WSL2 |
| CPU          | 2 Kerne                                    |
| RAM          | 1 GB (PostgreSQL: 2 GB empfohlen)          |
| Speicher     | 5 GB + ~50 MB/Monat Historie              |
| Python       | 3.10, 3.11 oder 3.12                      |
| Docker       | 24.0+ (optional, empfohlen)               |
| PostgreSQL   | 14+ (in Docker bereits enthalten)         |

Schnell-Check:

```bash
python3 --version        # >= 3.10
docker --version         # >= 24
df -h /                  # >= 5 GB frei
```

### 3.2 Installations­wege

Sie haben zwei Optionen — **Docker (empfohlen)** oder **bare-metal Python**.

#### 3.2.1 Installation mit Docker

```bash
# 1. Repository klonen
git clone https://github.com/bonorumsoft/finanzhub.git /opt/finanzhub
cd /opt/finanzhub

# 2. .env mit starkem DB-Passwort erzeugen
cat > .env <<EOF
DB_PASSWORD=$(openssl rand -hex 16)
TZ=Europe/Berlin
LOG_LEVEL=INFO
EOF
chmod 600 .env

# 3. Konfiguration anpassen
cp -r config.example/ config/
$EDITOR config/banks.yaml
$EDITOR config/mail.yaml

# 4. Stack starten
docker compose up -d
docker compose ps            # Status prüfen
docker compose logs finanzhub
```

Der Container startet den Scheduler im Vordergrund; die SQLite-/PostgreSQL-Daten werden in Docker-Volumes persistiert.

#### 3.2.2 Bare-Metal-Installation

```bash
# 1. System-Pakete
sudo apt install -y python3.10-venv python3-pip postgresql-client

# 2. Python-Umgebung
python3 -m venv /opt/finanzhub/.venv
cd /opt/finanzhub
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Konfiguration
cp -r config.example/ config/
$EDITOR config/banks.yaml
$EDITOR config/mail.yaml

# 4. PostgreSQL-Datenbank anlegen
sudo -u postgres psql <<SQL
CREATE USER finanzhub WITH PASSWORD 'STRONG_PASSWORD';
CREATE DATABASE finanzhub OWNER finanzhub;
GRANT ALL PRIVILEGES ON DATABASE finanzhub TO finanzhub;
SQL

# 5. .env-Datei
cat > /opt/finanzhub/.env <<EOF
DATABASE_URL=postgresql://finanzhub:STRONG_PASSWORD@localhost:5432/finanzhub
TZ=Europe/Berlin
LOG_LEVEL=INFO
EOF
chmod 600 /opt/finanzhub/.env

# 6. Schema anlegen
export $(grep -v '^#' .env | xargs)
finanzhub init
```

#### 3.2.3 Systemd-Service (optional, für Bare-Metal)

```bash
sudo tee /etc/systemd/system/finanzhub.service > /dev/null <<'EOF'
[Unit]
Description=FinanzHub financial reporting
After=network-online.target postgresql.service
Wants=network-online.target

[Service]
Type=simple
User=finanzhub
Group=finanzhub
WorkingDirectory=/opt/finanzhub
EnvironmentFile=/opt/finanzhub/.env
ExecStart=/opt/finanzhub/.venv/bin/python -m app.main
Restart=on-failure
RestartSec=10s
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/opt/finanzhub/output /opt/finanzhub/logs

[Install]
WantedBy=multi-user.target
EOF

sudo useradd -r -s /usr/sbin/nologin -d /opt/finanzhub finanzhub
sudo chown -R finanzhub:finanzhub /opt/finanzhub
sudo systemctl daemon-reload
sudo systemctl enable --now finanzhub
sudo systemctl status finanzhub
```

### 3.3 Erst­konfiguration

Die Beispielkonfiguration unter `config.example/` ist sofort lauffähig mit der **Demo-Bank** (deterministische Daten, keine echten Konten). Für den Echtbetrieb sind drei Schritte nötig:

#### 3.3.1 Bankzugänge einrichten

`config/banks.yaml` — aktivieren Sie die Adapter, die Sie nutzen möchten.

```yaml
banks:
  - name: sparkasse-demo
    type: demo                       # deterministische Demo-Daten

  - name: sparkasse
    type: enable_banking
    bank_id: "00000000-0000-0000-0000-000000000000"
    consent_id: "<aus enable-banking.de-Konto kopieren>"
    key_path: /secrets/ebanking.pem  # Privater RSA-Schlüssel
    psp_id: "<Ihre Application-ID>"

  - name: ing
    type: fints
    blz: "50010517"
    endpoint: "https://fints.ing.de/fints"
    product_id: "ABCDEF123456"
```

> **Sicherheits­hinweis:** Speichern Sie private Schlüssel und Passwörter niemals unverschlüsselt im Repository. Verwenden Sie den `secrets:`-Mechanismus Ihres Orchestrators oder einen lokalen `keyring`.

#### 3.3.2 Vermögens­werte inventarisieren

`config/assets.yaml`:

```yaml
immobilien:
  - name: Berlin-Mitte
    kaufpreis: 450000
    eigenkapital: 120000
    wert: 600000                       # aktueller Marktwert
    value_growth: 0.025                # 2.5% p.a. Annahme
    mieteinnahmen: 1800                # kalt
    nebenkosten: 320
    rate: 950                          # monatliche Rate
    zinssatz: 0.031
    tilgung: 0.02
    restschuld: 270000
    notar: 8500
    grunderwerbsteuer: 22500
    makler: 13500
    baujahr: 2018

depot:
  - name: MSCI-World-ETF
    isin: IE00B4L5Y983
    anzahl: 120
    einstandspreis: 80.10
    typ: etf
```

#### 3.3.3 Mail-Versand konfigurieren

`config/mail.yaml`:

```yaml
mail:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_user: reports@example.com
  smtp_password: "<app-passwort, niemals Hauptpasswort>"
  use_tls: true
  from_address: reports@example.com

notifications:
  - name: daily_wealth_report
    template: daily_wealth_report
    schedule: "0 22 * * *"             # täglich 22:00
    recipients: [ich@example.com]
    enabled: true
```

### 3.4 Erste Schritte nach der Installation

```bash
# 1. Datenbank initialisieren
finanzhub init

# 2. Konten anbinden
finanzhub pull                     # einzelner Adapter
finanzhub pull-all                 # alle konfigurierten

# 3. Kennzahlen prüfen
finanzhub wealth
finanzhub rent-check 2026-06
finanzhub forecast
finanzhub events detect

# 4. Test-Email senden
finanzhub notify test daily_wealth_report
```

### 3.5 Backup & Restore

```bash
# PostgreSQL
docker compose exec postgres pg_dump -U finanzhub finanzhub \
  | gzip > /backup/finanzhub-$(date +%F).sql.gz

# Wiederherstellen
gunzip -c /backup/finanzhub-2026-06-15.sql.gz \
  | docker compose exec -T postgres psql -U finanzhub -d finanzhub

# Konfiguration versionieren
tar -czf /backup/finanzhub-config-$(date +%F).tar.gz config/
```

Cron-Empfehlung: tägliches DB-Backup, 14-tägige Aufbewahrung (lokal) + verschlüsseltes Offsite-Backup.

### 3.6 Update einspielen

```bash
# Docker
cd /opt/finanzhub
git pull
docker compose build --pull
docker compose up -d
docker compose logs -f finanzhub

# Bare-Metal
cd /opt/finanzhub
git pull
source .venv/bin/activate
pip install -r requirements.txt
finanzhub init    # führt nur neue Migrationen aus (idempotent)
sudo systemctl restart finanzhub
```

> Migrationen sind **idempotent** — `finanzhub init` erkennt bereits angewendete Schritte anhand der `schema_migrations`-Tabelle und überspringt sie.

---

## 4. Nutzeranleitung

Diese Anleitung richtet sich an den **täglichen Anwender** — also Sie selbst oder Personen, die Reports lesen, einzelne Workflows ausführen oder das System pflegen.

### 4.1 Tägliche Workflows

#### 4.1.1 Vermögens­übersicht abrufen

```bash
finanzhub wealth
```

Ausgabe (Beispiel):

```
─────────────────────────────────────────────────────────────────────
 NETTOVERMÖGEN                487 320,55 €
   Banken (3 Konten)          142 815,12 €
   Depot (8 Positionen)       187 230,40 €
   Immobilien-Equity          157 275,03 €
─────────────────────────────────────────────────────────────────────
 LIQUIDITÄT                   142 815,12 €
 OFFENE MIETEN                      0,00 €
 OFFENE NEBENKOSTEN                 0,00 €
─────────────────────────────────────────────────────────────────────
 LETZTER DATENABGLEICH    2026-06-05 14:23
 ERWARTETE ENTWICKLUNG   +1 200 €/Monat
─────────────────────────────────────────────────────────────────────
```

#### 4.1.2 Forecast anzeigen

```bash
finanzhub forecast
finanzhub forecast --years 30 --include-immobilien
```

Erzeugt eine Tabelle mit Jahr, Liquidität, Depot, Immobilien-Equity, Gesamtvermögen, jährlicher Veränderung.

#### 4.1.3 Cashflow prüfen

```bash
finanzhub cashflow --months 12
```

#### 4.1.4 Mieten prüfen

```bash
finanzhub rent-check 2026-06            # Juni 2026
finanzhub rent-check 2026               # alle Monate 2026
finanzhub rent-check                    # aktueller Monat
```

Status: `bezahlt` (Summe passt), `ausgefallen` (Erwartung ≠ Ist), `zu viel` (Überzahlung), `mehrfach` (Splittung).

#### 4.1.5 NK-Abrechnung erstellen

```bash
finanzhub nk --year 2025 --property Berlin-Mitte
```

Erzeugt eine CSV im `output/`-Verzeichnis mit allen 4 Umlageschlüsseln, Summen­probe und Differenz.

#### 4.1.6 Ereignisse anzeigen

```bash
finanzhub events list                   # alle ungelesenen
finanzhub events list --all
finanzhub events detect                 # sofortige Detektion
finanzhub events ack <event_id>
```

#### 4.1.7 Test-Benachrichtigung senden

```bash
finanzhub notify test daily_wealth_report
```

Spart das Warten auf den nächsten Cron-Lauf.

### 4.2 CLI-Befehls­referenz (Auswahl)

| Befehl                                            | Zweck                                      |
| ------------------------------------------------- | ------------------------------------------- |
| `finanzhub init`                                  | Schema anlegen / migrieren                 |
| `finanzhub pull <bank>`                           | Bank-Daten synchronisieren                  |
| `finanzhub pull-all`                              | Alle Banken synchronisieren                |
| `finanzhub wealth`                                | Netto­vermögen anzeigen                     |
| `finanzhub forecast [--years N]`                  | Vermögens­vorschau                         |
| `finanzhub cashflow [--months N]`                 | Liquiditäts­planung                         |
| `finanzhub rent-check [PERIOD]`                   | Miet­eingangs­prüfung                      |
| `finanzhub nk --year Y --property P`              | NK-Abrechnung erstellen                    |
| `finanzhub rentability --property P`              | Rendite-Kennzahlen                         |
| `finanzhub events list [--all]`                   | Ereignisse anzeigen                        |
| `finanzhub events detect`                         | Detektion jetzt ausführen                  |
| `finanzhub events ack <id>`                       | Ereignis quittieren                        |
| `finanzhub notify list`                           | Notification-Log anzeigen                  |
| `finanzhub notify test <template>`                | Test-Email senden                          |
| `finanzhub notify run`                            | Fällige Notifications ausführen            |
| `finanzhub status`                                | System-Status, letzte Sync-Zeit, DB-Größe  |
| `finanzhub --version`                             | Version anzeigen                           |
| `finanzhub --help`                                | Vollständige Hilfe                         |

**Exit-Codes:** `0` = OK, `1` = Anwendungs­fehler, `2` = Usage-Fehler.

### 4.3 Konfiguration anpassen

Alle Konfigurations­dateien sind **YAML** und liegen in `config/` (bzw. `$CONFIG_DIR`). Beispielstruktur:

```
config/
├── settings.yaml        # Logging, Schwellwerte, Pfade
├── banks.yaml           # Bank-Adapter
├── assets.yaml          # Depot, Immobilien
├── income.yaml          # Gehälter, sonstige Einnahmen
├── forecast.yaml        # Szenario-Parameter
├── mail.yaml            # SMTP + Benachrichtigungen
└── notifications.yaml   # Schedules, Empfänger
```

> **Wichtig:** Kommentare sind in YAML erlaubt. Nutzen Sie `#` für Inline-Dokumentation.

#### 4.3.1 Schwellwerte für Alerts

`config/settings.yaml`:

```yaml
vermoegen:
  schwellwert_substanz_tage: 30
  schwellwert_substanz_prozent: 0.20
  schwellwert_konsekutive_monate: 3
```

#### 4.3.2 Forecast-Szenarien

`config/forecast.yaml`:

```yaml
scenarios:
  - name: basis
    depot_rendite: 0.06
    inflation: 0.02
    mietsteigerung: 0.02
  - name: stress
    depot_rendite: -0.02
    inflation: 0.05
    mietsteigerung: 0.00
```

### 4.4 Eigene Templates anlegen

Templates liegen in `app/templates/` und sind **Jinja2** mit Inline-CSS.

Neue Datei `app/templates/my_event.html.j2`:

```html
{% extends "base.html.j2" %}
{% block content %}
  <h1 style="color:#2563eb">{{ event.title }}</h1>
  <p>{{ event.description }}</p>
  <table>...</table>
{% endblock %}
```

Sofort testen:

```bash
finanzhub notify test my_event
```

### 4.5 Häufige Anwendungs­fälle

| Frage                                        | Befehl                                       |
| -------------------------------------------- | -------------------------------------------- |
| „Wie viel Geld habe ich?"                    | `finanzhub wealth`                           |
| „Reicht mein Vermögen bis zur Rente?"        | `finanzhub forecast --years 40`              |
| „Habe ich meine Miete bekommen?"             | `finanzhub rent-check $(date +%Y-%m)`        |
| „Gibt es ungewöhnliche Buchungen?"           | `finanzhub events list`                      |
| „Was hat sich gegenüber letztem Monat verändert?" | Reports automatisch per Mail             |
| „NK-Abrechnung für das Finanzamt"            | `finanzhub nk --year 2025 --property Berlin` |

### 4.6 Daten­schutz-Hinweise

* Alle Daten bleiben **lokal** — kein externer Sync außerhalb der von Ihnen konfigurierten Bank-/Mail-Endpunkte.
* Passwörter, IBANs und PINs werden **nie** geloggt.
* Logs werden in `output/logs/` (oder `$OUTPUT_DIR/logs/`) abgelegt — passen Sie die Retention in `settings.yaml` an.

---

## 5. Architektur

```
┌─────────────────────────────────────────────────────────────┐
│  app/main.py                                                │
│  ┌────────────────────┐   ┌────────────────────────────┐  │
│  │ APScheduler        │   │ Signal handler (SIGTERM)   │  │
│  └─────────┬──────────┘   └──────────────┬─────────────┘  │
│            │                              │                │
│  ┌─────────▼──────────────────────────────▼─────────────┐  │
│  │  CLI (Click)  app/cli.py                            │  │
│  └─────┬───────────┬───────────┬───────────┬────────────┘  │
│        │           │           │           │                │
│  ┌─────▼─────┐ ┌───▼─────┐ ┌───▼─────┐ ┌───▼──────────────┐ │
│  │ banking/  │ │ data/   │ │ core/   │ │ notifications/   │ │
│  │ BankAdapt │ │ price_  │ │ forecast│ │ engine + templ.  │ │
│  │ 4 Adapter │ │ service │ │ portfol │ │                  │ │
│  └─────┬─────┘ └────┬────┘ └────┬────┘ └────────┬─────────┘ │
│        │            │            │               │           │
│        └────────────┴─────┬──────┴───────────────┘           │
│                           │                                  │
│                    ┌──────▼──────┐                           │
│                    │   data/db   │  SQLAlchemy Core          │
│                    └──────┬──────┘                           │
│                           │                                  │
│            ┌──────────────┴──────────────┐                   │
│       ┌────▼─────┐               ┌───────▼────┐              │
│       │ SQLite   │               │ PostgreSQL │              │
│       └──────────┘               └────────────┘              │
└─────────────────────────────────────────────────────────────┘
```

### Layer-Regeln

- `core/` kennt **keine** `banking/`-Adapter
- `bank_collector.py` kennt **nur** das `BankAdapter`-Interface
- DB-Zugriff **ausschließlich** über `data/db.py`
- `notifications/` und `alerts/` dürfen `core/` lesen, aber nicht umgekehrt
- `app/main.py` ist der einzige Ort, an dem `APScheduler` instanziiert wird

### Datenmodell (vereinfacht)

```
accounts          transactions       positions           snapshots
   │                  │                  │                  │
   ├──────────────────┴──────────────────┤                  │
   │                                     │                  │
properties  rent_expected  events  event_dedup  notification_log  prices
```

---

## 6. Entwicklung & Tests

### 6.1 Voraussetzungen

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### 6.2 Tests ausführen

```bash
pytest                  # 130 Tests, ~0.5 s
pytest --cov=app        # mit Coverage
pytest -k forecast      # einzelne Suite
```

**Aktueller Stand:**

* 130 Tests bestanden
* Coverage `app/core/`: ≥ 82 % (teilweise 100 %)
* Coverage gesamt: 73 % (≥ 60 % Gate, Ziel 80 %)

### 6.3 Linting & Formatierung

```bash
ruff check app/ tests/
ruff format app/ tests/
```

### 6.4 Type-Check (optional)

```bash
mypy app/
```

### 6.5 Projekt­struktur

```
finanzhub/
├── app/
│   ├── banking/             # 4 Adapter + Interface
│   ├── core/                # Engines (forecast, portfolio, …)
│   ├── data/                # DB, price service, event detector
│   ├── notifications/       # engine, mail, templates
│   ├── alerts/              # rent, payment, substance
│   ├── templates/           # 17 Jinja2-Templates
│   ├── cli.py               # Click CLI
│   ├── main.py              # Scheduler + Boot
│   ├── config_loader.py     # Pydantic v2
│   ├── logger.py
│   └── exit_codes.py
├── config.example/          # 8 Beispiel-YAMLs
├── migrations/              # 001, 002, 003 SQL
├── tests/
│   ├── unit/                # 14 Module
│   └── integration/         # 3 End-to-End-Suites
├── Dockerfile
├── docker-compose.yml
├── .github/workflows/ci.yml
├── pyproject.toml
├── requirements.txt
└── requirements-dev.txt
```

---

## 7. Fehler­behebung

| Problem                                  | Ursache / Lösung                                                 |
| ---------------------------------------- | ---------------------------------------------------------------- |
| `ModuleNotFoundError: yfinance`          | Optional — `pip install yfinance` oder ohne Live-Kurse fortfahren |
| `psycopg2.OperationalError: connection refused` | `DATABASE_URL` falsch oder Postgres nicht gestartet        |
| `FATAL: permission denied for table`     | DB-User fehlt GRANT; mit `finanzhub` als Owner re-initialisieren |
| Bank-Adapter time-out                    | `BANK_TIMEOUT` in `settings.yaml` erhöhen                        |
| Keine Mails                              | SMTP-Credentials in `mail.yaml` prüfen; `finanzhub notify test`  |
| Migration-Fehler                         | `finanzhub init --force` führt alle Schritte erneut aus (Vorsicht) |
| Doppelte Mieten in `rent-check`          | Miet­erwartung in `assets.yaml` prüfen; Mehrfach-Buchung normal  |
| `EventAlreadyExists`                     | Ereignis wurde bereits persistiert (append-only — gewollt)       |

### Logs

```bash
# Live
finanzhub status
docker compose logs -f finanzhub
journalctl -u finanzhub -f

# Log-Verzeichnis
ls -la output/logs/                # rotiert nach $LOG_RETENTION_DAYS
```

---

## 8. Sicherheit & Compliance

* **Read-only** zu Banken: FinanzHub initiiert keine Zahlungen
* **Keine Telemetrie**: keine Daten verlassen Ihr System außer den von Ihnen konfigurierten Bank-/Mail-Endpunkten
* **Passwort-Logging deaktiviert**: `app/logger.py` filtert sensible Felder
* **Input-Validierung** an allen externen Schnittstellen via Pydantic v2
* **SQL-Injection-Schutz** durch SQLAlchemy Core (parametrisierte Queries)
* **TLS** für SMTP standardmäßig aktiviert
* **Container-Härtung**: `USER reporter`, `NoNewPrivileges`, `ProtectSystem=strict` (in der Beispiel-`systemd`-Unit)

Empfehlungen:

* Aktivieren Sie automatische Sicherheits­updates (`unattended-upgrades`)
* Setzen Sie `LOG_LEVEL=WARNING` in Produktion
* Rotieren Sie SMTP-App-Passwörter jährlich
* Backups verschlüsseln (z. B. `gpg --symmetric`)

---

## 9. Roadmap / Status

**MVP (Phase 0–13, abgeschlossen):**

- [x] Multi-Bank-Anbindung (Demo, CSV, enable-banking-Stub, FinTS-Stub)
- [x] Portfolio-, Forecast-, NK-, Mietrendite-, Cashflow-Engines
- [x] Event-Detection (14 Typen, Deduplizierung)
- [x] Notification-Engine mit 17 Templates
- [x] APScheduler (Cron + Interval)
- [x] CLI mit 15+ Kommandos
- [x] Docker-Stack + CI/CD
- [x] 130 Tests, 73 % Coverage

**Phase 14 (ausstehend):**

- [ ] Live-yfinance-Anbindung produktiv testen
- [ ] Mehrere Mandanten / Portfolios parallel
- [ ] Web-UI (optional, nur als Read-Only-Viewer)
- [ ] PostgreSQL-Backup-Restore-Tool
- [ ] Prometheus-/OpenMetrics-Endpunkt

---

## 10. Lizenz

MIT — siehe `LICENSE`.

Copyright © 2024 BonorumSoft.
