# FinanzHub mit Portainer betreiben

Diese Anleitung zeigt, wie FinanzHub in **Portainer** (Docker-UI) ausgerollt, gestartet und gewartet wird.

## Voraussetzungen

| Komponente       | Anforderung                            |
| ---------------- | -------------------------------------- |
| Portainer        | CE 2.19+ oder EE                       |
| Docker Host      | Linux (oder Docker Desktop)            |
| RAM              | ≥ 2 GB freier Speicher                 |
| Speicher         | ≥ 5 GB freier Speicher                 |
| Netzwerk         | Ausgehende HTTPS zu Banken + SMTP      |

Falls Portainer noch nicht läuft:

```bash
# Portainer CE installieren (einmalig)
docker volume create portainer_data
docker run -d -p 9443:9443 \
  --name portainer \
  --restart=always \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v portainer_data:/data \
  portainer/portainer-ce:latest
```

URL: `https://<dein-server>:9443`

---

## Deployment in 5 Schritten

### Schritt 1: Stacks → Add stack

In Portainer links auf **Stacks** → **+ Add stack**.

Wähle eine von drei Build-Methoden:

#### Option A: Git-Repository (empfohlen)

| Feld             | Wert                                                  |
| ---------------- | ----------------------------------------------------- |
| Name             | `finanzhub`                                           |
| Build method     | **Repository**                                        |
| Repository URL   | `https://github.com/bonorumsoft/finanzhub.git`        |
| Repository reference | `main`                                            |
| Compose path     | `docker-compose.portainer.yml`                        |
| Auto-update      | aktivieren (Pulls Updates automatisch)                |

**Vorteil:** Updates kommen per "Pull and redeploy".

#### Option B: Web-Editor

1. Build method → **Web editor**
2. Kompletten Inhalt von `docker-compose.portainer.yml` einfügen
3. Speichern

#### Option C: Upload

1. Build method → **Upload**
2. Datei `docker-compose.portainer.yml` auswählen
3. Speichern

### Schritt 2: Environment-Variablen setzen

Im Stack-Editor unter **Environment variables** > **Advanced mode**:

| Variable           | Wert                                   | Pflicht |
| ------------------ | -------------------------------------- | ------- |
| `DB_PASSWORD`      | `<openssl rand -hex 16>` (32 Zeichen)  | **ja**  |
| `TZ`               | `Europe/Berlin`                        | nein    |
| `LOG_LEVEL`        | `INFO`                                 | nein    |
| `SMTP_HOST`        | `smtp.gmail.com`                       | nein    |
| `SMTP_PORT`        | `587`                                  | nein    |
| `SMTP_USER`        | `finanzhub@example.com`                | nein    |
| `SMTP_PASSWORD`    | `<app-passwort>`                       | nein    |
| `INBOX_IMAP_USER`  | `belege@example.com`                   | nein (für Inbox) |
| `INBOX_IMAP_PASS`  | `<app-passwort>`                       | nein (für Inbox) |
| `OPENAI_API_KEY`   | `sk-...`                               | nein (Cloud-Provider) |
| `ANTHROPIC_API_KEY`| `sk-ant-...`                           | nein (Cloud-Fallback) |
| `INBOX_SMTP_HOST`  | `smtp.gmail.com`                       | nein (Bestätigungs-Mail) |

> **Wichtig:** `DB_PASSWORD` MUSS gesetzt sein, sonst startet der Container nicht!

Alternativ: **Load environment variables from .env file** aktivieren und `.env.portainer.example` als Vorlage verwenden (anpassen nicht vergessen).

### Schritt 3: Stack deployen

Klick auf **Deploy the stack**. Portainer erstellt:

- 2 Services (`finanzhub`, `postgres`)
- 4 Volumes (`finanzhub_postgres_data`, `finanzhub_config`, `finanzhub_output`, `finanzhub_logs`)
- 1 Netzwerk (`finanzhub_net`)

Dauer: 1–3 Minuten (Image-Download + DB-Init).

### Schritt 4: Container-Status prüfen

Portainer → **Stacks** → `finanzhub` → Übersicht:

| Service     | Erwarteter Status         |
| ----------- | ------------------------- |
| `finanzhub` | 🟢 running (healthy)      |
| `postgres`  | 🟢 running (healthy)      |

Falls `unhealthy`: Klick auf den Container → **Logs** → Fehlermeldung prüfen.

### Schritt 5: Initialisierung

> **Config-Auto-Init:** Beim ersten Start kopiert FinanzHub automatisch alle `config.example/*`-YAML-Dateien in das Volume `finanzhub_config`. Es sind **keine manuellen Datei-Kopien** nötig — der Stack läuft sofort mit Dummy-Werten. Du kannst die Configs später via Portainer-Volumes-Browser oder `docker exec` anpassen.

Container → **Console** → **Connect**:

```bash
finanzhub init              # Migrationen anwenden
finanzhub pull demo         # Demo-Bank-Daten laden
finanzhub wealth            # Vermögen anzeigen
```

Damit ist FinanzHub betriebsbereit. Die Cron-Jobs laufen automatisch im Hintergrund.

### Beleg-Inbox (optional)

Wenn `inbox.enabled: true` in `config/inbox.yaml` gesetzt ist, pollt der Scheduler automatisch alle 60 s die konfigurierte IMAP-Inbox:

```bash
# In Container-Console
finanzhub inbox status
finanzhub inbox run         # manuell triggern
```

Vollständige Doku: **[INBOX.md](INBOX.md)** — KI-Provider-Konfiguration, LM Studio-Setup, Sicherheits-Hinweise.

---

## Konfiguration anpassen

### Konfig-Dateien bearbeiten

Die YAML-Configs liegen im Volume `finanzhub_config`. Drei Zugriffswege:

#### 1. Über Portainer Volumes UI

1. **Volumes** → `finanzub_config`
2. Auf den **Browse**-Button (oder `du -sh /var/lib/docker/volumes/finanzhub_config`)
3. Datei direkt im Browser editieren

#### 2. Über exec in den Container

```bash
docker exec -it finanzhub bash
vi /app/config/banks.yaml
exit
```

#### 3. Per `bind mount` (in docker-compose.portainer.yml ändern)

```yaml
volumes:
  - /pfad/auf/host/config:/app/config:ro
```

Danach Stack neu deployen.

### Secrets verwalten

#### enable-banking-Privatschlüssel

1. Portainer → **Secrets** → **+ Add secret**
2. Name: `ebanking_key`
3. Wert: Inhalt der `.pem`-Datei einfügen
4. In `docker-compose.portainer.yml` referenzieren:

```yaml
services:
  finanzhub:
    secrets:
      - ebanking_key
secrets:
  ebanking_key:
    external: true
```

Pfad in der App: `/run/secrets/ebanking_key`. In `config/banks.yaml`:

```yaml
banks:
  - name: sparkasse
    type: enable_banking
    key_path: /run/secrets/ebanking_key
```

---

## Updates einspielen

### Per Auto-Update (Option A — Git-Repository)

Portainer → Stacks → `finanzhub` → **Pull and redeploy**.

### Manuell

1. Portainer → Stacks → `finanzhub` → **Editor**
2. Bei Git-Repo: Reference auf neue Version setzen (z. B. Tag `v0.2.0`)
3. Klick **Deploy the stack**
4. Portainer zieht das neue Image und startet Container neu

Migrations-Sicherheit: `finanzhub init` ist idempotent — neue Migrationen werden automatisch angewendet.

---

## Backups

### PostgreSQL-Backup

In Portainer → **Stacks** → `finanzhub` → `postgres` Container → **Console**:

```bash
# Backup in Container
pg_dump -U finanzhub finanzhub > /tmp/backup-$(date +%F).sql

# Auf Host kopieren
docker cp finanzhub_db:/tmp/backup-2026-06-15.sql ./backup-2026-06-15.sql
```

Oder als Cron im Stack hinzufügen:

```yaml
services:
  backup:
    image: postgres:16-alpine
    depends_on:
      - postgres
    volumes:
      - ./backups:/backups
    environment:
      PGPASSWORD: ${DB_PASSWORD}
    entrypoint: |
      sh -c '
        while true; do
          pg_dump -h postgres -U finanzhub finanzhub > /backups/backup-$$(date +%F).sql
          find /backups -type f -mtime +14 -delete
          sleep 86400
        fi
      '
    networks:
      - finanzhub_net
```

### Volume-Backup (Konfig + Logs)

Portainer → **Volumes** → Volume auswählen → **Browse** → manuell herunterladen.

Oder per CLI:

```bash
docker run --rm \
  -v finanzhub_config:/source:ro \
  -v $(pwd):/backup \
  alpine tar czf /backup/finanzhub-config.tar.gz -C /source .
```

---

## Monitoring

### Health-Status in Portainer

**Stacks** → `finanzhub` zeigt:

- **Status**: 🟢 healthy / 🟡 starting / 🔴 unhealthy
- **Image-Tag**: Welche Version läuft
- **Created**: Wann zuletzt deployt
- **Uptime**

### Container-Stats

**Containers** → `finanzhub` → **Stats**: Live-CPU, RAM, Netzwerk, Disk-IO.

### Logs ansehen

**Containers** → `finanzhub` → **Logs**:

- Live-Tail mit "Follow logs"
- Zeitraum eingrenzen
- Such-Filter (`grep`-ähnlich)
- Logs exportieren als `.txt` oder `.json`

### Health-Check-Alerts

Portainer CE hat **kein** eingebautes Alerting. Alternativen:

- **Uptime Kuma** (lokal, Open-Source): Health-Endpunkt pollen
- **Grafana + Prometheus** (Phase 14)
- **Portainer Webhooks** → externer Service

---

## Troubleshooting

### Container startet nicht

| Symptom                          | Ursache                              | Lösung                                   |
| -------------------------------- | ------------------------------------ | ---------------------------------------- |
| Status: `exited (1)`             | `DB_PASSWORD` fehlt                  | Env-Variable setzen, neu deployen        |
| Status: `unhealthy`              | Postgres nicht bereit                | 30 s warten, restart                     |
| Logs: `permission denied`        | Volume-Mount falsch                  | `chown 1000:1000 ./config ./output`      |
| Logs: `port already in use`      | Anderer Container auf Port 5432      | Postgres-`ports:`-Block entfernen        |

### Migration schlägt fehl

```bash
# In Container-Console
finanzhub init --force
```

### Daten zurücksetzen

> **ACHTUNG: löscht ALLE Daten!**

1. **Stacks** → `finanzhub` → **Stop the stack**
2. **Volumes** → `finanzhub_postgres_data` → **Remove**
3. **Stacks** → `finanzhub` → **Deploy the stack**

### Image-Update erzwungen

**Stacks** → `finanzhub` → **Editor** → **Pull and redeploy**.

Falls Probleme: Stack löschen, neu aus Git deployen.

### Container-Logs sind riesig

Logging-Limits sind bereits gesetzt (`max-size: 10m`, `max-file: 3`). Falls trotzdem voll:

**Volumes** → `finanzhub_logs` → manuell leeren.

---

## Migration von docker-compose zu Portainer

Falls du bereits einen lokalen `docker compose`-Stack laufen hast:

```bash
# 1. Backup erstellen
docker exec finanzhub_db pg_dump -U finanzhub finanzhub > backup.sql

# 2. In Portainer deployen (siehe oben)

# 3. Daten importieren
#    In Portainer: postgres-Container → Console
psql -U finanzhub -d finanzhub < /path/to/backup.sql
```

---

## Sicherheits-Hinweise

- [ ] Portainer-Zugriff: nur per HTTPS + Reverse-Proxy
- [ ] `DB_PASSWORD` ≥ 32 Zeichen (z. B. `openssl rand -hex 16`)
- [ ] SMTP-App-Passwörter, niemals Hauptpasswörter
- [ ] Volume-Backups verschlüsselt ablegen (LUKS / GPG)
- [ ] Auto-Update nur wenn Git-Tag gepinnt ist
- [ ] Postgres-Port 5432 NICHT nach außen exposen
- [ ] Container laufen als unprivilegierter User (bereits im Dockerfile gesetzt)

---

**Weiterführend:**

- [Portainer Dokumentation](https://docs.portainer.io/)
- [INTEGRATION.md](INTEGRATION.md) — Banken, SMTP, Datenbank im Detail
- [USAGE.md](USAGE.md) — Tägliche Nutzung
- [README](../README.md) — Übersicht
