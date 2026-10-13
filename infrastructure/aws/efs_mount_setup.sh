#!/bin/bash
# ==============================================================================
# CloudOps 360: Amazon EFS Mount & Configuration Script
# Used in Lab 2 & Lab 3 to mount shared attachment filesystem on EC2
# ==============================================================================

set -euo pipefail

# Check argument
if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <EFS_FILESYSTEM_ID> [AWS_REGION]"
    echo "Example: $0 fs-0123456789abcdef0 us-east-1"
    exit 1
fi

EFS_ID="$1"
AWS_REGION="${2:-us-east-1}"
MOUNT_POINT="/mnt/efs/cloudops360-attachments"

echo "[EFS Setup] Initializing Amazon EFS mount for: $EFS_ID in region: $AWS_REGION..."

# 1. Install amazon-efs-utils if not installed
if ! command -v mount.efs &> /dev/null; then
    echo "[EFS Setup] Installing amazon-efs-utils..."
    if command -v dnf &> /dev/null; then
        dnf install -y amazon-efs-utils
    elif command -v yum &> /dev/null; then
        yum install -y amazon-efs-utils
    elif command -v apt-get &> /dev/null; then
        apt-get update && apt-get install -y nfs-common binutils
        git clone https://github.com/aws/efs-utils /tmp/efs-utils
        cd /tmp/efs-utils && ./build-deb.sh && apt-get install -y ./build/amazon-efs-utils*deb
        rm -rf /tmp/efs-utils
    fi
fi

# 2. Create local mount directory
mkdir -p "$MOUNT_POINT"

# 3. Mount EFS with TLS encryption in transit and IAM authentication
echo "[EFS Setup] Mounting $EFS_ID to $MOUNT_POINT with TLS encryption..."
mount -t efs -o tls,iam "$EFS_ID":/ "$MOUNT_POINT" || {
    echo "[EFS Setup] Falling back to standard DNS mount..."
    mount -t nfs4 -o nfsvers=4.1,rsize=1048576,wsize=1048576,hard,timeo=600,retrans=2,noresvport \
        "${EFS_ID}.efs.${AWS_REGION}.amazonaws.com:/" "$MOUNT_POINT"
}

# 4. Configure persistent mount in /etc/fstab
if ! grep -q "$EFS_ID" /etc/fstab; then
    echo "[EFS Setup] Adding mount to /etc/fstab for persistence across reboots..."
    echo "$EFS_ID:/ $MOUNT_POINT efs _netdev,tls,iam 0 0" >> /etc/fstab
fi

# 5. Set correct POSIX permissions for application user
echo "[EFS Setup] Setting ownership and permissions on $MOUNT_POINT..."
chown -R ec2-user:ec2-user "$MOUNT_POINT" || chown -R www-data:www-data "$MOUNT_POINT"
chmod 775 "$MOUNT_POINT"

# 6. Verify mount status
df -h "$MOUNT_POINT"
echo "[EFS Setup] EFS successfully mounted and verified at $MOUNT_POINT."
