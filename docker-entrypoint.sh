#!/bin/sh
set -e

# =============================================================================
# FinanzHub Docker-Entrypoint
# Läuft als root, initialisiert Config-Verzeichnis, wechselt zu reporter
# =============================================================================

CONFIG_DIR="${CONFIG_DIR:-/app/config}"
EXAMPLE_DIR="/app/config.example"
OUTPUT_DIR="${OUTPUT_DIR:-/app/output}"

# Config-Verzeichnis: falls leer, aus Beispielen kopieren
if [ -d "$EXAMPLE_DIR" ]; then
    for f in "$EXAMPLE_DIR"/*.yaml "$EXAMPLE_DIR"/*.yml; do
        [ -f "$f" ] || continue
        filename=$(basename "$f")
        dest="$CONFIG_DIR/$filename"
        if [ ! -f "$dest" ]; then
            cp "$f" "$dest"
            echo "  Config kopiert: $filename"
        fi
    done
fi

# Output-Verzeichnis erstellen (falls nicht vorhanden)
mkdir -p "$OUTPUT_DIR"
mkdir -p "$CONFIG_DIR"

# Berechtigungen fixen: alles dem reporter-User geben
chown -R reporter:reporter "$CONFIG_DIR" "$OUTPUT_DIR" 2>/dev/null || true

# args an den eigentlichen Befehl (CMD)
exec gosu reporter python -m app.main "$@"
