#!/bin/bash
# =============================================================================
# Synology: FinanzHub Volume-Besitzer fixen
# =============================================================================
# Fixt Berechtigungen für alle FinanzHub-Docker-Volumes.
# Postgres (alpine) läuft als UID 70, Reporter als UID 1000.
#
# Ausführung:
#   1. Per SSH auf der Synology einloggen
#   2. sudo bash synology-fix-ownership.sh
#   3. Anschließend Stack in Portainer neustarten
# =============================================================================

echo "=== FinanzHub Volume-Besitzer fixen ==="
echo ""

# --- Postgres (UID 70 = postgres in alpine) ---
echo "[1/4] Postgres-Daten (finanzhub_postgres_data)"
docker run --rm --user root \
  -v finanzhub_postgres_data:/data \
  alpine sh -c "chown -R 70:70 /data" 2>&1 && echo "  ✅ done" || echo "  ❌ fehlgeschlagen"

# --- FinanzHub Config (UID 1000 = reporter) ---
echo "[2/4] Config (finanzhub_config)"
docker run --rm --user root \
  -v finanzhub_config:/data \
  alpine sh -c "chown -R 1000:1000 /data" 2>&1 && echo "  ✅ done" || echo "  ❌ fehlgeschlagen"

# --- FinanzHub Output (UID 1000 = reporter) ---
echo "[3/4] Output (finanzhub_output)"
docker run --rm --user root \
  -v finanzhub_output:/data \
  alpine sh -c "chown -R 1000:1000 /data" 2>&1 && echo "  ✅ done" || echo "  ❌ fehlgeschlagen"

# --- FinanzHub Logs (UID 1000 = reporter) ---
echo "[4/4] Logs (finanzhub_logs)"
docker run --rm --user root \
  -v finanzhub_logs:/data \
  alpine sh -c "chown -R 1000:1000 /data" 2>&1 && echo "  ✅ done" || echo "  ❌ fehlgeschlagen"

echo ""
echo "=== Fertig! Jetzt Stack in Portainer neustarten ==="
