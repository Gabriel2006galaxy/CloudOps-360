#!/bin/bash
# ==============================================================================
# Lab 1 only: MySQL-compatible database (MariaDB 10.5) on the EC2 instance itself.
# Lab 2 replaces this with Amazon RDS for MySQL; the application code is unchanged.
#
#   sudo bash infrastructure/aws/lab1_mariadb_on_ec2.sh
#
# Generates a random password for the 'cloudops_user' account, writes the
# DATABASE_URL into /etc/cloudops360/cloudops360.env, then runs migrations.
# The database listens on 127.0.0.1 only.
# ==============================================================================
set -euo pipefail
ENV_FILE=/etc/cloudops360/cloudops360.env
[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "Run ec2_bootstrap.sh first." >&2; exit 1; }

dnf install -y mariadb105-server >/dev/null
# Bind to localhost only - never expose the database port
cat > /etc/my.cnf.d/cloudops360.cnf <<'CNF'
[mysqld]
bind-address=127.0.0.1
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci
CNF
systemctl enable --now mariadb

if grep -q '^DATABASE_URL=' "$ENV_FILE"; then
    echo "[lab1] DATABASE_URL already set in $ENV_FILE - leaving it unchanged."
else
    PASS=$(python3.11 -c "import secrets,string; a=string.ascii_letters+string.digits; print(''.join(secrets.choice(a) for _ in range(28)))")
    mysql -u root <<SQL
CREATE DATABASE IF NOT EXISTS cloudops360 CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'cloudops_user'@'localhost' IDENTIFIED BY '$PASS';
CREATE USER IF NOT EXISTS 'cloudops_user'@'127.0.0.1' IDENTIFIED BY '$PASS';
GRANT ALL PRIVILEGES ON cloudops360.* TO 'cloudops_user'@'localhost', 'cloudops_user'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
    echo "DATABASE_URL=mysql+pymysql://cloudops_user:$PASS@127.0.0.1:3306/cloudops360?charset=utf8mb4" >> "$ENV_FILE"
    echo "[lab1] Database and user created; DATABASE_URL written to $ENV_FILE (mode 0640)."
fi

cd /opt/cloudops360
sudo -u cloudops bash -c "set -a; . $ENV_FILE; set +a; .venv/bin/flask db upgrade && .venv/bin/flask seed-reference-data"
systemctl enable cloudops360
systemctl restart cloudops360
echo "[lab1] Create the first administrator:"
echo "  cd /opt/cloudops360 && sudo -u cloudops bash -c 'set -a; . $ENV_FILE; set +a; .venv/bin/flask create-admin'"
