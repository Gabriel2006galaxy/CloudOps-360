#!/bin/bash
# ==============================================================================
# CloudOps 360 - EC2 bootstrap (Amazon Linux 2023). Idempotent; safe to re-run.
#
#   sudo bash infrastructure/aws/ec2_bootstrap.sh [git-branch]
#
# Can also be pasted into EC2 "User data" (runs as root on first boot).
# Installs packages, creates the unprivileged 'cloudops' service user, deploys
# the code to /opt/cloudops360, installs the systemd unit and Nginx config and
# creates /etc/cloudops360/cloudops360.env. It does NOT create AWS resources,
# does NOT seed demo accounts and does NOT start the app until a database is
# configured in the env file.
# ==============================================================================
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/Gabriel2006galaxy/CloudOps-360.git}"
BRANCH="${1:-${BRANCH:-main}}"
APP_DIR=/opt/cloudops360
APP_USER=cloudops
ENV_DIR=/etc/cloudops360
ENV_FILE=$ENV_DIR/cloudops360.env

log() { echo "[bootstrap] $*"; }
[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }

log "Installing packages"
dnf install -y git python3.11 python3.11-pip nginx amazon-efs-utils mariadb105 >/dev/null

log "Creating service user '$APP_USER'"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$APP_DIR" --shell /sbin/nologin "$APP_USER"

log "Deploying code (branch $BRANCH) to $APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
    git clone --branch "$BRANCH" --depth 1 "$REPO_URL" "$APP_DIR"
else
    git -C "$APP_DIR" fetch --depth 1 origin "$BRANCH"
    git -C "$APP_DIR" checkout -B "$BRANCH" "origin/$BRANCH"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

log "Creating virtual environment"
sudo -u "$APP_USER" python3.11 -m venv "$APP_DIR/.venv"
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

log "Preparing environment file $ENV_FILE"
install -d -m 0750 -o root -g "$APP_USER" "$ENV_DIR"
if [ ! -f "$ENV_FILE" ]; then
    install -m 0640 -o root -g "$APP_USER" "$APP_DIR/infrastructure/aws/cloudops360.env.example" "$ENV_FILE"
    # A random key is generated here only as a starting point; Lab 3 moves it to Secrets Manager.
    KEY=$(python3.11 -c "import secrets; print(secrets.token_urlsafe(48))")
    sed -i "s|^SECRET_KEY=.*|SECRET_KEY=$KEY|" "$ENV_FILE"
    log "Created $ENV_FILE - edit it to configure the database (see docs/aws_deployment.md)."
fi

log "Local attachment directory (replaced by the EFS mount in Lab 2)"
install -d -m 0750 -o "$APP_USER" -g "$APP_USER" /var/lib/cloudops360/uploads

log "Installing systemd unit and Nginx config"
install -m 0644 "$APP_DIR/infrastructure/aws/cloudops360.service" /etc/systemd/system/cloudops360.service
if [ ! -f /etc/nginx/conf.d/cloudops360.conf ]; then
    install -m 0644 "$APP_DIR/infrastructure/aws/nginx.conf" /etc/nginx/conf.d/cloudops360.conf
fi
# Remove the default server block so ours is the default_server
sed -i 's/^\(\s*listen\s\+\(\[::\]:\)\?80\) default_server;/\1;/' /etc/nginx/nginx.conf || true
systemctl daemon-reload
nginx -t
systemctl enable --now nginx

if grep -Eq '^(DATABASE_URL|DB_SECRET_NAME)=.+' "$ENV_FILE"; then
    log "Database configured - running migrations and reference data"
    (cd "$APP_DIR" && sudo -u "$APP_USER" bash -c "set -a; . $ENV_FILE; set +a; FLASK_ENV=production .venv/bin/flask db upgrade && FLASK_ENV=production .venv/bin/flask seed-reference-data")
    systemctl enable cloudops360
    systemctl restart cloudops360
    log "Service started. Check: curl -s http://127.0.0.1/health"
else
    log "No database configured yet. Lab 1: sudo bash $APP_DIR/infrastructure/aws/lab1_mariadb_on_ec2.sh"
    log "Lab 2: set DATABASE_URL (or DB_SECRET_NAME) to Amazon RDS in $ENV_FILE, then re-run this script."
fi
log "Done."
