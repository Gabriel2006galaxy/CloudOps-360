#!/bin/bash
# ==============================================================================
# CloudOps 360 - collect evidence that the AWS deployment is configured as claimed.
#   sudo bash /opt/cloudops360/infrastructure/aws/verify_deployment.sh | tee verify-$(hostname).txt
#
# Read-only: it changes nothing. Each line is PASS / FAIL / INFO. Attach the
# output to your lab report. Checks that need account-level describe permissions
# (RDS/EFS encryption-at-rest, public accessibility) are printed as AWS CLI
# commands to run from CloudShell with your own admin credentials.
# ==============================================================================
set -uo pipefail
APP_DIR=/opt/cloudops360
ENV_FILE=/etc/cloudops360/cloudops360.env
pass() { echo "PASS  $*"; }
fail() { echo "FAIL  $*"; }
info() { echo "INFO  $*"; }

echo "== CloudOps 360 deployment verification on $(hostname) at $(date -u +%FT%TZ) =="
set -a; [ -r "$ENV_FILE" ] && . "$ENV_FILE"; set +a

# --- Services ---
systemctl is-active --quiet cloudops360 && pass "cloudops360 service active" || fail "cloudops360 service not active"
systemctl is-active --quiet nginx && pass "nginx active" || fail "nginx not active"
HEALTH=$(curl -s http://127.0.0.1:8000/health)
echo "$HEALTH" | grep -q '"status": *"healthy"' && pass "health: $(echo "$HEALTH" | tr -d '\n ' )" || fail "health: $HEALTH"

# --- IAM: instance role, no static keys ---
TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60")
ROLE=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/)
[ -n "$ROLE" ] && pass "EC2 instance role attached: $ROLE" || fail "no IAM instance role attached"
if [ -n "${AWS_ACCESS_KEY_ID:-}" ] || ls /root/.aws/credentials /home/*/.aws/credentials "$APP_DIR/.aws/credentials" >/dev/null 2>&1; then
    fail "static AWS access keys found on this instance"
else
    pass "no static AWS access keys in environment or ~/.aws/credentials"
fi
if command -v aws >/dev/null; then
    info "caller identity: $(aws sts get-caller-identity --query Arn --output text 2>&1)"
fi
grep -Rqs "AKIA[0-9A-Z]\{16\}" "$APP_DIR" --include='*.py' --include='*.env' --include='*.cfg' \
    && fail "AWS access key pattern found in application files" || pass "no AWS access key pattern in application files"

# --- Secrets Manager ---
if [ -n "${DB_SECRET_NAME:-}" ]; then
    grep -q '^DATABASE_URL=' "$ENV_FILE" && fail "DATABASE_URL still present although DB_SECRET_NAME is set" \
        || pass "DB credentials not in env file (DB_SECRET_NAME=$DB_SECRET_NAME)"
    command -v aws >/dev/null && aws secretsmanager describe-secret --secret-id "$DB_SECRET_NAME" \
        --query '{Name:Name,KmsKeyId:KmsKeyId,LastAccessed:LastAccessedDate}' --output text 2>&1 | sed 's/^/INFO  secret metadata: /'
else
    info "DB_SECRET_NAME not set - database credentials come from DATABASE_URL in $ENV_FILE (Lab 1/2 fallback)"
fi
[ -n "${APP_SECRET_NAME:-}" ] && pass "SECRET_KEY loaded from Secrets Manager ($APP_SECRET_NAME)" || info "SECRET_KEY comes from $ENV_FILE"
PERM=$(stat -c '%a %U:%G' "$ENV_FILE" 2>/dev/null)
[ "$PERM" = "640 root:cloudops" ] && pass "env file permissions $PERM" || fail "env file permissions are '$PERM' (expected 640 root:cloudops)"

# --- Database: engine, private address, TLS ---
cd "$APP_DIR" && sudo -u cloudops --preserve-env .venv/bin/python - <<'PY'
import ipaddress, socket
from app import create_app
from app.extensions import db
app = create_app('production')
with app.app_context():
    url = db.engine.url
    print(f"INFO  database engine: {url.get_backend_name()} host={url.host}")
    version = db.session.execute(db.text('SELECT VERSION()')).scalar()
    print(f"INFO  server version: {version}")
    if url.host:
        addr = socket.gethostbyname(url.host)
        private = ipaddress.ip_address(addr).is_private
        print(("PASS" if private else "FAIL") + f"  database resolves to {'private' if private else 'PUBLIC'} address {addr}")
    row = db.session.execute(db.text("SHOW SESSION STATUS LIKE 'Ssl_version'")).fetchone()
    cipher = db.session.execute(db.text("SHOW SESSION STATUS LIKE 'Ssl_cipher'")).fetchone()
    if row and row[1]:
        print(f"PASS  database connection encrypted: {row[1]} {cipher[1] if cipher else ''}")
    else:
        print("FAIL  database connection is NOT using TLS (set DB_SSL_CA)")
    counts = {t: db.session.execute(db.text(f'SELECT COUNT(*) FROM {t}')).scalar()
              for t in ('users', 'tickets', 'attachments', 'audit_logs')}
    print(f"INFO  row counts: {counts}")
PY

# --- Storage / EFS ---
if [ "${STORAGE_BACKEND:-local}" = "efs" ]; then
    mountpoint -q "${EFS_MOUNT_POINT:-/mnt/efs}" && pass "EFS mounted at ${EFS_MOUNT_POINT:-/mnt/efs}: $(findmnt -no SOURCE,FSTYPE,OPTIONS -T ${EFS_MOUNT_POINT:-/mnt/efs})" \
        || fail "EFS not mounted at ${EFS_MOUNT_POINT:-/mnt/efs}"
    pgrep -x stunnel >/dev/null || pgrep -f efs-proxy >/dev/null && pass "EFS TLS tunnel running (encryption in transit)" || fail "no EFS TLS tunnel process"
    grep -q " ${EFS_MOUNT_POINT:-/mnt/efs} efs .*tls" /etc/fstab && pass "fstab entry uses tls" || fail "fstab entry missing or without tls"
else
    info "STORAGE_BACKEND=${STORAGE_BACKEND:-local} (local disk) - Lab 1 configuration"
fi
(cd "$APP_DIR" && sudo -u cloudops --preserve-env .venv/bin/flask storage-check | tail -2 | sed 's/^/INFO  /')

# --- HTTPS ---
if ss -ltn | grep -q ':443 '; then
    HDRS=$(curl -skI https://127.0.0.1/auth/login)
    echo "$HDRS" | grep -qi '^strict-transport-security' && pass "HTTPS serving with HSTS" || fail "HTTPS without HSTS header"
    PROTO=$(echo | openssl s_client -connect 127.0.0.1:443 2>/dev/null | grep -m1 -E 'Protocol|New,' )
    info "TLS handshake: $PROTO"
    curl -sI http://127.0.0.1/auth/login | grep -qi '^location: https' && pass "HTTP redirects to HTTPS" || fail "HTTP does not redirect to HTTPS"
    [ "${SESSION_COOKIE_SECURE:-false}" = "true" ] && pass "SESSION_COOKIE_SECURE=true" || fail "SESSION_COOKIE_SECURE is not true while HTTPS is enabled"
else
    info "no listener on :443 - HTTPS not enabled yet (Lab 3)"
fi
# Once HTTPS is on, plain HTTP only answers with a redirect, so check the HTTPS page
HDR_URL=http://127.0.0.1/auth/login
ss -ltn | grep -q ':443 ' && HDR_URL=https://127.0.0.1/auth/login
curl -skI "$HDR_URL" | grep -qi '^x-frame-options: deny' && pass "security headers present ($HDR_URL)" || fail "security headers missing ($HDR_URL)"

# --- Network exposure from this host's point of view ---
ss -ltn | awk 'NR>1 {print $4}' | grep -E ':(3306|2049|8000)$' | grep -v -E '^(127\.0\.0\.1|\[::1\]):' \
    && fail "database/NFS/Gunicorn port listening on a public interface" || pass "Gunicorn/DB/NFS ports bound to localhost only on this host"

echo
echo "== Run these from AWS CloudShell (account-level settings this instance cannot read) =="
cat <<'CMDS'
aws rds describe-db-instances --query 'DBInstances[].{id:DBInstanceIdentifier,encrypted:StorageEncrypted,public:PubliclyAccessible,sg:VpcSecurityGroups[].VpcSecurityGroupId}' --output table
aws efs describe-file-systems --query 'FileSystems[].{id:FileSystemId,encrypted:Encrypted,name:Name}' --output table
aws efs describe-mount-targets --file-system-id <fs-id> --query 'MountTargets[].{subnet:SubnetId,ip:IpAddress}' --output table
aws ec2 describe-security-groups --group-ids <web-sg> <db-sg> <efs-sg> --query 'SecurityGroups[].{name:GroupName,in:IpPermissions}' --output json
CMDS
