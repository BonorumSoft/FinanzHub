# Beleg-Inbox (Receipt Ingestion)

Die **Beleg-Inbox** ist die *Kassenbon-Schnittstelle* von FinanzHub. Sie verarbeitet **automatisch** Kassenbons und Rechnungen, die per E-Mail an eine konfigurierte Inbox-Adresse geschickt werden — entweder als Foto (JPEG/PNG/HEIC) oder als PDF.

Das System extrahiert **Datum, Betrag, Händler, Kategorie** per KI, gleicht das Ergebnis mit vorhandenen Banktransaktionen ab und legt alles in einer durchsuchbaren Datenbank ab.

## Inhaltsverzeichnis

1. [Konzept](#1-konzept)
2. [Architektur](#2-architektur)
3. [Erstkonfiguration](#3-erstkonfiguration)
4. [KI-Provider wählen](#4-ki-provider-wählen)
5. [Tägliche Workflows](#5-tägliche-workflows)
6. [CLI-Referenz](#6-cli-referenz)
7. [Rezepte](#7-rezepte)
8. [Troubleshooting](#8-troubleshooting)
9. [Sicherheit & Datenschutz](#9-sicherheit--datenschutz)

---

## 1. Konzept

### Was die Inbox leistet

```
📸  📧                                🧠                              💾
Foto machen  →  E-Mail an Inbox  →  KI-Extraktion  →  DB  +  Bank-Match
oder PDF         (IMAP-Polling)     (lokal oder Cloud)    (Konfidenz-Score)
```

- **Vollautomatisch**: einmal konfiguriert, kein manueller Eingriff mehr
- **Read-only** zu Banken (kein Auslösen von Zahlungen)
- **Privacy first**: lokale KI (LM Studio) als Default, Cloud nur als Fallback
- **Idempotent**: jede Mail nur einmal verarbeitet (UID-basiert)
- **Append-only Audit-Trail**: kein Löschen, nur Markieren (`steuerrelevant`, Tags)

### Was die Inbox *nicht* macht

- Keine Buchungen erstellen — nur **Matching** zu bestehenden Banktransaktionen
- Keine doppelte Buchungserkennung (das ist Aufgabe der `payment_monitor`)
- Keine Steuerberechnung — nur Markierung für späteren Export

---

## 2. Architektur

```
┌────────────────────────────────────────────────────────────────────┐
│  Scheduler (alle 60 s)                                             │
│      │                                                             │
│      ▼                                                             │
│  InboxEngine.process_inbox()                                       │
│      │                                                             │
│      ├─► MailFetcher.fetch_new()       (IMAP, Whitelist)           │
│      │     │                                                       │
│      │     └─► IncomingMail[] (mit Attachments)                    │
│      │                                                             │
│      ├─► AttachmentHandler.process()   (Routing Bild vs. PDF)      │
│      │     │                                                       │
│      │     └─► ImageConverter (JPEG/PNG/HEIC → PDF)               │
│      │                                                             │
│      ├─► ReceiptExtractor.extract()    (Provider-Routing)          │
│      │     │                                                       │
│      │     ├─► LM Studio  (lokal, multimodal)   ←── Default        │
│      │     ├─► Ollama     (lokal, multimodal)                     │
│      │     ├─► OpenAI     (gpt-4o-mini)                          │
│      │     └─► Anthropic  (claude-haiku)     ←── Fallback        │
│      │                                                             │
│      ├─► TransactionMatcher.find_match() (Scoring 0.0–1.0)         │
│      │                                                             │
│      └─► Persist + Confirmation-Mail                               │
└────────────────────────────────────────────────────────────────────┘
```

### Status-Lebenszyklus

```
pending ──► extracted ──► matched  (≥ 0.75 Konfidenz, TX gefunden)
                │  ╲
                │   ╲─► no_match    (≤ 0.75 ODER keine Kandidaten)
                │    ╲
                │     ► manual_review
                │
                └────► error        (KI- oder DB-Fehler)
```

### Scoring (TransactionMatcher)

| Bedingung                                              | Konfidenz |
| ------------------------------------------------------ | --------- |
| Exakter Betrag + Datum im Fenster + Händler-Substring  | **0.95**  |
| Exakter Betrag + Datum im Fenster                      | **0.85**  |
| Fuzzy-Betrag (±0,50 € oder 2 %) + Datum im Fenster     | **0.70**  |
| Nur Betrag (innerhalb erweitertes Fenster)             | **0.50**  |
| Kein Match                                             | 0.0       |

`min_confidence_for_match: 0.75` (default) → alles darunter landet in `manual_review`.

---

## 3. Erstkonfiguration

### 3.1 Voraussetzungen

| Komponente   | Hinweis                                                  |
| ------------ | -------------------------------------------------------- |
| IMAP-Postfach | z. B. `belege@deinedomain.de` (gmail, posteo, mailbox.org) |
| KI-Provider  | Mindestens einer muss erreichbar sein                    |
| Python-Pakete | `img2pdf`, `Pillow`, `pdf2image` (in `requirements.txt`) |
| HEIC-Support | `pip install pillow-heif` (optional, für iPhone-Fotos)   |
| Poppler      | System-Paket für `pdf2image` (`apt install poppler-utils`, `brew install poppler`) |

### 3.2 Konfigurationsdatei `config/inbox.yaml`

Beim ersten Start wird die Datei aus `config.example/inbox.yaml` kopiert. Wichtige Felder:

```yaml
inbox:
  enabled: true                                    # ← aktivieren

  imap:
    host: "imap.gmail.com"
    port: 993
    use_ssl: true
    username: ""            # aus .env: INBOX_IMAP_USER
    password: ""            # aus .env: INBOX_IMAP_PASS
    folder: "INBOX"
    poll_interval_seconds: 60
    mark_as_read: true
    move_to_folder: "Belege/Verarbeitet"           # leer = nicht verschieben

  allowed_senders:                                  # ← PFLICHT für Produktion
    - "tjorben@example.com"
    - "fenja@example.com"
    # leer = alle Absender akzeptiert (nicht empfohlen)
```

### 3.3 `.env` ergänzen

```bash
# Beleg-Inbox IMAP
INBOX_IMAP_USER=belege@example.com
INBOX_IMAP_PASS=app-passwort-oder-normal-mit-app-passwort

# Optional: Cloud-Provider (nur wenn nicht LM Studio)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# Optional: SMTP für Bestätigungsmails
INBOX_SMTP_HOST=smtp.gmail.com
INBOX_SMTP_PORT=587
INBOX_SMTP_USER=...
INBOX_SMTP_PASS=...
INBOX_SMTP_FROM=finanzhub@example.com
```

### 3.4 Aktivierung prüfen

```bash
finanzhub init          # wendet Migration 005_add_receipts an
finanzhub inbox status  # zeigt 0 Belege
```

### 3.5 Erster Test-Beleg

```bash
# Schicke ein Foto eines Kassenbons an die Inbox-Adresse
# Innerhalb von 60 s:
finanzhub inbox run
finanzhub inbox list --status matched
```

---

## 4. KI-Provider wählen

| Provider       | Datenschutz     | Kosten  | Modell             | Empfehlung                          |
| -------------- | --------------- | ------- | ------------------ | ----------------------------------- |
| **LM Studio**  | ✅ 100 % lokal  | 0 €     | qwen2.5-vl-7b      | **Default** — auf eigenem Server    |
| **Ollama**     | ✅ 100 % lokal  | 0 €     | llava:13b          | Alternative zu LM Studio            |
| **OpenAI**     | ⚠️ Cloud (USA) | ~$0.01  | gpt-4o-mini        | Schnellster Fallback bei Timeouts   |
| **Anthropic**  | ⚠️ Cloud (USA) | ~$0.01  | claude-haiku-4-5   | Bester Fallback bei komplexen Bons  |

### 4.1 LM Studio (empfohlen)

1. **Download**: [lmstudio.ai](https://lmstudio.ai/) — läuft auf macOS/Windows/Linux
2. **Modell laden**: z. B. `qwen2.5-vl-7b-instruct` (multimodal!)
3. **Server starten**:
   - Tab "Local Server" → Model auswählen → Start
   - Endpunkt: `http://localhost:1234/v1` (LM Studio zeigt die URL an)
4. **Konfiguration** (`inbox.yaml`):

```yaml
extraction:
  provider: "local_lm_studio"
  local_lm_studio:
    base_url: "http://192.168.3.160:1234/v1"  # IP oder hostname
    model: "qwen2.5-vl-7b-instruct"
    timeout_seconds: 30
```

> **GPU-Hinweis**: 7B-Modelle brauchen ≥ 8 GB VRAM. Für ältere Hardware: 3B-Variante.

### 4.2 Ollama

1. **Installation**: `curl -fsSL https://ollama.com/install.sh | sh`
2. **Modell laden**: `ollama pull llava:13b`
3. **Konfiguration**:

```yaml
extraction:
  provider: "ollama"
  ollama:
    base_url: "http://localhost:11434"
    model: "llava:13b"
    timeout_seconds: 45
```

### 4.3 OpenAI

1. **API-Key**: [platform.openai.com](https://platform.openai.com/api-keys)
2. **`.env`**: `OPENAI_API_KEY=sk-...`
3. **Konfiguration**:

```yaml
extraction:
  provider: "openai"
  openai:
    api_key: ""        # aus .env
    model: "gpt-4o-mini"
    timeout_seconds: 20
```

### 4.4 Anthropic

1. **API-Key**: [console.anthropic.com](https://console.anthropic.com/)
2. **`.env`**: `ANTHROPIC_API_KEY=sk-ant-...`
3. **Konfiguration**:

```yaml
extraction:
  provider: "anthropic"
  anthropic:
    api_key: ""        # aus .env
    model: "claude-haiku-4-5-20251001"
    timeout_seconds: 20
```

### 4.5 Fallback-Konfiguration

Bei Timeouts oder Fehlern des primären Providers wird automatisch der `fallback_provider` versucht:

```yaml
extraction:
  provider: "local_lm_studio"
  fallback_provider: "anthropic"     # wird genutzt wenn LM Studio fehlschlägt
```

### 4.6 Modell-Validierung

Beim Start prüft FinanzHub, ob das konfigurierte Modell multimodal ist (Bildverständnis). **Warnung** beim Start wenn nicht:

```
WARNING  Modell llama-3-8b wirkt nicht multimodal — Belege können nicht gelesen werden.
```

Erkannt werden Namen mit `vl`, `vision`, `llava`, `4o`, `haiku`, `opus`, `sonnet`.

---

## 5. Tägliche Workflows

### 5.1 Morgens: Inbox-Status prüfen

```bash
finanzhub inbox status
```

```
Beleg-Inbox Status
═══════════════════════════════════════════════════
  Ausstehend (pending):          0
  Extrahiert, nicht gematched:   2
  Erfolgreich gematched:        47
  Fehler:                        0
  Gesamt (letzte 90 Tage):      49

Ungematchte Belege (2):
┌────┬────────────┬────────┬──────────────────┐
│ ID │ Datum      │ Betrag │ Händler          │
├────┼────────────┼────────┼──────────────────┤
│ 23 │ 2026-06-04 │  47,90 │ MediaMarkt       │
│ 22 │ 2026-06-02 │ 124,50 │ Bauhaus          │
└────┴────────────┴────────┴──────────────────┘
```

### 5.2 Manuell triggern (z. B. nach Versand eines Belegs)

```bash
finanzhub inbox run
```

Ausgabe:

```
Mails: 2, verarbeitet: 3, extrahiert: 3, gematched: 2, fehler: 0
```

### 5.3 Belege auflisten

```bash
# Alle der letzten 7 Tage
finanzhub inbox list --days 7

# Nur nicht-gematchte
finanzhub inbox list --status no_match
finanzhub inbox list --status manual_review

# Fehler zur Diagnose
finanzhub inbox list --status error
```

### 5.4 Details zu einem Beleg

```bash
finanzhub inbox show 23
```

Zeigt alle Felder (Datum, Betrag, Händler, extrahierter JSON, Match-Info, Pfad zur PDF).

### 5.5 Manuelles Matching (KI-Fehler korrigieren)

```bash
# Suche die passende Transaktion
finanzhub rent-check 2026-06
# → finde TX-123, 47,90 € bei MediaMarkt

# Verknüpfe manuell
finanzhub inbox match 23 TX-123
```

### 5.6 Steuerlich relevant markieren

```bash
finanzhub inbox tag 23 steuerrelevant
```

Markiert den Beleg in der Spalte `steuerrelevant` und legt einen Eintrag in `receipt_tags` an.

### 5.7 Test-Extraction (KI lokal ausprobieren)

```bash
finanzhub inbox test-extraction kassenbon.jpg
```

Ausgabe:

```
Datum:        2026-06-04
Betrag:       47.9 EUR
Händler:      REWE Stuhr
Kategorie:    Lebensmittel
Rechnung:     False
Zahlungsbeleg:False
MwSt:         -
Rechnungsnr.: -
Konfidenz:    92%
Modell:       qwen2.5-vl-7b-instruct
```

Nützlich um zu prüfen, ob das Modell richtig konfiguriert ist — **ohne** DB-Schreibung.

### 5.8 Export für die Steuererklärung

```bash
finanzhub inbox export --year 2026 --output steuer-2026.csv
```

Erzeugt CSV mit allen Belegen eines Jahres (alle Spalten).

---

## 6. CLI-Referenz

Vollständige Liste aller `finanzhub inbox`-Kommandos:

| Kommando                                                     | Zweck                                              |
| ------------------------------------------------------------ | -------------------------------------------------- |
| `finanzhub inbox run`                                        | Inbox einmal verarbeiten (manuell)                 |
| `finanzhub inbox status [--days 90]`                         | Übersicht (Status + ungematchte Tabelle)           |
| `finanzhub inbox list [--status X] [--days N]`               | Belege tabellarisch auflisten                      |
| `finanzhub inbox show <id>`                                  | Details zu einem Beleg                             |
| `finanzhub inbox match <id> <tx_id>`                        | Manuelles Matching (überschreibt KI)               |
| `finanzhub inbox tag <id> <tag>`                             | Tag setzen (`steuerrelevant`, `privat`, …)         |
| `finanzhub inbox export [--year 2026] [--output X.csv]`      | CSV-Export                                         |
| `finanzhub inbox test-extraction <pdf_or_image>`             | KI-Extraktion testen (ohne DB-Effekt)              |

**Exit-Codes:** `0` = OK, `1` = Fehler, `2` = Inbox deaktiviert.

---

## 7. Rezepte

### 7.1 Niedrige Konfidenz global anheben

Wenn viele Belege in `manual_review` landen:

```yaml
# inbox.yaml
extraction:
  min_confidence_for_match: 0.50   # niedriger → mehr auto-matches
```

### 7.2 Beleg nachverarbeiten (KI verbessert)

```sql
-- status zurücksetzen, damit Inbox-Run erneut extrahiert
UPDATE receipts SET status = 'pending', matched_transaction_id = NULL
WHERE id = 23;
```

Anschließend `finanzhub inbox run` (oder per IMAP-Polling warten).

### 7.3 Backup der Original-PDFs

Die PDFs liegen unter `storage_path` (default: `/app/output/receipts`).
Diese sind **nicht** in der DB — separat sichern:

```bash
tar -czf receipts-2026-06.tar.gz /app/output/receipts/
```

### 7.4 Storage-Pfad ändern (z. B. NAS-Mount)

`inbox.yaml`:

```yaml
storage_path: "/mnt/nas/finanzhub/receipts"
```

Oder via `.env` (überschreibt YAML):

```bash
INBOX_STORAGE_PATH=/mnt/nas/finanzhub/receipts
```

### 7.5 Whitelist erweitern (Haushaltsmitglieder)

```yaml
allowed_senders:
  - "tjorben@example.com"
  - "fenja@example.com"
  - "haushalt+shared@example.com"
```

### 7.6 Storage aufräumen (alte PDFs)

```bash
# Belege älter als 2 Jahre löschen (Vorsicht!)
find /app/output/receipts -name "*.pdf" -mtime +730 -delete
```

### 7.7 Debugging: was schickt die KI?

```bash
finanzhub inbox show 23
# Ganz unten: extraction_raw → kompletter JSON der KI-Antwort
```

Oder in der DB:

```sql
SELECT id, extracted_merchant, extracted_amount, extracted_confidence, extraction_raw
FROM receipts
WHERE status = 'manual_review'
ORDER BY received_at DESC;
```

### 7.8 Mehrere Empfänger für Bestätigungsmail

Aktuell wird an den Absender geantwortet. Für mehrere CCs:

```yaml
# inbox.yaml
confirmation:
  enabled: true
  reply_to_sender: true
  cc: ["buchhaltung@example.com"]      # (geplant Phase 14)
```

### 7.9 Mobile Benachrichtigung über Ntfy

```yaml
# inbox.yaml (Phase 14)
alerts:
  on_new_beleg:
    - type: ntfy
      topic: "finanzhub-tjorben"
      priority: default
```

---

## 8. Troubleshooting

### 8.1 KI liefert leere Felder

**Symptom:** Belege in `manual_review`, `extracted_merchant = NULL`.

**Ursache:** Modell erkennt Text nicht (schlechte Fotoqualität, exotische Schrift).

**Lösung:**

1. Fotoqualität prüfen: ≥ 1 MP, scharf, gute Beleuchtung
2. Anderes Modell testen: `qwen2.5-vl-7b` → `gpt-4o-mini` (Cloud, oft besser)
3. `finanzhub inbox test-extraction bild.jpg` — wiederholt aufrufen, jeder Lauf ist unabhängig
4. Manuell korrigieren: `finanzhub inbox match 23 TX-123`

### 8.2 IMAP-Verbindung schlägt fehl

**Symptom:** Logs zeigen `IMAP offline` oder `Login failed`.

**Lösung:**

```bash
# Manueller IMAP-Test
python3 -c "
import imaplib
with imaplib.IMAP4_SSL('imap.gmail.com', 993) as m:
    m.login('user@gmail.com', 'app-passwort')
    print('OK')
"
```

Bei Gmail: **App-Passwort** erforderlich (2FA + App-Passwörter).
Bei Outlook: OAuth2-Token nötig (Phase 14).

### 8.3 HEIC-Fotos werden nicht konvertiert

**Symptom:** Status `error`, `error_message: "pillow-heif nicht installiert"`.

**Lösung:**

```bash
pip install pillow-heif
# In Docker-Image: requirements.txt ergänzen → rebuild
```

### 8.4 PDF-Erstellung schlägt fehl (Poppler fehlt)

**Symptom:** `RuntimeError: Unable to get page count` oder `pdf2image` Fehler.

**Lösung:**

```bash
# Ubuntu/Debian
sudo apt install poppler-utils

# macOS
brew install poppler

# Alpine (Docker)
apk add poppler
```

### 8.5 Beleg wird mehrfach verarbeitet

**Ursache:** IMAP `mark_as_read: true` funktioniert nicht (z. B. weil Mail-Client parallel läuft).

**Lösung:**

1. **Sicherste Variante**: `move_to_folder: "Belege/Verarbeitet"` setzen — Mail wird physisch verschoben
2. Whitelist für `INBOX`-Folder aktivieren (IMAP-Provider-spezifisch)

### 8.6 `Status: error`, `error_message: pdf kaputt`

**Ursache:** Beleg-PDF ist beschädigt oder passwortgeschützt.

**Lösung:**

1. Original-PDF in Mailbox öffnen
2. Wenn tatsächlich kaputt: manuell `status = 'manual_review'` setzen, später nachverarbeiten
3. Falls Standardpasswort: PDF vorher entsperren

### 8.7 Hohe CPU-Last durch LM Studio

**Lösung:**

- Kleineres Modell wählen: `qwen2.5-vl-3b-instruct` statt 7B
- Niedrigere `max_tokens` (in `receipt_extractor.py: _extract_lm_studio`)
- `poll_interval_seconds` erhöhen (weniger häufig pollen)

### 8.8 `min_confidence_for_match` zu streng

Wenn fast alle Belege in `manual_review`:

```yaml
extraction:
  min_confidence_for_match: 0.60   # war 0.75
```

---

## 9. Sicherheit & Datenschutz

### 9.1 Bedrohungs­modell

| Bedrohung                          | Mitigation                                         |
| ---------------------------------- | -------------------------------------------------- |
| **Fremde schicken Phishing**       | `allowed_senders` Whitelist (Pflicht in Produktion) |
| **Beleg enthält sensible Daten**   | Provider-Wahl: lokal = kein Cloud-Leak              |
| **KI halluziniert Beträge**        | `min_confidence_for_match` + Validierung (`< 100k`) |
| **PDF-Speicherort unsicher**       | `storage_path` außerhalb Web-Root, Modus 0700      |
| **IMAP-Passwort im Klartext**      | `.env` mit `chmod 600`, oder Docker-Secrets        |
| **Bestätigungsmail an falschen**   | `allowed_senders` + SMTP-Auth                      |

### 9.2 Whitelist-Pflicht

> **Ohne `allowed_senders` Whitelist keine Produktion.**

Leere Whitelist = alle Absender werden verarbeitet. Ein Angreifer mit Ihrer Inbox-Adresse könnte:

- Belege einschleusen, die als „bezahlt" gematcht werden
- Ihr Volumen künstlich aufblähen (Cost)
- Bei Cloud-Providern: Daten exfiltrieren

**Empfehlung:**

```yaml
allowed_senders:
  - "tjorben@example.com"      # exact
  - "+49.+@example.com"        # pattern (gmail filter style)
```

### 9.3 Provider-Wahl nach Datenklasse

| Datenklasse          | Empfohlener Provider     |
| -------------------- | ------------------------ |
| Eigene Kassenbons    | LM Studio (lokal)        |
| Geschäftsreise-Bons  | LM Studio oder Anthropic |
| Steuerliche Belege   | LM Studio (kein Cloud)   |
| Medizinische Rechnungen | LM Studio (DSGVO)     |

### 9.4 Speicherort

```yaml
storage_path: "/app/output/receipts"   # default
```

Sicherheits-Hinweise:

- **Modus 0700** auf dem Verzeichnis: `chmod 700 /app/output/receipts`
- **Nicht** im Web-Root exponieren
- **Backup verschlüsseln** (GPG, LUKS)

### 9.5 Logging

`app/logger.py` filtert sensible Felder aus Logs. Belege werden nur als **Metadaten** geloggt (Dateigröße, MIME-Type, Händler-Name), niemals der Inhalt selbst.

### 9.6 DSGVO

| Anforderung                | Umsetzung                                        |
| -------------------------- | ------------------------------------------------ |
| Datenminimierung           | Nur extrahierte Felder + Pfad zum Original-PDF   |
| Speicherbegrenzung         | `storage_path` mit Retention (Cron-Aufräumen)    |
| Auskunftsrecht             | `finanzhub inbox export --year 2026`             |
| Recht auf Löschung         | `DELETE FROM receipts WHERE id = 23; rm /app/.../...pdf` |
| Privacy by Default         | Lokaler Provider als Default                     |

---

**Weiterführend:**

- [INTEGRATION.md](INTEGRATION.md) — IMAP, SMTP, Provider-Details
- [USAGE.md](USAGE.md) — Allgemeine CLI-Workflows
- [DEVELOPMENT.md](DEVELOPMENT.md) — Architektur der Inbox-Module
- [README.md](../README.md) — Projekt-Übersicht
