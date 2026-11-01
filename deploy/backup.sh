#!/usr/bin/env bash
# Logical PostgreSQL backup (compressed). Run from the repo root, e.g. nightly via cron:
#   0 2 * * * cd /opt/flowqr && ./deploy/backup.sh >> backups/backup.log 2>&1
set -euo pipefail
mkdir -p backups
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
FILE="backups/flowqr-${STAMP}.sql.gz"
docker compose exec -T db pg_dump -U flowqr -d flowqr --no-owner | gzip -9 > "$FILE"
echo "wrote $FILE ($(du -h "$FILE" | cut -f1))"
# keep 14 days locally; ALSO copy backups off the server (object storage / another host).
find backups -name 'flowqr-*.sql.gz' -mtime +14 -delete
