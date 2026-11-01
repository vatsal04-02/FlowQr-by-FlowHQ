#!/usr/bin/env bash
# Logical PostgreSQL backup (compressed). Run from the repo root, e.g. nightly via cron:
#   0 2 * * * cd /opt/flowqr && ./deploy/backup.sh >> backups/backup.log 2>&1
set -euo pipefail
COMPOSE=${COMPOSE:-docker compose}   # e.g. COMPOSE="docker compose -p flowqr-staging --env-file .env.staging -f docker-compose.yml ..."
mkdir -p backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="backups/flowqr-${STAMP}.sql.gz"
$COMPOSE exec -T db pg_dump -U flowqr -d flowqr --no-owner | gzip -9 > "$FILE"
gzip -t "$FILE"   # integrity of the archive
[ "$(gunzip -c "$FILE" | grep -c "CREATE TABLE")" -ge 20 ] || { echo "backup looks incomplete"; rm -f "$FILE"; exit 1; }
echo "wrote $FILE ($(du -h "$FILE" | cut -f1))"
# keep 14 days locally; ALSO copy backups off the server (object storage / another host).
find backups -name 'flowqr-*.sql.gz' -mtime +14 -delete
