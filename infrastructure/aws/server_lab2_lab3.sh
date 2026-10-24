#!/bin/bash
# ==============================================================================
# CloudOps 360 - switch a running Lab 1 server to Lab 2 + Lab 3.
# Run on the EC2 instance (EC2 Instance Connect) AFTER cloudshell_lab2_lab3.sh,
# using the exact command that script prints at the end:
#
#   curl -fsSL https://raw.githubusercontent.com/Gabriel2006galaxy/CloudOps-360/main/infrastructure/aws/server_lab2_lab3.sh -o /tmp/labs.sh && sudo bash /tmp/labs.sh <efs-id>
#
#   Lab 2  database -> Amazon RDS for MySQL (verified TLS, least-privilege user),
#          attachments -> Amazon EFS (TLS mount with the instance role)
#   Lab 3  credentials and session key from AWS Secrets Manager via the IAM role
#          (no passwords or keys left in the env file), HTTPS with HTTP -> HTTPS redirect
# Asks once for the RDS master password (shown by the CloudShell script). Safe to re-run.
# ==============================================================================
set -euo pipefail
shopt -s inherit_errexit   # errors inside $(...) stop the script too
FS_ID="${1:?usage: sudo bash $0 <efs-file-system-id>  (copy the full command printed by the CloudShell script)}"
APP_DIR=/opt/cloudops360
ENV_FILE=/etc/cloudops360/cloudops360.env
CA=/etc/pki/rds/global-bundle.pem
DB_SECRET=cloudops360/prod/db
APP_SECRET=cloudops360/prod/app

log() { echo -e "\n[labs] $*"; }
die() { echo -e "\n[labs] ERROR: $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "Run with sudo."
[ -f "$ENV_FILE" ] || die "$ENV_FILE not found - this server was not set up with the User data script."

TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 600")
md() { curl -s -H "X-aws-ec2-metadata-token: $TOKEN" "http://169.254.169.254/latest/meta-data/$1"; }
REGION=$(md placement/region)
PUBLIC_IP=$(md public-ipv4)
ROLE=$(md iam/security-credentials/)
[ -n "$ROLE" ] || die "No IAM role on this instance yet. Wait 1 minute after the CloudShell step, then run this again."
log "Region $REGION, IAM role '$ROLE' (temporary credentials, no access keys)"

log "1/7 Updating the application code"
bash "$APP_DIR/infrastructure/aws/deploy_update.sh" main

log "2/7 Reading the database settings from Secrets Manager ($DB_SECRET)"
SECRET_JSON=""
for attempt in 1 2 3 4 5 6; do
    SECRET_JSON=$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$DB_SECRET" \
        --query SecretString --output text 2>/dev/null) && break
    sleep 10
done
[ -n "$SECRET_JSON" ] || die "Cannot read $DB_SECRET. Did the CloudShell script finish without errors?"
field() { echo "$SECRET_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }
DB_HOST=$(field host)
DB_USER=$(field username)
APP_PW=$(field password)
echo "   RDS endpoint: $DB_HOST (user $DB_USER)"

log "3/7 Downloading the Amazon RDS certificate bundle (to verify the database's TLS certificate)"
install -d -m 0755 /etc/pki/rds
curl -fsSo "$CA" https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem
chmod 0644 "$CA"

log "4/7 Creating the least-privilege application user on RDS"
echo "   Paste the RDS master password printed by CloudShell (right-click -> Paste; nothing is shown) and press Enter:"
read -rs MASTER_PW </dev/tty
echo
MASTER_PW="$MASTER_PW" APP_PW="$APP_PW" DB_HOST="$DB_HOST" DB_USER="$DB_USER" CA="$CA" \
"$APP_DIR/.venv/bin/python" - <<'PY'
import os
import sys

import pymysql

try:
    conn = pymysql.connect(host=os.environ['DB_HOST'], user='admin', password=os.environ['MASTER_PW'],
                           ssl={'ca': os.environ['CA']}, autocommit=True, connect_timeout=15)
except pymysql.err.OperationalError as exc:
    sys.exit(f"   Could not log in to RDS as admin ({exc.args[0]}). Check the master password and run the script again.")
user, password = os.environ['DB_USER'], os.environ['APP_PW']
with conn.cursor() as cur:
    cur.execute("CREATE DATABASE IF NOT EXISTS cloudops360 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    # REQUIRE SSL: the server refuses unencrypted connections for this account
    cur.execute(f"CREATE USER IF NOT EXISTS '{user}'@'%%' IDENTIFIED BY %s REQUIRE SSL", (password,))
    cur.execute(f"ALTER USER '{user}'@'%%' IDENTIFIED BY %s REQUIRE SSL", (password,))
    # Only what the app and its migrations need, only on its own database
    cur.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, DROP, INDEX, ALTER, REFERENCES "
                f"ON cloudops360.* TO '{user}'@'%'")
    cur.execute(f"SHOW GRANTS FOR '{user}'@'%'")
    for (grant,) in cur.fetchall():
        print('   ', grant)
conn.close()
PY
unset MASTER_PW

log "5/7 Moving settings to Secrets Manager and Amazon EFS (backup of the old env file: /root/cloudops360.env.lab1.bak)"
[ -f /root/cloudops360.env.lab1.bak ] || install -m 0600 "$ENV_FILE" /root/cloudops360.env.lab1.bak
set_env() {
    if grep -q "^$1=" "$ENV_FILE"; then sed -i "s|^$1=.*|$1=$2|" "$ENV_FILE"; else echo "$1=$2" >> "$ENV_FILE"; fi
}
# No database password or session key stays on disk: both now come from Secrets Manager
sed -i '/^DATABASE_URL=/d; /^SECRET_KEY=/d' "$ENV_FILE"
set_env AWS_REGION "$REGION"
set_env DB_SECRET_NAME "$DB_SECRET"
set_env APP_SECRET_NAME "$APP_SECRET"
set_env DB_SSL_CA "$CA"
set_env STORAGE_BACKEND efs
set_env EFS_MOUNT_POINT /mnt/efs
set_env UPLOAD_FOLDER /mnt/efs/cloudops360-attachments
set_env SESSION_COOKIE_SECURE true
chown root:cloudops "$ENV_FILE"
chmod 0640 "$ENV_FILE"

log "6/7 Mounting Amazon EFS $FS_ID (TLS + IAM role)"
bash "$APP_DIR/infrastructure/aws/efs_mount_setup.sh" "$FS_ID"     | { grep -v '^\[efs\] Now set\|^  STORAGE_BACKEND\|^  EFS_MOUNT_POINT\|^  UPLOAD_FOLDER\|^then: sudo' || true; }

log "Creating the tables on RDS and loading the demo data"
cd "$APP_DIR"
sudo -u cloudops bash -c "set -a; . $ENV_FILE; set +a; FLASK_ENV=production .venv/bin/flask db upgrade"
# development mode only for the demo seed; never fall back to SQLite if Secrets Manager failed
sudo -u cloudops bash -c "set -a; . $ENV_FILE; set +a; FLASK_ENV=development ALLOW_SQLITE_FALLBACK=false .venv/bin/flask seed-db" \
    | { grep -v 'Pass123' || true; }

log "7/7 Enabling HTTPS (self-signed certificate for the lab; HTTP redirects to HTTPS)"
bash "$APP_DIR/infrastructure/aws/tls_self_signed.sh" | { grep -v '^\[tls\] Next\|^      ' || true; }
install -m 0644 "$APP_DIR/infrastructure/aws/nginx_https.conf" /etc/nginx/conf.d/cloudops360.conf
nginx -t
systemctl reload nginx

systemctl restart cloudops360
for attempt in $(seq 1 15); do
    curl -fs http://127.0.0.1:8000/health >/dev/null && break
    sleep 2
done
HEALTH=$(curl -s http://127.0.0.1:8000/health || true)
echo "   health: $HEALTH"
echo "$HEALTH" | grep -q '"healthy"' || die "The app is not healthy. See: sudo journalctl -u cloudops360 -n 50"

log "Stopping the Lab 1 MariaDB database (the app now uses RDS only)"
systemctl disable --now mariadb >/dev/null 2>&1 || true

log "Verification report (also saved to /root/cloudops360-verify.txt)"
bash "$APP_DIR/infrastructure/aws/verify_deployment.sh" | tee /root/cloudops360-verify.txt

cat <<DONE

==============================================================================
 Lab 2 + Lab 3 are live.
   Open:  https://$PUBLIC_IP
   The browser warns about the certificate because it is self-signed (lab
   demo): click Advanced -> Proceed. Use the IP address, not the long DNS name.
   Sign in with the same demo buttons as before.
==============================================================================
DONE
