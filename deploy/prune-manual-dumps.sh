#!/usr/bin/env bash
# Remove MANUAL database dumps (pre-release and restore-check copies) older than MANUAL_DUMP_KEEP_DAYS (default 14). backup.sh runs this after every nightly backup, so no separate cron entry is needed.
# They contain Google content as it was when they were taken, and Google's published storage limit is 30 calendar days
# (docs/audits/GOOGLE_RETENTION_ARCHITECTURE.md). The nightly encrypted backups are rotated by backup.sh (BACKUP_KEEP_DAYS) and are not touched here.
# It never touches env or compose copies. DRY_RUN=1 only lists what it would remove.
#   BACKUP_DIR              default /opt/flowqr/backups
#   MANUAL_DUMP_KEEP_DAYS   default 14 (a manual dump is NOT redacted unless it was made with redacted-dump.sh, so it must go before its oldest content reaches 30 days)
set -eu
DIR=${BACKUP_DIR:-/opt/flowqr/backups}
DAYS=${MANUAL_DUMP_KEEP_DAYS:-14}
[ -d "$DIR" ] || { echo "no such folder: $DIR" >&2; exit 2; }
n=0
while IFS= read -r f; do
  n=$((n+1))
  if [ "${DRY_RUN:-0}" = "1" ]; then echo "would remove: $(basename "$f")"; else rm -f -- "$f"; echo "removed: $(basename "$f")"; fi
done < <(find "$DIR" -maxdepth 1 -type f \( -name 'pre-*.dump' -o -name 'restore-check-*.dump' \) -mtime +"$DAYS")
echo "$(date -u +%FT%TZ) manual dumps older than $DAYS days: $n"
