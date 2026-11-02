#!/bin/bash
# ==============================================================================
# CloudOps 360 - Docker containerization on the EC2 server.
#
#   sudo bash /opt/cloudops360/infrastructure/aws/docker_demo.sh        # install Docker, build, run, show
#   sudo bash /opt/cloudops360/infrastructure/aws/docker_demo.sh show   # only show image + container (for the demo)
#   sudo bash /opt/cloudops360/infrastructure/aws/docker_demo.sh stop   # remove the container
#
# Packages the code on this server into the cloudops360 Docker image and runs it
# as a container NEXT TO the live site (which keeps running under systemd on
# port 8000 behind Nginx). The container listens on 127.0.0.1:8080 and uses the
# same Amazon RDS database and Amazon EFS storage. Its credentials come from
# Secrets Manager through the instance's IAM role, exactly like the live site:
# no password or key is baked into the image (.dockerignore keeps .env out).
# ==============================================================================
set -euo pipefail
APP_DIR=/opt/cloudops360
ENV_FILE=/etc/cloudops360/cloudops360.env
IMAGE=cloudops360:latest
NAME=cloudops360-container
PORT=8080

log() { echo -e "\n[docker] $*"; }
die() { echo -e "\n[docker] ERROR: $*" >&2; exit 1; }
[ "$(id -u)" -eq 0 ] || die "Run with sudo."

show() {
    log "Image (the packaged application):"
    docker images cloudops360 --format 'table {{.Repository}}:{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}'
    log "Running container:"
    docker ps --filter "name=$NAME" --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}'
    log "The app inside the container answers (database + EFS check):"
    curl -s "http://127.0.0.1:$PORT/health" || echo "(not answering)"
    echo
    curl -s "http://127.0.0.1:$PORT/auth/login" | grep -o '<title>[^<]*</title>' || true
}

case "${1:-run}" in
    show) command -v docker >/dev/null || die "Docker is not installed yet: run this script without 'show' first."
          show; exit 0 ;;
    stop) docker rm -f "$NAME" >/dev/null 2>&1 || true
          log "Container removed. The live site is unchanged."; exit 0 ;;
    run)  ;;
    *)    die "usage: sudo bash $0 [run|show|stop]" ;;
esac

[ -f "$ENV_FILE" ] || die "$ENV_FILE not found - this server was not set up with the User data script."
set -a; . "$ENV_FILE"; set +a
EFS_DIR="${EFS_MOUNT_POINT:-/mnt/efs}"

log "1/5 Installing Docker (Amazon Linux 2023 package)"
command -v docker >/dev/null || dnf install -y -q docker
systemctl enable --now docker >/dev/null 2>&1
docker --version

log "2/5 Checking memory and disk (t3.micro has 1 GB of memory)"
if ! swapon --show | grep -q .; then
    [ -f /swapfile ] || { fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile >/dev/null; }
    swapon /swapfile && echo "   1 GB swap file switched on so the build cannot starve the live site"
fi
FREE_MB=$(df -m --output=avail / | tail -1 | tr -d ' ')
[ "$FREE_MB" -gt 1500 ] || die "Only ${FREE_MB} MB of disk left; the image needs about 1.5 GB."
echo "   disk free: ${FREE_MB} MB"

log "3/5 Building the image from $APP_DIR (first time: a few minutes)"
docker build -t "$IMAGE" "$APP_DIR"

log "4/5 Starting the container on 127.0.0.1:$PORT (same RDS + EFS, IAM role credentials)"
docker rm -f "$NAME" >/dev/null 2>&1 || true
# host network: the container reaches RDS, EFS and the instance metadata (IAM role) like the host does
docker run -d --name "$NAME" --restart unless-stopped \
    --network host --memory 400m \
    --env-file "$ENV_FILE" \
    -e FLASK_ENV=production -e PORT="$PORT" -e BIND_HOST=127.0.0.1 -e WORKERS=1 \
    -v /etc/pki/rds:/etc/pki/rds:ro \
    -v "$EFS_DIR:$EFS_DIR" \
    --user "$(id -u cloudops):$(id -g cloudops)" \
    "$IMAGE" >/dev/null

for attempt in $(seq 1 30); do
    curl -fs "http://127.0.0.1:$PORT/health" >/dev/null && break
    sleep 2
done
if ! curl -fs "http://127.0.0.1:$PORT/health" >/dev/null; then
    docker logs --tail 40 "$NAME" || true
    die "The container did not become healthy (log above). The live site is not affected."
fi

log "5/5 Done"
show
cat <<DONE

==============================================================================
 CloudOps 360 now also runs as a Docker container (next to the live site).
 For the demo:  sudo bash $APP_DIR/infrastructure/aws/docker_demo.sh show
 Container log: sudo docker logs --tail 20 $NAME
==============================================================================
DONE
