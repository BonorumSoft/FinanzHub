# Nutzungs­dokumentation

Diese Dokumentation ist die ausführliche **Schritt-für-Schritt-Anleitung** für die tägliche, wöchentliche, monatliche und jährliche Nutzung von FinanzHub. Sie ergänzt den Schnellstart und die CLI-Referenz im [README](../README.md#4-nutzeranleitung) um konkrete Rezepte, Workflows und Troubleshooting-Tipps.

## Inhaltsverzeichnis

1. [Konzepte](#1-konzepte)
2. [Schnellstart-Walkthrough](#2-schnellstart-walkthrough)
3. [CLI-Referenz](#3-cli-referenz)
4. [Tägliche Workflows](#4-tägliche-workflows)
5. [Wöchentliche Workflows](#5-wöchentliche-workflows)
6. [Monatliche Workflows](#6-monatliche-workflows)
7. [Jährliche Workflows](#7-jährliche-workflows)
8. [Rezepte](#8-rezepte)
9. [Reports interpretieren](#9-reports-interpretieren)
10. [Troubleshooting](#10-troubleshooting)
11. [Glossar](#11-glossar)

---

## 1. Konzepte

Bevor wir uns in die Workflows stürzen, ein paar Konzepte, die Sie verstanden haben sollten:

### 1.1 Vermögensbestandteile

```
Nettovermögen
├── Banken            (Giro, Tagesgeld, Festgeld)
├── Depot             (Aktien, ETFs, Fonds, Anleihen)
└── Immobilien        (Marktwert − Restschuld = Equity)
```

### 1.2 Append-only Audit-Trail

FinanzHub löscht **nie** Daten. Selbst korrigierte Buchungen bleiben als „storniert" markiert (Phase 14, aktuell nur INSERT).

### 1.3 Idempotenz

Jeder CLI-Befehl kann beliebig oft ausgeführt werden, ohne Schaden anzurichten. Beispiel:

```bash
finanzhub pull-all       # zweimal ausgeführt → kein Effekt
finanzhub init           # zweimal ausgeführt → keine doppelten Migrationen
```

### 1.4 Graceful Degradation

Fehlende optionale Komponenten (yfinance, OpenFIGI) führen zu **WARNINGS**, nicht zu Abstürzen.

### 1.5 Read-only zu Banken

FinanzHub fordert nur Lese­rechte an. Niemals werden Zahlungen initiiert.

---

## 2. Schnellstart-Walkthrough

In 10 Minuten vom leeren System zur ersten Vermögensübersicht.

### Schritt 1: Repository klonen

```bash
git clone https://github.com/bonorumsoft/finanzhub.git
cd finanzhub
```

### Schritt 2: Beispielkonfiguration übernehmen

```bash
cp -r config.example/ config/
```

Die Demo-Bank ist bereits aktiviert — Sie brauchen **nichts** zu konfigurieren.

> **Docker/Portainer:** Beim ersten Start kopiert FinanzHub automatisch alle Configs aus `config.example/` in das Volume — kein manuelles `cp` nötig.

### Schritt 3: Python-Umgebung einrichten

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Schritt 4: Datenbank initialisieren

```bash
finanzhub init
# → Migrations applied: 001, 002, 003
```

### Schritt 5: Demo-Daten synchronisieren

```bash
finanzhub pull demo
# → 87 Transaktionen geladen, 3 Konten registriert
```

### Schritt 6: Vermögen anzeigen

```bash
finanzhub wealth
```

Sie sehen eine Tabelle mit Bank­beständen, Depot, Immobilien-Equity und Netto­vermögen.

### Schritt 7: Forecast ansehen

```bash
finanzhub forecast
```

Sie sehen die nächsten 30 Jahre mit jährlichen Vermögens­werten.

### Schritt 8: Test-E-Mail (optional)

```bash
# mail.yaml anpassen, dann:
finanzhub notify test daily_wealth_report
```

---

## 3. CLI-Referenz

Vollständige Liste aller Kommandos mit Beispielen.

### 3.1 Globale Flags

| Flag             | Beschreibung                                          |
| ---------------- | ----------------------------------------------------- |
| `--config-dir`   | Pfad zum Konfig­verzeichnis (default: `./config/`)   |
| `--output-dir`   | Pfad zum Output-Verzeichnis (default: `./output/`)    |
| `--verbose / -v` | Logging-Level auf DEBUG setzen                        |
| `--json`         | JSON-Output (bei unterstützten Kommandos)             |
| `--help`         | Hilfe zum jeweiligen Kommando                         |
| `--version`      | Version anzeigen                                      |

### 3.2 Kommandos

#### `init` — Schema anlegen

```bash
finanzhub init
finanzhub init --force   # WARNUNG: ignoriert schema_migrations
```

#### `pull` — Bank-Daten synchronisieren

```bash
finanzhub pull <bank-name>
finanzhub pull sparkasse --days 30      # nur letzte 30 Tage
finanzhub pull sparkasse --since 2026-01-01
```

#### `pull-all` — Alle Banken

```bash
finanzhub pull-all
finanzhub pull-all --parallel 3         # bis zu 3 parallel
```

#### `wealth` — Netto­vermögen

```bash
finanzhub wealth
finanzhub wealth --json | jq '.net_worth'
finanzhub wealth --no-color              # für Skripte
```

#### `forecast` — Vermögens­vorschau

```bash
finanzhub forecast
finanzhub forecast --years 40
finanzhub forecast --scenario stress
finanzhub forecast --include-immobilien
```

#### `cashflow` — Liquiditäts­planung

```bash
finanzhub cashflow
finanzhub cashflow --months 24
finanzhub cashflow --json
```

#### `rent-check` — Miet­eingänge prüfen

```bash
finanzhub rent-check                    # aktueller Monat
finanzhub rent-check 2026-06             # Juni 2026
finanzhub rent-check 2026                # alle Monate 2026
finanzhub rent-check --property "Berlin-Mitte"
```

Status-Output:

```
BERLIN-MITTE         erwartet:  1 800,00 €     Ist:  1 800,00 €     [bezahlt]
LEIPZIG-WEST         erwartet:  1 250,00 €     Ist:  0,00 €         [ausgefallen]
HAMBURG-NORD         erwartet:    950,00 €     Ist:  2 850,00 €     [bezahlt] (3 Buchungen)
```

#### `nk` — NK-Abrechnung

```bash
finanzhub nk --year 2025 --property "Berlin-Mitte"
finanzhub nk --year 2025 --property "Berlin-Mitte" --output nk-2025.csv
finanzhub nk --year 2025 --property "Berlin-Mitte" --format pdf   # TODO Phase 14
```

#### `rentability` — Rendite-Kennzahlen

```bash
finanzhub rentability --property "Berlin-Mitte"
finanzhub rentability --all
finanzhub rentability --all --json
```

#### `events` — Ereignis­verwaltung

```bash
finanzhub events list                   # alle ungelesenen
finanzhub events list --all             # inkl. quittierter
finanzhub events list --type rent_late  # gefiltert
finanzhub events detect                 # sofortige Detektion
finanzhub events ack <event_id>         # quittieren
finanzhub events purge --before 2024-01-01  # Aufräumen
```

#### `notify` — Benachrichtigungen

```bash
finanzhub notify list                              # Historie
finanzhub notify run                               # fällige ausführen
finanzhub notify test <template>                    # Test-Email
finanzhub notify test <template> --to foo@bar.com  # spezifischer Empfänger
```

#### `status` — System-Status

```bash
finanzhub status
finanzhub status --json
```

#### `valuation` — Immobilien­schätzung

```bash
finanzhub valuation --property "Berlin-Mitte"
finanzhub valuation --all
```

#### `export` — Daten­export (DSGVO-Auskunft)

```bash
finanzhub export --output export-2026-06-15.json
finanzhub export --format csv
```

---

## 4. Tägliche Workflows

### 4.1 Morgens: Letzter Sync-Status prüfen

```bash
finanzhub status
# → Alles grün? Keine Aktion nötig.
```

### 4.2 Vormittags: Manuelle Synchronisation (optional)

```bash
finanzhub pull-all
```

Tritt nur ein, wenn Sie den automatischen Scheduler deaktiviert haben.

### 4.3 Mittags: Ungewöhnliche Buchungen prüfen

```bash
finanzhub events list --severity warning
```

### 4.4 Abends: Tagesabschluss

```bash
finanzhub wealth
finanzhub forecast
```

### 4.5 Test-E-Mail nach Änderungen

Nach Config-Änderungen immer:

```bash
finanzhub notify test daily_wealth_report
```

### 4.6 Beleg-Inbox (täglich)

Wer den Inbox-Polling aktiviert hat, braucht **keinen** manuellen Workflow — der Scheduler pollt alle 60 s. Trotzdem zur Kontrolle:

```bash
finanzhub inbox status           # Übersicht (sollte meist 0 ungematcht sein)
finanzhub inbox list --status error   # Fehler prüfen
```

Bei vielen manuellen Käufen (z. B. nach dem Wocheneinkauf):

```bash
# Alle 5 Belege manuell triggern
finanzhub inbox run
```

---

## 5. Wöchentliche Workflows

### 5.1 Wochenrückblick (jeden Sonntag)

```bash
finanzhub wealth
finanzhub cashflow
finanzhub events list --since 7d
```

### 5.2 Miet­eingänge prüfen (jeden Montag)

```bash
finanzhub rent-check           # aktueller Monat
finanzhub rent-check --last-month   # abgeschlossener Monat
```

### 5.3 DB-Größe prüfen

```bash
finanzhub status --json | jq '.db_size_mb'
# > 1024? → ggf. alte Daten exportieren und archivieren
```

### 5.4 Backups prüfen

```bash
ls -la /backup/finanzhub/
# 7 Tage Backups vorhanden? Cron-Job OK?
```

---

## 6. Monatliche Workflows

### 6.1 Monats­abschluss (1. des Monats)

```bash
# 1. Letzten Monat vollständig pullen
finanzhub pull-all --since $(date -d "last month" +%Y-%m-01)

# 2. Snapshot erstellen
finanzhub snapshot create

# 3. Mieten prüfen
finanzhub rent-check $(date -d "last month" +%Y-%m)

# 4. Forecast aktualisieren
finanzhub forecast --save output/forecasts/$(date +%Y-%m).json

# 5. Cashflow prüfen
finanzhub cashflow --months 12
```

### 6.2 NK-Abrechnung vorbereiten (1. Quartalsmonat)

```bash
# Vorlage herunterladen
finanzhub nk --year $(date +%Y) --property "Berlin-Mitte" \
  --output nk-$(date +%Y)-berlin-mitte.csv
```

### 6.3 Steuer-Export (für Steuerberater)

```bash
finanzhub export --year $(date +%Y) --format csv \
  --output steuer-$(date +%Y).zip
```

### 6.4 Rendite-Übersicht (1. des Monats)

```bash
finanzhub rentability --all
finanzhub rentability --all --json > rendite-$(date +%Y-%m).json
```

---

## 7. Jährliche Workflows

### 7.1 Jahresabschluss (31.12. / 1.1.)

```bash
# 1. Snapshot des aktuellen Vermögens
finanzhub wealth --json > vermoegen-$(date +%Y).json

# 2. Forecast für nächstes Jahr
finanzhub forecast --years 1

# 7. Archiv erstellen
finanzhub export --year $(date +%Y) --output archiv-$(date +%Y).zip

# 8. Konfiguration sichern
tar -czf config-$(date +%Y).tar.gz config/
```

### 7.2 Steuer-Export (Anfang Januar)

```bash
finanzhub export --year $(date +%Y) --format csv --include all
# → an Steuerberater senden
```

### 7.3 Versicherungs-Summen prüfen

Stellen Sie sicher, dass Ihre Versicherungen zur aktuellen Vermögenslage passen.

### 7.4 Passwörter rotieren

- [ ] SMTP-App-Passwort
- [ ] enable-banking-Schlüssel (alle 12 Monate)
- [ ] DB-Passwort
- [ ] Server-SSH-Keys (alle 24 Monate)

### 7.5 Update auf neue FinanzHub-Version

```bash
git pull
docker compose build --pull
docker compose up -d
docker compose logs -f finanzhub
finanzhub status
```

---

## 8. Rezepte

### 8.1 Eigene KPIs hinzufügen

Im `app/core/portfolio_engine.py`:

```python
def calculate_savings_rate(monthly_income: Decimal, monthly_spend: Decimal) -> Decimal:
    """Sparquote = (Einkommen - Ausgaben) / Einkommen"""
    if monthly_income == 0:
        return Decimal("0")
    return (monthly_income - monthly_spend) / monthly_income
```

### 8.2 Custom Alert: „Kontostand < 5000 €"

`config/notifications.yaml`:

```yaml
alerts:
  - name: low_balance_warning
    condition: "sum(bank_balances) < 5000"
    severity: warning
    template: low_balance
    recipients: [ich@example.com]
```

Template `app/templates/low_balance.html.j2`:

```html
{% extends "base.html.j2" %}
{% block content %}
  <h1 style="color:#dc2626">Kontostand niedrig</h1>
  <p>Der Gesamtbestand Ihrer Bankkonten ist unter 5 000 € gefallen.</p>
  <p>Aktueller Stand: <strong>{{ total_balance }} €</strong></p>
{% endblock %}
```

### 8.3 Notfall-Stopp der automatischen Mails

```bash
# Scheduler deaktivieren (Docker)
docker compose stop finanzhub

# Oder (bare-metal)
sudo systemctl stop finanzhub

# Konfiguration behalten, nur pausieren
```

### 8.4 Daten­migration auf PostgreSQL

```bash
# 1. Export aus SQLite
finanzhub export --output dump.json --format json

# 2. Auf PostgreSQL-Instanz initialisieren
DATABASE_URL=postgresql://... finanzhub init

# 3. Import
DATABASE_URL=postgresql://... finanzhub import --input dump.json
```

### 8.5 Mobile Alerts via Ntfy

`config/mail.yaml`:

```yaml
mail:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_user: ...
  smtp_password: ...
  forward_to_ntfy: true
  ntfy_topic: "finanzhub-alerts-XYZ"
```

### 8.6 CSV-Export für Excel

```bash
finanzhub export --format csv --output vermoegen.csv
# In Excel öffnen → Daten → Aus Text/CSV → Trennzeichen Komma
```

### 8.7 Asset-Preis-Refresh erzwingen

```bash
finanzhub pull-all --force-price-refresh
```

### 8.8 Immobilie hinzufügen

1. `config/assets.yaml` editieren
2. `finanzhub valuation --property "Neue-Immobilie"` (Schätzung)
3. `finanzhub snapshot create`

### 8.9 Mandanten-Trennung (Phase 14)

```bash
finanzhub user create --name partner --email partner@example.com
finanzhub snapshot create --user partner
```

### 8.10 Schnell-Check „Ist alles OK?"

```bash
finanzhub status && finanzhub events list --severity critical
```

Wenn beides grün → Sie können den Bildschirm schließen.

---

## 9. Reports interpretieren

### 9.1 Täglicher Vermögens-Report

Sie erhalten täglich um 22:00 eine E-Mail. Beispiel:

```
─────────────────────────────────────────────
  FINANZHUB · TÄGLICHER BERICHT · 15.06.2026
─────────────────────────────────────────────

Ihr Vermögen heute
  487 320,55 €    +1 234,55 € seit gestern (+0,25%)

Aufteilung
  ████████████████  Banken       142 815,12 €  (29,3%)
  ██████████████████████  Depot   187 230,40 €  (38,4%)
  ███████████████  Immobilien  157 275,03 €  (32,3%)

Liquidität              142 815,12 €   ✅ ausreichend
Offene Mieten                 0,00 €   ✅ alles bezahlt
Substanz-Reserve         71 407,56 €   ✅ 6 Monate gedeckt

Hinweise des Tages
  ⚠  Ungewöhnlich hohe Buchung: -2 340,00 € (Karten-Zahlung, ...)
  ✅  Depot-Rendite YTD: +4,2%

Nächste Aktionen
  •  Keine kritischen Ereignisse

─────────────────────────────────────────────
```

### 9.2 Quartals-Report

Zusätzlich zu allen Tages-Report-Daten:

- Quartalsrendite
- Vergleich mit Vorquartal
- NK-Abrechnungs-Status
- Empfehlungen des Systems

### 9.3 NK-Abrechnungs-Report

Eine Tabelle pro Wohnung mit:

- Position (Heizung, Wasser, Müll, …)
- Kosten gesamt
- Ihr Anteil
- Anteil pro Mieter (aufgeschlüsselt)
- Summenprobe ✅/❌

### 9.4 Forecast-Tabelle

```
Jahr    Liquidität    Depot      Immo-Equity   Gesamt     Δ%
─────────────────────────────────────────────────────────────────
2026    142 815       187 230    157 275       487 320    -
2027    154 870       198 462    164 802       518 134    +6,3%
2028    167 280       210 116    172 802       550 198    +6,2%
...
2055    423 891       621 482    389 104     1 434 477  +194%
```

---

## 10. Troubleshooting

### 10.1 Häufige Probleme und Lösungen

#### Problem: `ModuleNotFoundError: yfinance`

**Ursache:** Optionale Abhängigkeit nicht installiert.

**Lösung:**

```bash
pip install yfinance
```

Oder: Depot-Kurse werden übersprungen, Forecast funktioniert trotzdem.

#### Problem: `psycopg2.OperationalError: could not connect to server`

**Ursache:** PostgreSQL läuft nicht oder `DATABASE_URL` ist falsch.

**Lösung:**

```bash
# Docker:
docker compose ps
docker compose up -d postgres
docker compose logs postgres

# Bare-metal:
sudo systemctl status postgresql
sudo -u postgres psql -c "\l"
```

#### Problem: Bank-Adapter timeout

**Ursache:** Bank-Server langsam oder Netzwerk instabil.

**Lösung:**

`config/banks.yaml`:

```yaml
banks:
  - name: sparkasse
    type: enable_banking
    timeout: 60            # erhöhen
    retry_attempts: 5
```

#### Problem: SMTP-Versand schlägt fehl

**Ursache:** Falsches Passwort / App-Passwort / Port blockiert.

**Lösung:**

```bash
# Manueller SMTP-Test
python3 -c "
import smtplib, ssl
ctx = ssl.create_default_context()
with smtplib.SMTP_SSL('smtp.gmail.com', 465, context=ctx) as s:
    s.login('user@gmail.com', 'app-password')
    s.sendmail('user@gmail.com', ['test@example.com'], 'Subject: Test\n\nBody')
"
```

#### Problem: Miet-Status „mehrfach" obwohl alles passt

**Ursache:** Miete wurde in mehreren Buchungen geleistet (z. B. Miete + Kaution).

**Lösung:** Erwarteten Betrag anpassen oder `rent_matcher` mit Toleranz konfigurieren.

`config/settings.yaml`:

```yaml
rent_matcher:
  tolerance_eur: 0.01
  allow_split: true
```

#### Problem: `schema_migrations` ist beschädigt

**Ursache:** Manuelle DB-Änderung ohne Migration.

**Lösung:**

```sql
-- Mit psql oder SQLite-Tool
DELETE FROM schema_migrations WHERE version='004';
-- dann:
finanzhub init    # Migration 004 wird erneut angewendet
```

#### Problem: Forecast liefert unrealistische Werte

**Ursache:** Fehlerhafte `monthly_savings` (negativ oder 0) oder extreme Rendite.

**Lösung:**

`config/forecast.yaml` prüfen:

```yaml
scenarios:
  - name: basis
    depot_rendite: 0.06         # 6%, nicht 6
    inflation: 0.02
    mietsteigerung: 0.02
```

`config/income.yaml` prüfen (Einnahmen > Ausgaben).

#### Problem: Doppelte Events

**Ursache:** Detektor läuft mehrfach in derselben Stunde (Scheduler + CLI).

**Lösung:** `event_detector` dedupliziert über `dedup_key`. Falls doch Duplikate:

```sql
SELECT type, dedup_key, count(*)
FROM events
GROUP BY type, dedup_key
HAVING count(*) > 1;
```

Falls echte Duplikate: Bug melden mit `dedup_key`.

#### Problem: Mails kommen im Spam-Ordner an

**Lösung:**

1. SPF-Eintrag in DNS prüfen
2. DKIM-Signatur aktivieren
3. `From`-Adresse zur SMTP-Domain passend
4. Inhalt prüfen (zu viele Links, Anhänge)

#### Problem: Hohe CPU-Last

**Ursache:** Forecast für 100 Jahre mit 1-Tage-Auflösung.

**Lösung:** `--years 30` reicht meist, in `config/forecast.yaml` Auflösung anpassen.

#### Problem: Datenbank wird zu groß

**Ursache:** Zu viele Transaktionen (z. B. PayPal-Sammelbuchungen).

**Lösung:**

```bash
# Alte Buchungen archivieren
finanzhub export --before 2023-01-01 --output archive-2023.json
finanzhub events purge --before 2023-01-01

# Falls SQLite → PostgreSQL migrieren (siehe Rezept 8.4)
```

### 10.2 Diagnose-Befehle

```bash
# Vollständiger System-Status
finanzhub status --verbose

# Letzte Logs
tail -f output/logs/finanzhub.log

# DB-Statistik
sqlite3 /var/lib/finanzhub/finanzhub.db "SELECT count(*) FROM transactions;"

# Aktive Konfiguration anzeigen
finanzhub config show

# Cache leeren
rm -rf output/cache/*
finanzhub pull-all --force-price-refresh
```

### 10.3 Wo finde ich Hilfe?

1. Diese Dokumentation (USAGE.md, DEVELOPMENT.md, INTEGRATION.md)
2. In-App-Hilfe: `finanzhub <command> --help`
3. GitHub Issues: [github.com/bonorumsoft/finanzhub/issues](https://github.com/bonorumsoft/finanzhub/issues)
4. Logs: `output/logs/finanzhub.log`

---

### 3.1.5 Inbox-Kommandos (Beleg-Verarbeitung)

| Befehl                                            | Zweck                                      |
| ------------------------------------------------- | ------------------------------------------- |
| `finanzhub inbox run`                             | Inbox einmal verarbeiten                   |
| `finanzhub inbox status [--days 90]`              | Übersicht + ungematchte Belege              |
| `finanzhub inbox list [--status X]`               | Belege tabellarisch                         |
| `finanzhub inbox show <id>`                       | Details zu einem Beleg                     |
| `finanzhub inbox match <id> <tx_id>`              | Manuelles Matching                          |
| `finanzhub inbox tag <id> <tag>`                  | Tag setzen (z. B. `steuerrelevant`)         |
| `finanzhub inbox export [--year 2026]`            | CSV-Export für Steuererklärung              |
| `finanzhub inbox test-extraction <image_or_pdf>`  | KI-Extraktion testen (ohne DB-Effekt)       |

**Beispiel-Workflow:**

```bash
# Nach Einkauf mit dem Smartphone ein Foto machen → an belege@… senden
# (Scheduler pollt alle 60 s automatisch, oder manuell triggern)
finanzhub inbox run
# → Mails: 1, verarbeitet: 1, extrahiert: 1, gematched: 1, fehler: 0

finanzhub inbox status
# → Ungematchte Belege (1):
# → ┌────┬────────────┬────────┬──────────────┐
# → │ ID │ Datum      │ Betrag │ Händler      │
# → │ 23 │ 2026-06-04 │  47,90 │ MediaMarkt   │
# → └────┴────────────┴────────┴──────────────┘

# Manuelles Matching (KI hat die TX nicht gefunden)
finanzhub inbox match 23 TX-2026-06-04-001
# → ✅ Beleg #23 ↔ Transaktion TX-2026-06-04-001

# Steuerlich markieren für die nächste Erklärung
finanzhub inbox tag 23 steuerrelevant
# → ✅ Tag 'steuerrelevant' auf Beleg #23 gesetzt

# Export für den Steuerberater
finanzhub inbox export --year 2026 --output steuer-2026.csv
# → ✅ 142 Belege nach steuer-2026.csv exportiert
```

Ausführliche Doku: [INBOX.md](INBOX.md).

---

## 11. Glossar

| Begriff              | Bedeutung                                                                 |
| -------------------- | ------------------------------------------------------------------------- |
| **Annutät**          | Monatliche Rate für ein Darlehen (Zins + Tilgung)                          |
| **Append-only**      | Daten werden nur hinzugefügt, nie geändert/gelöscht                       |
| **Asset**            | Vermögenswert (Bankkonto, Depot-Position, Immobilie)                      |
| **Brutto­rendite**   | Jahresmiete / Kaufpreis                                                   |
| **Consent**          | Einwilligung des Bankkunden (DSGVO + PSD2)                                 |
| **Coverage**         | Test-Abdeckung in Prozent                                                  |
| **Cron**             | Zeitplaner (5-Felder-Syntax)                                              |
| **DSGVO**            | EU-Datenschutz-Grundverordnung                                            |
| **Equity**           | Eigenkapital-Anteil (z. B. Immobilien-Wert − Restschuld)                  |
| **FinTS**            | FinTS-Protokoll (ehemals HBCI) für deutsche Banken                        |
| **Forecast**         | Vermögens-Vorschau                                                         |
| **Idempotent**       | Mehrfach-Ausführung = gleiches Ergebnis                                    |
| **Liquidität**       | Verfügbare Bank­bestände                                                   |
| **Mietspiegel**      | Marktgerechte Vergleichsmiete                                              |
| **NK**               | Nebenkosten (Betriebs­kosten, umlagefähig)                                |
| **Netto­rendite**    | (Jahresmiete − Bewirtschaftung) / Eigenkapital                            |
| **Peters-Formel**    | (Jahresmiete − 0,20 × KP) / 0,80 × KP × 100                              |
| **PSD2**             | EU-Zahlungsdienste-Richtlinie                                              |
| **PWA**              | Progressive Web App (für Phase 14 geplant)                                 |
| **Read-only**        | Kein Schreibzugriff auf externe Systeme                                    |
| **Retention**        | Aufbewahrungs­dauer von Daten/Logs                                        |
| **Restschuld**       | Verbleibende Darlehens­schuld                                              |
| **SPF**              | Sender Policy Framework (DNS-Eintrag gegen Spam)                          |
| **STAMP**            | Strategies to Trust Amidst Perfecting and Manipulation                    |
| **Substanz­verzehr** | Vermögens­rückgang aus laufendem Cashflow                                  |
| **TAN**              | Transaktions­nummer (z. B. photoTAN, chipTAN)                              |
| **Tilgung**          | Jährliche Rückzahlung des Darlehens                                        |
| **TLR**              | Tilgungsleistungs- und Zinszahlungs-Verhältnis                            |
| **TUI**              | Terminal User Interface                                                    |
| **YTD**              | Year-to-Date                                                               |
| **Zinssatz**         | Jährlicher Zins für ein Darlehen (Dezimal, 0,031 = 3,1%)                  |

---

## 12. Web-UI Dashboard

FinanzHub hat ein integriertes Web-UI (Flask) für Browser-Zugriff.

### 12.1 Aktivierung

Das Web-UI startet **automatisch** auf Port 8080, sobald der Container läuft. Steuerbar via Env-Vars:

| Variable         | Default   | Beschreibung                          |
| ---------------- | --------- | ------------------------------------- |
| `WEB_ENABLED`    | `true`    | Web-UI ein/aus                        |
| `WEB_PORT`       | `8080`    | HTTP-Port                              |
| `WEB_HOST`       | `0.0.0.0` | Bind-Addresse (0.0.0.0 = alle IFs)   |
| `WEB_PASSWORD`   | (auto)    | Login-Passwort (wenn leer: temporär im Log) |

### 12.2 Login

`http://<dein-server>:8080` → Passwort eingeben. Wird kein `WEB_PASSWORD` gesetzt, generiert das System ein temporäres Passwort und loggt es beim Start als `WARNING`:

```
WARNING app.web.auth: Kein WEB_PASSWORD gesetzt – verwende temporäres Passwort: aB3x…
```

### 12.3 Seiten

| Seite          | Beschreibung                                                     |
| -------------- | ---------------------------------------------------------------- |
| **Dashboard**  | Vermögen (4 Cards), Nettovermögen-Chart (90d), Kontostände, Letzte Buchungen, Ereignisse |
| **Buchungen**  | Transaktionsliste mit Zeitfilter (7d/30d/90d/1J), Summenzeile   |
| **Belege**     | Beleg-Inbox mit Status-Filter (alle/pending/extracted/matched/error) |
| **Einstellungen** | Read-only-Ansicht der geladenen YAML-Configs                  |

---

**Weiterführend:**

- [Entwickler­dokumentation](DEVELOPMENT.md) — Architektur, Module, Erweiterung
- [Integrations­dokumentation](INTEGRATION.md) — Banken, SMTP, Datenbank
- [README](../README.md) — Übersicht, Inbetriebnahme
