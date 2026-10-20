#!/bin/bash
# ==============================================================================
# CloudOps 360 - one-shot demo setup for a fresh EC2 instance (AWS Academy Sandbox)
#
# Paste these 2 lines into EC2 "Launch instance" -> Advanced details -> User data:
#
#   #!/bin/bash
#   curl -fsSL https://raw.githubusercontent.com/Gabriel2006galaxy/CloudOps-360/main/infrastructure/aws/user_data_demo.sh | bash
#
# The instance then sets itself up (about 10 minutes) with the LATEST code from
# GitHub: Python, Nginx, Gunicorn, MariaDB, the database schema, the demo accounts
# and sample tickets, and the one-click demo login buttons.
#
# DEMO ONLY: it loads demo accounts with publicly known passwords. Use it on a
# short-lived lab instance, never on a site that stays online.
# Progress log on the server:  sudo tail -f /var/log/cloudops360-setup.log
# ==============================================================================
set -euo pipefail
exec > >(tee -a /var/log/cloudops360-setup.log) 2>&1
echo "[demo-setup] started $(date -u +%FT%TZ)"

REPO=https://github.com/Gabriel2006galaxy/CloudOps-360.git
SRC=/tmp/cloudops360
ENV_FILE=/etc/cloudops360/cloudops360.env

# 1 GB swap so package installs fit in a t3.micro's 1 GB of memory
if ! swapon --show | grep -q /swapfile; then
    [ -f /swapfile ] || dd if=/dev/zero of=/swapfile bs=1M count=1024
    chmod 600 /swapfile
    mkswap /swapfile >/dev/null
    swapon /swapfile
fi

dnf install -y git >/dev/null
rm -rf "$SRC"
git clone --depth 1 "$REPO" "$SRC"

# Same two scripts as the manual Lab 1 steps
bash "$SRC/infrastructure/aws/ec2_bootstrap.sh" main
bash /opt/cloudops360/infrastructure/aws/lab1_mariadb_on_ec2.sh

# Demo accounts + sample tickets (production refuses seed-db, so run it once in development mode)
cd /opt/cloudops360
sudo -u cloudops bash -c "set -a; . $ENV_FILE; set +a; FLASK_ENV=development .venv/bin/flask seed-db"

# One-click demo login buttons on the sign-in page
grep -q '^SHOW_DEMO_ACCOUNTS=' "$ENV_FILE" || echo 'SHOW_DEMO_ACCOUNTS=true' >> "$ENV_FILE"
systemctl restart cloudops360

sleep 3
curl -fsS http://127.0.0.1/health && echo
echo "[demo-setup] FINISHED $(date -u +%FT%TZ) - open http://<public-ip>/"
