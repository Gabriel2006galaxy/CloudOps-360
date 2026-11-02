#!/bin/bash
# ==============================================================================
# CloudOps 360 - show what is stored in Amazon RDS and on Amazon EFS (read-only).
#
#   sudo bash /opt/cloudops360/infrastructure/aws/show_database.sh
#
# Uses the application's own connection: the database credentials come from
# AWS Secrets Manager through the EC2 IAM role and the connection uses TLS.
# Changes nothing. Never prints a password (password hashes are cut short).
# ==============================================================================
set -uo pipefail
APP_DIR=/opt/cloudops360
ENV_FILE=/etc/cloudops360/cloudops360.env

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
set -a; . "$ENV_FILE"; set +a

if ! sudo -u cloudops bash -c "cd $APP_DIR; set -a; . $ENV_FILE; set +a; .venv/bin/python - 2>/dev/null" <<'PY'
from app import create_app
from app.extensions import db

app = create_app('production')
with app.app_context():
    run = lambda sql: db.session.execute(db.text(sql)).fetchall()
    url = db.engine.url
    ssl = run("SHOW SESSION STATUS LIKE 'Ssl_version'")
    print('\n== AMAZON RDS DATABASE ==')
    print('  Endpoint    :', url.host)
    print('  Engine      : MySQL', run('SELECT VERSION()')[0][0])
    print('  Credentials :', app.config.get('DB_CREDENTIALS_SOURCE'))
    print('  Connection  :', ('encrypted with ' + ssl[0][1]) if ssl and ssl[0][1] else 'NOT encrypted')
    print('\nTABLES (rows in each):')
    for (t,) in run('SHOW TABLES'):
        print('  %-24s %s' % (t, run('SELECT COUNT(*) FROM `%s`' % t)[0][0]))
    print('\nUSERS (passwords are stored only as scrypt hashes):')
    for r in run('SELECT username, role, LEFT(password_hash, 30) FROM users ORDER BY id'):
        print('  %-12s %-11s %s...' % tuple(r))
    print('\nTICKETS:')
    for r in run('SELECT reference_id, status, priority, LEFT(title, 45) FROM tickets ORDER BY id'):
        print('  %s  %-11s %-8s %s' % tuple(r))
    print('\nATTACHMENTS (details here in RDS, the file itself on EFS):')
    rows = run('SELECT original_filename, storage_path, file_size, LEFT(checksum_sha256, 16) FROM attachments ORDER BY id')
    for r in rows:
        print('  %s -> %s (%s bytes, sha256 %s...)' % tuple(r))
    if not rows:
        print('  (none yet - upload a file on a ticket first)')
    print('\nLAST 5 AUDIT LOG ENTRIES (UTC):')
    for r in run('SELECT created_at, action, LEFT(details, 60) FROM audit_logs ORDER BY id DESC LIMIT 5'):
        print('  %s  %-26s %s' % tuple(r))
PY
then
    echo "[show] Could not read the database. Check: sudo journalctl -u cloudops360 -n 30"
    exit 1
fi

echo
echo "== AMAZON EFS FILES (${UPLOAD_FOLDER:-not configured}) =="
findmnt -no SOURCE,FSTYPE "${EFS_MOUNT_POINT:-/mnt/efs}" 2>/dev/null | sed 's/^/  Mounted from: /'
if [ -d "${UPLOAD_FOLDER:-}" ]; then
    FILES=$(find "$UPLOAD_FOLDER" -type f ! -name '.health-*' -printf '  %TY-%Tm-%Td %TH:%TM  %8s bytes  %P\n' | sort)
    if [ -n "$FILES" ]; then echo "$FILES"; else echo "  (no files yet)"; fi
else
    echo "  Upload folder not found."
fi
