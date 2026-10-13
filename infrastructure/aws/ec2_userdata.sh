#!/bin/bash
# ==============================================================================
# CloudOps 360: EC2 Automated User Data Deployment Script
# Target: Amazon Linux 2023 (or Amazon Linux 2)
# ==============================================================================

set -euo pipefail
exec > >(tee /var/log/user-data.log|logger -t user-data -s 2>/dev/console) 2>&1
echo "[CloudOps 360] Bootstrapping EC2 instance at $(date -u)..."

# 1. Update system packages
dnf update -y || yum update -y

# 2. Install Git, Python 3.12/3.11, Nginx, and Amazon EFS Utilities
dnf install -y git python3.11 python3.11-pip python3.11-devel nginx amazon-efs-utils || {
    yum install -y git python3 python3-pip python3-devel nginx amazon-efs-utils
}

# 3. Setup application directory
APP_DIR="/var/www/cloudops-360"
mkdir -p "$APP_DIR"
mkdir -p /var/log/cloudops360
chown -R ec2-user:ec2-user /var/www /var/log/cloudops360

# 4. Clone or pull repository
# Replace with user's repository URL
REPO_URL="https://github.com/Gabriel2006galaxy/CloudOps-360.git"
if [ ! -d "$APP_DIR/.git" ]; then
    echo "[CloudOps 360] Cloning application repository..."
    git clone "$REPO_URL" "$APP_DIR"
else
    echo "[CloudOps 360] Updating existing repository..."
    cd "$APP_DIR" && git pull
fi

cd "$APP_DIR"
chown -R ec2-user:ec2-user "$APP_DIR"

# 5. Create Python virtual environment and install dependencies
sudo -u ec2-user python3.11 -m venv "$APP_DIR/.venv" || sudo -u ec2-user python3 -m venv "$APP_DIR/.venv"
sudo -u ec2-user "$APP_DIR/.venv/bin/pip" install --upgrade pip
sudo -u ec2-user "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

# 6. Configure environment variables (.env) if not already present
if [ ! -f "$APP_DIR/.env" ]; then
    echo "[CloudOps 360] Generating initial .env configuration..."
    SECRET_KEY_GEN=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    cat <<EOF > "$APP_DIR/.env"
FLASK_APP=run.py
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=${SECRET_KEY_GEN}
# For local SQLite fallback in Lab 1:
# DATABASE_URL=sqlite:////var/www/cloudops-360/cloudops360.db
# For Amazon RDS in Lab 2:
# DATABASE_URL=mysql+pymysql://cloudops_user:YourDbPassword@your-rds-endpoint.rds.amazonaws.com:3306/cloudops360
UPLOAD_FOLDER=/mnt/efs/cloudops360-attachments
AWS_REGION=us-east-1
SESSION_COOKIE_SECURE=False
REMEMBER_COOKIE_SECURE=False
SESSION_COOKIE_HTTPONLY=True
SESSION_COOKIE_SAMESITE=Lax
PERMANENT_SESSION_LIFETIME_MINUTES=60
EOF
    chown ec2-user:ec2-user "$APP_DIR/.env"
    chmod 600 "$APP_DIR/.env"
fi

# 7. Setup systemd Gunicorn service
cp "$APP_DIR/infrastructure/aws/cloudops360.service" /etc/systemd/system/cloudops360.service
systemctl daemon-reload

# 8. Setup Nginx site configuration
cp "$APP_DIR/infrastructure/aws/nginx.conf" /etc/nginx/conf.d/cloudops360.conf
systemctl enable nginx
systemctl restart nginx

# 9. Apply database migrations and seed default reference data
sudo -u ec2-user "$APP_DIR/.venv/bin/flask" db upgrade || true
sudo -u ec2-user "$APP_DIR/.venv/bin/flask" seed-db --no-input || true

# 10. Start CloudOps 360 service
systemctl enable cloudops360
systemctl restart cloudops360

echo "[CloudOps 360] EC2 deployment bootstrap completed successfully at $(date -u)."
