# FinanzHub — Dokumentation

Willkommen in der FinanzHub-Dokumentation. Diese ist in **vier Dokumente** gegliedert, die sich an unterschiedliche Zielgruppen richten:

| Dokument                                    | Zielgruppe           | Inhalt                                              |
| ------------------------------------------- | -------------------- | --------------------------------------------------- |
| [README.md](../README.md)                   | Alle                 | Übersicht, Schnellstart, Inbetrieb­nahme, Nutzung   |
| **[DEVELOPMENT.md](DEVELOPMENT.md)**        | Entwickler           | Architektur, Module, Erweiterung, Tests, Style      |
| **[INTEGRATION.md](INTEGRATION.md)**        | Administrator/DevOps| Banken, SMTP, Datenbank, Scheduler, Sicherheit     |
| **[USAGE.md](USAGE.md)**                    | Endbenutzer          | CLI-Referenz, Workflows, Rezepte, Fehlerbehebung    |
| **[PORTAINER.md](PORTAINER.md)**            | Portainer-Admins     | Deployment via Portainer, Backups, Updates          |

---

## Schnellzugriff nach Rolle

### „Ich will FinanzHub nur nutzen"

→ Lesen Sie das [README](../README.md) (Abschnitte 2 + 4) und die [USAGE.md](USAGE.md).

### „Ich will FinanzHub installieren und betreiben"

→ Lesen Sie das [README](../README.md#3-inbetriebnahmeanleitung) (Abschnitt 3) und die [INTEGRATION.md](INTEGRATION.md).

### „Ich will FinanzHub erweitern oder debuggen"

→ Lesen Sie die [DEVELOPMENT.md](DEVELOPMENT.md) und die [INTEGRATION.md](INTEGRATION.md).

### „Ich will einen Bank-Adapter anschließen"

→ Siehe [INTEGRATION.md §2](INTEGRATION.md#2-bank-integrationen) und [DEVELOPMENT.md §5.1](DEVELOPMENT.md#51-neuen-bank-adapter-hinzufügen).

### „Ich will meine Immobilien-Equity tracken"

→ [USAGE.md §4-6](USAGE.md#4-tägliche-workflows) und [INTEGRATION.md §2](INTEGRATION.md#2-bank-integrationen).

---

## Lese­reihenfolge (empfohlen)

1. **README** → 1 (Überblick), 2 (Schnellstart)
2. **README** → 3 (Inbetriebnahmeanleitung)
3. **USAGE** → 1-3 (Konzepte, Walkthrough, CLI)
4. **USAGE** → 4-7 (Workflows nach Zeitraum)
5. **INTEGRATION** → 2-5 (Bank, Mail, DB)
6. **DEVELOPMENT** → 1-4 (Architektur)
7. (Optional) **DEVELOPMENT** → 5-7 (Erweitern, Tests, Style)

---

## Dokumentations-Konventionen

- **Code-Blöcke** sind ausführbar (mit `bash` für Shell, `python` für Python)
- **Kommandos** beginnen mit `$ ` (ausführbar) oder `#` (Kommentar)
- **Pfade** sind relativ zum Projekt-Root, sofern nicht anders angegeben
- **Beispiele** basieren auf der mitgelieferten `config.example/`-Konfiguration
- **WARNUNG**, **WICHTIG** und **HINWEIS** markieren besondere Aufmerksamkeit

---

## Mitwirken

Verbesserungsvorschläge für die Dokumentation:

1. Issue mit Label `docs` auf GitHub öffnen
2. PR gegen `develop` branch
3. Review durch Maintainer (max. 5 Werktage)

Style-Guide für Dokumentation siehe [DEVELOPMENT.md §7](DEVELOPMENT.md#7-style-guide).
