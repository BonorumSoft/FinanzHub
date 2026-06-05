# Integrations­dokumentation

Diese Dokumentation beschreibt, wie FinanzHub mit **externen Systemen** verbunden wird: Banken, SMTP-Server, Datenbanken, Kurs­diensten und Schedulern. Sie richtet sich an Administratoren und Entwickler, die Integrationen einrichten, prüfen oder erweitern.

## Inhaltsverzeichnis

1. [Übersicht](#1-übersicht)
2. [Bank-Integrationen](#2-bank-integrationen)
3. [Kurs­dienste](#3-kursdienste)
4. [E-Mail / SMTP](#4-e-mail--smtp)
5. [Datenbank](#5-datenbank)
6. [Scheduler](#6-scheduler)
7. [Migrationen](#7-migrationen)
8. [Logging & Monitoring](#8-logging--monitoring)
9. [Sicherheits­hinweise](#9-sicherheitshinweise)

---

## 1. Übersicht

FinanzHub integriert sich in vier externe Kategorien:

| Kategorie       | Adapter            | Optional | Auth-Methode              |
| --------------- | ------------------ | -------- | ------------------------- |
| Banken          | enable-banking     | nein     | OAuth2 + RSA-JWS          |
| Banken          | FinTS              | nein     | PIN + TAN                 |
| Banken          | CSV                | nein     | (lokale Datei)            |
| Banken          | Demo               | nein     | (deterministisch)         |
| Kurse           | yfinance           | ja       | (keine)                   |
| Kurse           | OpenFIGI           | ja       | API-Key (Free-Tier)       |
| Mail            | SMTP               | nein     | PLAIN / LOGIN / XOAUTH2   |
| Datenbank       | SQLite / PostgreSQL| nein     | Connection-String         |

Alle Integrationen sind **read-only** (außer DB-Schreibzugriff für die eigene Datenbank). Es werden **keine** Zahlungen ausgelöst.

---

## 2. Bank-Integrationen

### 2.1 Demo-Bank (immer verfügbar)

`type: demo` — liefert reproduzierbare Test-Daten mit Seed 42.

```yaml
banks:
  - name: demo
    type: demo
```

Wird automatisch im `config.example/` mitgeliefert. Ideal für Erst-Installation und CI-Tests.

### 2.2 enable-banking (PSD2 / EU-Banken)

enable-banking ist ein **EU-Aggregator** mit PSD2-Lizenz. Erfordert:

1. **Geschäfts­konto** bei [enable-banking.com](https://enable-banking.com)
2. **RSA-Schlüsselpaar** (mind. 2048 Bit) für JWS-Signatur
3. **Application-ID** (PSP-ID)
4. **Bank-Konfiguration** mit `bank_id` (eindeutige UUID pro Bank)

#### 2.2.1 Schlüsselpaar erzeugen

```bash
mkdir -p /secrets
openssl genrsa -out /secrets/ebanking.pem 2048
openssl rsa -in /secrets/ebanking.pem -pubout -out /secrets/ebanking.pub

# Den privaten Schlüssel bei enable-banking registrieren (Upload der .pub-Datei)
```

#### 2.2.2 Konfiguration

`config/banks.yaml`:

```yaml
banks:
  - name: sparkasse
    type: enable_banking
    bank_id: "00000000-0000-0000-0000-000000000000"
    consent_id: "CONSENT_UUID"
    key_path: /secrets/ebanking.pem
    psp_id: "00000000-0000-0000-0000-000000000000"
    timeout: 30
```

#### 2.2.3 Ablauf

1. Benutzer loggt sich im enable-banking-Portal ein, autorisiert den Zugriff
2. Erhält eine `consent_id` (90 Tage gültig, verlängerbar)
3. FinanzHub nutzt `consent_id` + `key_path` für JWS-signierte Requests
4. Bei 401 → `consent_id` abgelaufen, Admin-Notification wird ausgelöst

#### 2.2.4 Fehler­behandlung

| HTTP-Code | Bedeutung              | Aktion                       |
| --------- | ---------------------- | ---------------------------- |
| 200       | OK                     | normaler Workflow            |
| 401       | Consent abgelaufen     | Re-Authorize, Alert an Admin |
| 403       | Bank verweigert        | Bank-spezifische Sperre      |
| 429       | Rate-Limit             | Retry mit backoff            |
| 5xx       | Aggregator-Ausfall     | Retry, dann Alert            |

### 2.3 FinTS (deutsche Banken, nativ)

FinTS ist das **HBCI/FinTS-Protokoll** der deutschen Banken. Erfordert:

1. **BLZ** (8 Stellen)
2. **FinTS-Endpoint-URL** (vom Bank-Support)
3. **Konto-Zugangsdaten** (Konto­nummer + PIN)
4. **TAN-Verfahren** (chipTAN, photoTAN, mobileTAN, …)

```yaml
banks:
  - name: ing
    type: fints
    blz: "50010517"
    endpoint: "https://fints.ing.de/fints"
    username: "1234567890"
    password: "<im Keyring, nicht hier>"
    tan_mechanism: "photoTAN"
```

Aktuell als **Stub** implementiert. Für Echtbetrieb empfehlen wir `python-fints` als Backend (TODO in `fints_adapter.py`).

### 2.4 CSV-Adapter (Offline-Import)

Für Banken ohne API: **manueller CSV-Export** aus dem Online-Banking.

`config/banks.yaml`:

```yaml
banks:
  - name: comdirect-csv
    type: csv
    file_pattern: "/import/comdirect_*.csv"
    encoding: "utf-8"
    delimiter: ";"           # autodetect, falls nicht gesetzt
    skip_lines: 0
    column_map:
      buchungsdatum: "Buchungsdatum"
      valuta: "Wertstellung"
      empfaenger: "Empfänger"
      iban: "IBAN"
      betrag: "Betrag"
      zweck: "Verwendungszweck"
```

Spalten-Autodetect für gängige Banken (Comdirect, DKB, Sparkasse, ING) in `app/banking/csv_adapter.py:_detect_column_map()`.

#### Workflow

```bash
# 1. CSV aus Online-Banking herunterladen
# 2. In /import/ ablegen
# 3. Synchronisieren
finanzhub pull comdirect-csv
```

### 2.5 Sandbox / Test-Modus

enable-banking bietet eine **Sandbox-Umgebung**. Nutzen Sie diese für CI:

```yaml
banks:
  - name: sandbox
    type: enable_banking
    sandbox: true
    bank_id: "sandbox-bank-uuid"
    consent_id: "sandbox-consent-uuid"
    psp_id: "<sandbox-psp-id>"
    key_path: /secrets/sandbox-ebanking.pem
    base_url: "https://sandbox.enable-banking.com"
```

---

## 3. Kurs­dienste

### 3.1 yfinance (Hauptquelle)

```bash
pip install yfinance
```

Funktioniert ohne API-Key. Liefert aktuelle Kurse + Währung.

```python
from app.data.price_service import PriceService
ps = PriceService(db)
price = ps.get_price("IE00B4L5Y983")  # MSCI World ETF
# → Decimal("382.45")
```

#### Fallbacks

| Szenario                    | Verhalten                                   |
| --------------------------- | ------------------------------------------- |
| `yfinance` nicht installiert | WARNING, Positionen werden **übersprungen** |
| ISIN nicht bei Yahoo        | OpenFIGI-Mapping versucht, sonst NULL       |
| Yahoo-Rate-Limit            | 1h-Cache in `prices`-Tabelle                |
| Netzwerk­fehler             | `RuntimeError` → Scheduler retry in 1h      |

### 3.2 OpenFIGI (Mapping)

```bash
pip install requests
# API-Key optional für höhere Rate-Limits
# Setzen via env: OPENFIGI_API_KEY=<key>
```

Nutzt kostenlose `https://api.openfigi.com/v3/mapping` für ISIN → Ticker.

### 3.3 Statische ISIN-Map

`app/data/price_service.py:STATIC_ISIN_MAP` enthält ~50 der gängigsten europäischen ETFs ohne API-Call:

```python
STATIC_ISIN_MAP = {
    "IE00B4L5Y983": ("IWDA.AS", "EUR"),     # MSCI World (iShares)
    "IE00BFM6TC58": ("EUNL.DE", "EUR"),     # MSCI World (Amundi)
    # ...
}
```

**Aktualisieren:** halbjährlich oder wenn ein Kurs nicht aufgelöst wird.

### 3.4 Caching

| Cache-Stufe | TTL | Speicherort                |
| ----------- | --- | -------------------------- |
| In-Memory   | 60s | `functools.lru_cache`     |
| DB          | 1h  | `prices`-Tabelle           |

Refresh erzwingen:

```bash
finanzhub pull-all --force-price-refresh
```

---

## 4. E-Mail / SMTP

### 4.1 SMTP-Konfiguration

`config/mail.yaml`:

```yaml
mail:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_user: reports@example.com
  smtp_password: "<app-passwort>"
  use_tls: true
  from_address: "FinanzHub <reports@example.com>"
  timeout: 30
  retry_attempts: 3
  retry_backoff: exponential
```

#### Provider-Beispiele

| Provider      | Host                    | Port | Besonderheit                       |
| ------------- | ----------------------- | ---- | ---------------------------------- |
| Gmail         | smtp.gmail.com          | 587  | App-Passwort erforderlich          |
| Outlook       | smtp-mail.outlook.com   | 587  | OAuth2 empfohlen                   |
| GMX           | mail.gmx.net            | 587  | Standard PLAIN                     |
| Mailgun       | smtp.mailgun.org        | 587  | Domain-Validation erforderlich     |
| self-hosted   | mail.example.com        | 25/587 | STARTTLS, eigenes Cert            |

### 4.2 Gmail-Beispiel mit App-Passwort

1. [myaccount.google.com](https://myaccount.google.com) → Sicherheit → 2FA aktivieren
2. App-Passwörter → „FinanzHub" generieren
3. 16-stelliges Passwort in `mail.yaml` eintragen
4. Test: `finanzhub notify test daily_wealth_report`

### 4.3 OAuth2 / XOAUTH2 (Microsoft, Google)

```yaml
mail:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  auth_method: xoauth2
  oauth2_token_path: /secrets/oauth2-token.json
```

Token-Refresh wird automatisch vom `mail_service.py` gehandhabt.

### 4.4 Empfänger-Verwaltung

Mehrere Empfänger in `config/notifications.yaml`:

```yaml
notifications:
  - name: daily_wealth_report
    template: daily_wealth_report
    schedule: "0 22 * * *"
    recipients:
      - ich@example.com
      - partner@example.com
    cc: [finanzamt@example.com]      # optional
    bcc: [archive@example.com]        # optional
```

### 4.5 Anti-Spam-Maßnahmen

* **SPF-Eintrag** in DNS: `v=spf1 include:_spf.example.com ~all`
* **DKIM-Signatur** in SMTP-Server konfigurieren
* **DMARC**: `v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com`
* `From`-Adresse muss zur authentifizierten Domain gehören

### 4.6 Test-Versand

```bash
# Allgemein
finanzhub notify test daily_wealth_report

# An spezifische Empfänger
finanzhub notify test daily_wealth_report --to test@example.com

# Mit Debug
LOG_LEVEL=DEBUG finanzhub notify test daily_wealth_report
```

---

## 5. Datenbank

### 5.1 SQLite (Standard, Entwicklung)

```env
DATABASE_URL=sqlite:////var/lib/finanzhub/finanzhub.db
```

**Vorteile:**

- Keine externe Abhängigkeit
- Sofortiger Start, ideal für Raspberry Pi / Single-User

**Nachteile:**

- Keine parallele Schreibzugriffe (Single-Writer-Lock)
- Keine Netzwerk­replikation

**Empfohlen für:** ≤ 1 Benutzer, ≤ 10 Jahre Historie.

### 5.2 PostgreSQL (Produktion)

```env
DATABASE_URL=postgresql://finanzhub:STRONG@postgres:5432/finanzhub
```

Docker-Compose enthält bereits `postgres:16-alpine`.

**Manuelle Installation:**

```bash
sudo apt install -y postgresql-15
sudo -u postgres psql <<SQL
CREATE USER finanzhub WITH PASSWORD '<STRONG>';
CREATE DATABASE finanzhub OWNER finanzhub;
GRANT ALL PRIVILEGES ON DATABASE finanzhub TO finanzhub;
SQL
```

**Empfohlen für:** Mehrere Benutzer/Mandanten, langfristige Speicherung, Backups via `pg_dump`.

### 5.3 Connection-Pool

`app/data/db.py` konfiguriert SQLAlchemy-Engine:

```python
engine = create_engine(
    DATABASE_URL,
    pool_size=5,                # 5 Connections
    max_overflow=10,            # +10 bei Lastspitzen
    pool_pre_ping=True,         # testet Connections vor Nutzung
    pool_recycle=3600,          # 1h, vermeidet stale connections
    echo=False,                 # SQL-Echo nur im DEBUG-Modus
)
```

### 5.4 Backup & Restore

#### SQLite

```bash
# Backup (online, aber sqlite3 .backup ist sicherer)
sqlite3 /var/lib/finanzhub/finanzhub.db ".backup '/backup/fh-$(date +%F).db'"

# Restore
systemctl stop finanzhub
cp /backup/fh-2026-06-15.db /var/lib/finanzhub/finanzhub.db
systemctl start finanzhub
```

#### PostgreSQL

```bash
# Backup
docker compose exec postgres pg_dump -U finanzhub finanzhub \
  | gzip > /backup/fh-$(date +%F).sql.gz

# Restore
gunzip -c /backup/fh-2026-06-15.sql.gz \
  | docker compose exec -T postgres psql -U finanzhub -d finanzhub
```

#### Cron-Empfehlung

```cron
# /etc/cron.d/finanzhub-backup
0 3 * * * root /opt/finanzhub/scripts/backup.sh
```

`scripts/backup.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
BACKUP_DIR=/backup/finanzhub
mkdir -p "$BACKUP_DIR"
docker compose -f /opt/finanzhub/docker-compose.yml exec -T postgres \
  pg_dump -U finanzhub finanzhub \
  | gzip > "$BACKUP_DIR/fh-$(date +%F).sql.gz"
find "$BACKUP_DIR" -type f -mtime +14 -delete
```

### 5.5 Verschlüsselung at-Rest

Empfehlung: **Dateisystem-Verschlüsselung** (LUKS) oder **DB-seitige Verschlüsselung** (PostgreSQL TDE).

```bash
# LUKS-Beispiel
sudo cryptsetup luksFormat /dev/sdb
sudo cryptsetup open /dev/sdb finanzhub_data
sudo mkfs.ext4 /dev/mapper/finanzhub_data
```

---

## 6. Scheduler

### 6.1 Cron-Jobs

`config/notifications.yaml` definiert Schedules:

```yaml
notifications:
  - name: daily_wealth_report
    schedule: "0 22 * * *"        # täglich 22:00
    template: daily_wealth_report

  - name: weekly_digest
    schedule: "0 8 * * 1"        # Mo 08:00
    template: weekly_digest

  - name: monthly_portfolio
    schedule: "0 9 1 * *"        # 1. des Monats 09:00
    template: monthly_portfolio
```

Cron-Syntax: `min hour day month weekday`. Zeitzone via `TZ` env (`Europe/Berlin`).

### 6.2 Intervall-Jobs (neuere API)

```yaml
intervals:
  - name: pull_every_6h
    function: pull_all
    every: 6h
    jitter: 5m             # ±5 Min Streuung gegen Lastspitzen
```

### 6.3 APScheduler-Konfiguration

`app/scheduler.py`:

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

scheduler = BlockingScheduler(timezone=settings.timezone)
```

### 6.4 Distributed Locking (geplant)

Bei mehreren Instanzen verhindert `app/data/lock.py` doppelte Ausführung:

```python
with advisory_lock("finanzhub:daily_pull", timeout=300):
    run_daily_pull()
```

PostgreSQL: `pg_try_advisory_lock()`. SQLite: File-Lock.

### 6.5 Scheduler-Logs

```bash
journalctl -u finanzhub -f            # systemd
docker compose logs -f finanzhub      # docker
```

Log-Marker:

- `SCHEDULER: job started: daily_wealth_report`
- `SCHEDULER: job completed in 1.2s: daily_wealth_report`
- `SCHEDULER: job failed: daily_wealth_report — <error>`

---

## 7. Migrationen

### 7.1 Schema-Migrationen

`migrations/00X_*.sql` werden **alphabetisch sortiert** angewendet:

```
migrations/
├── 001_initial_schema.sql
├── 002_add_events.sql
├── 003_add_notification_log.sql
└── 004_add_field_x.sql           # NEU
```

Anwendung via:

```bash
finanzhub init                      # idempotent
```

### 7.2 Idempotenz

`app/data/db.py` trackt in `schema_migrations`:

```sql
CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY,
    applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

Bereits angewendete Versionen werden übersprungen.

### 7.3 Migration schreiben — Schritt für Schritt

#### Schritt 1: SQL-Datei anlegen

```sql
-- migrations/004_add_custody_field.sql
ALTER TABLE accounts ADD COLUMN custody BOOLEAN NOT NULL DEFAULT FALSE;
CREATE INDEX idx_accounts_custody ON accounts(custody);
```

#### Schritt 2: SQLite-Kompatibilität prüfen

```bash
sqlite3 /tmp/test.db < migrations/004_add_custody_field.sql
```

#### Schritt 3: Pydantic-Modell erweitern

```python
# app/config_loader.py
class BankAccount(BaseModel):
    ...
    custody: bool = False
```

#### Schritt 4: Tests schreiben

```python
def test_custody_field_default_false():
    acc = BankAccount(iban="DE00...", name="X", type="giro", bank_name="Y")
    assert acc.custody is False
```

#### Schritt 5: Migration anwenden

```bash
finanzhub init
# Tabelle schema_migrations enthält jetzt 001, 002, 003, 004
```

### 7.4 Downgrades (manuell)

Es gibt **kein** automatisches Rollback. Bei Problemen:

```bash
# 1. Backup einspielen
gunzip -c /backup/fh-pre-migration.sql.gz | psql ...

# 2. schema_migrations korrigieren
psql -d finanzhub -c "DELETE FROM schema_migrations WHERE version='004';"
```

### 7.5 Daten-Migrationen (Backfill)

Große Backfills **außerhalb** von SQL-Dateien als Python-Skript:

`scripts/migrate_004_backfill_custody.py`:

```python
from app.data.db import get_engine

engine = get_engine()
with engine.begin() as conn:
    # Depots = custody=true, Giro = custody=false
    conn.execute(text("""
        UPDATE accounts
        SET custody = TRUE
        WHERE type = 'depot'
    """))
    print("Backfill abgeschlossen")
```

Aufruf: `python scripts/migrate_004_backfill_custody.py`.

---

## 8. Logging & Monitoring

### 8.1 Strukturiertes Logging

```python
import logging
logger = logging.getLogger(__name__)

logger.info(
    "Bank-Sync erfolgreich",
    extra={
        "bank": "sparkasse",
        "transactions_added": 42,
        "duration_ms": 1234,
    },
)
```

`app/logger.py` formatiert als JSON, wenn `LOG_FORMAT=json` gesetzt.

### 8.2 Log-Datei

```
output/logs/finanzhub.log
```

Rotation: 10 MB × 5 Backups (konfigurierbar in `settings.yaml`).

### 8.3 Health-Check

```bash
finanzhub status
# → {"status": "ok", "db_size_mb": 42, "last_sync": "2026-06-15T22:00:00Z"}
```

HTTP-Health (optional, Phase 14):

```python
# app/main.py
from aiohttp import web

async def healthz(request):
    return web.json_response({"status": "ok"})

app = web.Application()
app.router.add_get("/healthz", healthz)
```

### 8.4 Prometheus-Metrics (geplant, Phase 14)

```
# HELP finanzhub_transactions_total
# TYPE finanzhub_transactions_total counter
finanzhub_transactions_total{bank="sparkasse"} 1234

# HELP finanzhub_forecast_duration_seconds
# TYPE finanzhub_forecast_duration_seconds histogram
finanzhub_forecast_duration_seconds_bucket{le="1.0"} 100
```

### 8.5 Alerting

| Bedingung                          | Notification                  |
| ---------------------------------- | ----------------------------- |
| Bank-Sync 3× fehlgeschlagen        | `mail_failed_sync` Event      |
| Forecast-Engine < 50% Erwartung    | `forecast_below_target` Event |
| DB-Größe > 1 GB                    | `db_size_warning` Event       |
| SMTP-Versand 5× fehlgeschlagen     | `mail_send_failed` Event      |

Eigene Alerts in `config/notifications.yaml`:

```yaml
alerts:
  - name: db_too_large
    condition: "db_size_mb > 1024"
    severity: warning
    recipients: [admin@example.com]
```

---

## 9. Sicherheits­hinweise

### 9.1 Secret-Management

**NIEMALS** Secrets in Git committen!

#### Methoden

| Methode        | Verwendung                                       |
| -------------- | ------------------------------------------------ |
| env-File       | `.env` (in `.gitignore`!)                        |
| Docker Secrets | `docker secret create ebanking_pem /secrets/...` |
| Hashicorp Vault| Professionell, mit Rotation                      |
| systemd        | `EnvironmentFile=/etc/finanzhub/secrets.env`     |
| Keyring        | `python -m keyring set finanzhub mail_password` |

#### Beispiel `.env` (NICHT in Git!)

```env
DB_PASSWORD=STRONG_PASSWORD
ENABLE_BANKING_KEY=...
SMTP_PASSWORD=...
```

#### Verschlüsseltes Secret-File

```bash
gpg --symmetric --cipher-algo AES256 secrets.env    # → secrets.env.gpg
gpg --decrypt secrets.env.gpg > secrets.env
```

In `app/config_loader.py`:

```python
def _load_env():
    if Path("secrets.env.gpg").exists():
        subprocess.run(["gpg", "--decrypt", "secrets.env.gpg"], check=True)
```

### 9.2 Netzwerk-Sicherheit

* **Outbound HTTPS** zu Banken / SMTP — kein Problem
* **Inbound**: FinanzHub lauscht standardmäßig auf **keinem** Port
* Bei Web-UI (Phase 14): **TLS-Termination** durch Reverse-Proxy (nginx, Caddy, Traefik)

#### Reverse-Proxy-Beispiel (nginx)

```nginx
server {
    listen 443 ssl http2;
    server_name finanzhub.example.com;

    ssl_certificate /etc/letsencrypt/live/finanzhub.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/finanzhub.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 9.3 Audit-Log

Alle Kontozugriffe (Pull) werden in `audit_log`-Tabelle geschrieben (geplant Phase 14):

```sql
CREATE TABLE audit_log (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    actor TEXT,             -- 'finanzhub' / username
    action TEXT,            -- 'pull', 'update_config', 'init'
    target TEXT,            -- bank name, file path
    ip_address INET,
    success BOOLEAN
);
```

### 9.4 Compliance (EU-DSGVO)

| Anforderung                         | Umsetzung in FinanzHub                       |
| ----------------------------------- | -------------------------------------------- |
| Datenminimierung                    | Nur Notwendiges wird persistiert             |
| Rechtmäßigkeit                      | Konfiguration dokumentiert Verarbeitungszweck |
| Speicherbegrenzung                  | Retention-Policy in `settings.yaml`          |
| Integrität & Vertraulichkeit        | TLS für SMTP, verschlüsselte Backups         |
| Auskunftsrecht                      | Export als JSON via `finanzhub export`       |
| Recht auf Löschung                  | `finanzhub purge --user <id>` (TODO)         |

### 9.5 Härtungs-Checkliste (Produktion)

- [ ] `app` läuft als unprivilegierter User
- [ ] `systemd`-Service mit `NoNewPrivileges`, `ProtectSystem=strict`
- [ ] DB-Passwort ≥ 32 Zeichen, in Vault/GPG
- [ ] SMTP nur via STARTTLS / TLS
- [ ] Backup verschlüsselt (LUKS oder GPG)
- [ ] Log-Level `WARNING` in Produktion
- [ ] Keine Test-Adapter in Produktion aktiv
- [ ] `.env` mit `chmod 600` gesichert
- [ ] Firewall: nur ausgehende Verbindungen erlaubt
- [ ] Auto-Updates via `unattended-upgrades` aktiv
- [ ] SSH-Key-Only-Auth, fail2ban aktiv
- [ ] Reverse-Proxy mit TLS (Phase 14)

---

**Weiterführend:**

- [Entwickler­dokumentation](DEVELOPMENT.md)
- [Nutzungs­dokumentation](USAGE.md)
- [README](../README.md)
