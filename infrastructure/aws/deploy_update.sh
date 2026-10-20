#!/bin/bash
# ==============================================================================
# Deploy a new version on an EC2 instance that was set up with ec2_bootstrap.sh.
#   sudo bash /opt/cloudops360/infrastructure/aws/deploy_update.sh [branch]
# Pulls code, installs dependencies, applies migrations (safe to run on every
# instance; Alembic skips applied revisions) and restarts Gunicorn.
# ==============================================================================
set -euo pipefail
BRANCH="${1:-main}"
APP_DIR=/opt/cloudops360
ENV_FILE=/etc/cloudops360/cloudops360.env
[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
sudo -u cloudops git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH"
sudo -u cloudops git -C "$APP_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
chown -R cloudops:cloudops "$APP_DIR"
sudo -u cloudops "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
(cd "$APP_DIR" && sudo -u cloudops bash -c "set -a; . $ENV_FILE; set +a; .venv/bin/flask db upgrade")
install -m 0644 "$APP_DIR/infrastructure/aws/cloudops360.service" /etc/systemd/system/cloudops360.service
systemctl daemon-reload
systemctl restart cloudops360
sleep 2
curl -fsS http://127.0.0.1:8000/health && echo
echo "[deploy] $(sudo -u cloudops git -C "$APP_DIR" log -1 --oneline) is live."
