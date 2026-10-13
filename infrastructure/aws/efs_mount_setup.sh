#!/bin/bash
# ==============================================================================
# CloudOps 360 - mount Amazon EFS for shared attachments (Lab 2 / Lab 3)
#
#   sudo bash infrastructure/aws/efs_mount_setup.sh <fs-id> [access-point-id]
#
# * Mounts with TLS (encryption in transit) via amazon-efs-utils. There is NO
#   unencrypted NFS fallback: if the TLS mount fails, the script stops.
# * Adds 'iam' when the instance role is used for EFS authorization (Lab 3, with
#   the file-system policy in efs_file_system_policy.json).
# * Persists the mount in /etc/fstab (_netdev) so it survives reboots.
# * Creates /mnt/efs/cloudops360-attachments owned by the 'cloudops' user, 0750.
# Run it on EVERY EC2 instance that serves the application.
# ==============================================================================
set -euo pipefail
FS_ID="${1:?usage: $0 <fs-id> [access-point-id]}"
AP_ID="${2:-}"
MOUNT_POINT=/mnt/efs
APP_DIR_ON_EFS=$MOUNT_POINT/cloudops360-attachments
USE_IAM="${USE_IAM:-yes}"

[ "$(id -u)" -eq 0 ] || { echo "Run as root (sudo)." >&2; exit 1; }
command -v mount.efs >/dev/null || dnf install -y amazon-efs-utils

OPTS="_netdev,tls"
[ "$USE_IAM" = "yes" ] && OPTS="$OPTS,iam"
[ -n "$AP_ID" ] && OPTS="$OPTS,accesspoint=$AP_ID"

mkdir -p "$MOUNT_POINT"
if ! mountpoint -q "$MOUNT_POINT"; then
    echo "[efs] Mounting $FS_ID at $MOUNT_POINT with options: $OPTS"
    mount -t efs -o "$OPTS" "$FS_ID":/ "$MOUNT_POINT"
fi

FSTAB_LINE="$FS_ID:/ $MOUNT_POINT efs $OPTS 0 0"
if ! grep -q "^$FS_ID:/ " /etc/fstab; then
    echo "$FSTAB_LINE" >> /etc/fstab
    echo "[efs] Added to /etc/fstab: $FSTAB_LINE"
fi

install -d -m 0750 -o cloudops -g cloudops "$APP_DIR_ON_EFS"

echo "[efs] Verification:"
mountpoint "$MOUNT_POINT"
findmnt -T "$MOUNT_POINT" -o TARGET,SOURCE,FSTYPE,OPTIONS
# efs-utils tunnels TLS through stunnel on localhost; its presence proves encryption in transit
{ pgrep -a stunnel || pgrep -af efs-proxy; } >/dev/null && echo "[efs] TLS tunnel (stunnel) is running: encryption in transit active" \
    || echo "[efs] WARNING: no stunnel process found - TLS may not be active"
sudo -u cloudops bash -c "echo efs-write-test > $APP_DIR_ON_EFS/.write-test && rm $APP_DIR_ON_EFS/.write-test" \
    && echo "[efs] cloudops user can write to $APP_DIR_ON_EFS"

echo "[efs] Now set in /etc/cloudops360/cloudops360.env:"
echo "  STORAGE_BACKEND=efs"
echo "  EFS_MOUNT_POINT=$MOUNT_POINT"
echo "  UPLOAD_FOLDER=$APP_DIR_ON_EFS"
echo "then: sudo systemctl restart cloudops360"
