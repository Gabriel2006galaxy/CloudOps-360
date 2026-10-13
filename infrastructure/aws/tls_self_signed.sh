#!/bin/bash
# ==============================================================================
# Lab 3 (no domain name): create a self-signed TLS certificate for Nginx.
#   sudo bash infrastructure/aws/tls_self_signed.sh [hostname-or-public-ip]
# Browsers will warn because no public CA signed it; traffic is still encrypted.
# With a real domain, prefer Let's Encrypt:  sudo dnf install -y certbot python3-certbot-nginx
#                                             sudo certbot --nginx -d your.domain
# ==============================================================================
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
TOKEN=$(curl -s -X PUT http://169.254.169.254/latest/api/token -H "X-aws-ec2-metadata-token-ttl-seconds: 60" || true)
DEFAULT_HOST=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-hostname || hostname -f)
HOST="${1:-$DEFAULT_HOST}"
DIR=/etc/pki/cloudops360
install -d -m 0750 "$DIR"
openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
    -keyout "$DIR/cloudops360.key" -out "$DIR/cloudops360.crt" \
    -subj "/CN=$HOST" -addext "subjectAltName=DNS:$HOST"
chmod 0600 "$DIR/cloudops360.key"
echo "[tls] Certificate for $HOST written to $DIR"
openssl x509 -in "$DIR/cloudops360.crt" -noout -subject -enddate
echo "[tls] Next: sudo cp /opt/cloudops360/infrastructure/aws/nginx_https.conf /etc/nginx/conf.d/cloudops360.conf"
echo "      sudo nginx -t && sudo systemctl reload nginx"
echo "      set SESSION_COOKIE_SECURE=true in /etc/cloudops360/cloudops360.env; sudo systemctl restart cloudops360"
