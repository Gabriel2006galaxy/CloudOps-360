#!/bin/bash
# ==============================================================================
# CloudOps 360 - put the DEMO data back to its starting state right before a
# presentation: ticket times are counted from now, so only the one sample ticket
# that is meant to be overdue shows as overdue.
#
#   sudo bash /opt/cloudops360/infrastructure/aws/reset_demo_data.sh
#
# Deletes ALL tickets, comments, attachments (also on EFS), notifications, audit
# entries and extra users, then loads the demo accounts and incidents again.
# Demo servers only - never run this on a server with real data.
# ==============================================================================
set -euo pipefail
APP_DIR=/opt/cloudops360
ENV_FILE=/etc/cloudops360/cloudops360.env

[ "$(id -u)" -eq 0 ] || { echo "[reset] Run with sudo."; exit 1; }
[ -f "$ENV_FILE" ] || { echo "[reset] $ENV_FILE not found."; exit 1; }

cd "$APP_DIR"
# Development mode only for the demo data command; never fall back to SQLite if Secrets Manager fails
sudo -u cloudops bash -c "set -a; . $ENV_FILE; set +a; FLASK_ENV=development ALLOW_SQLITE_FALLBACK=false .venv/bin/flask reset-demo --yes" \
    | { grep -v 'Pass123' || true; }

HEALTH=$(curl -s http://127.0.0.1:8000/health || true)
echo "$HEALTH" | grep -q '"healthy"' && echo "[reset] Done. The site is healthy; sign in with the demo buttons." \
    || echo "[reset] WARNING: health check says: $HEALTH"
