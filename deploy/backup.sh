#!/usr/bin/env bash
# Encrypted logical PostgreSQL backup, copied off the server, with a status file the admin Operations page reads.
# Run from the repo root, e.g. nightly via cron:
#   0 2 * * * cd /opt/flowqr && ./deploy/backup.sh >> backups/backup.log 2>&1
#
# Settings (environment, or a .env.backup file next to docker-compose.yml that you `set -a; . .env.backup; set +a`):
#   BACKUP_PASSPHRASE_FILE  file containing the encryption passphrase (chmod 600). KEEP A COPY OFF THE SERVER: without it a backup cannot be opened.
#   BACKUP_REMOTE           where the encrypted copy goes. One of:
#                             /mnt/offsite/flowqr            a mounted directory (NFS, another disk)
#                             user@host:/backups/flowqr      scp
#                             s3://bucket/prefix             aws cli (works with any S3-compatible store; set AWS_ENDPOINT_URL for non-AWS)
#                             rclone:remote:path             rclone
#   COMPOSE                 e.g. "docker compose -p flowqr-staging --env-file .env.staging -f docker-compose.yml"
#   BACKUP_KEEP_DAYS        local retention (default 14, 1 to 28). Set remote retention in the remote's own lifecycle rules (the same limit applies to the remote copy).
#   GOOGLE CONTENT          Google's published storage limit is 30 calendar days. Every backup is therefore written from a REDACTED COPY (deploy/redacted-dump.sh): Google content older than
#                           (30 - BACKUP_KEEP_DAYS - 1) days is removed from the copy before it is dumped, so a backup kept BACKUP_KEEP_DAYS days never holds content older than 30 days.
#                           The live database is not changed, and everything else is dumped as it is. After ANY restore, run the retention job before serving traffic (docs/audits/GOOGLE_RETENTION_ARCHITECTURE.md).
# Without a passphrase the backup is written unencrypted and the status says so (the Operations page then shows a warning).
set -uo pipefail
COMPOSE=${COMPOSE:-docker compose}
KEEP=${BACKUP_KEEP_DAYS:-14}
case "$KEEP" in ''|*[!0-9]*) echo "BACKUP_KEEP_DAYS must be a whole number" >&2; exit 2;; esac
[ "$KEEP" -ge 1 ] && [ "$KEEP" -le 28 ] || { echo "BACKUP_KEEP_DAYS must be 1 to 28 so that Google content never outlives its 30-day limit in a backup" >&2; exit 2; }
REDACT_DAYS=$((30 - KEEP - 1))
HERE=$(cd "$(dirname "$0")" && pwd)
DIR=${BACKUP_DIR:-backups}   # BACKUP_DIR lets staging and production keep separate folders and status files
STATUS="$DIR/status.json"
mkdir -p "$DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RAW="$DIR/flowqr-${STAMP}.sql.gz"
OUT="$RAW"
ENCRYPTED=false
OFFSITE=false
REMOTE_NOTE=""
UPLOADED=false
REMOTE_VERIFIED_AT=""

prev_verified() { [ -f "$STATUS" ] && sed -n 's/.*"restore_verified_at": *"\([^"]*\)".*/\1/p' "$STATUS" | head -1; }
write_status() {  # ok error file size_mb
  local v vj=null; v=$(prev_verified); [ -n "$v" ] && vj="\"$v\""
  printf '{"ok": %s, "error": "%s", "finished_at": "%s", "file": "%s", "size_mb": %s, "encrypted": %s, "offsite": %s, "offsite_verified_at": %s, "restore_verified_at": %s}\n' \
    "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$3" "${4:-0}" "$ENCRYPTED" "$OFFSITE" "$( [ -n "${REMOTE_VERIFIED_AT:-}" ] && echo "\"$REMOTE_VERIFIED_AT\"" || echo null )" "$vj" > "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"
}
fail() { echo "BACKUP FAILED: $1" >&2; rm -f "$RAW" "$RAW.enc"; write_status false "$1" "" 0; exit 1; }

COMPOSE="$COMPOSE" "$HERE/redacted-dump.sh" "$RAW" "$REDACT_DAYS" || fail "redacted dump failed (no unredacted backup is ever written)"
gzip -t "$RAW" || fail "archive is corrupt"
[ "$(gunzip -c "$RAW" | grep -c "CREATE TABLE")" -ge 20 ] || fail "backup looks incomplete (too few tables)"

if [ -n "${BACKUP_PASSPHRASE_FILE:-}" ] && [ -s "$BACKUP_PASSPHRASE_FILE" ]; then
  openssl enc -aes-256-cbc -pbkdf2 -iter 600000 -salt -pass "file:$BACKUP_PASSPHRASE_FILE" -in "$RAW" -out "$RAW.enc" || fail "encryption failed"
  # prove the encrypted file opens before the plain one is deleted
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass "file:$BACKUP_PASSPHRASE_FILE" -in "$RAW.enc" | gzip -t || fail "encrypted copy does not decrypt"
  rm -f "$RAW"; OUT="$RAW.enc"; ENCRYPTED=true
else
  echo "WARNING: BACKUP_PASSPHRASE_FILE not set: this backup is NOT encrypted" >&2
fi
( cd "$DIR" && sha256sum "$(basename "$OUT")" > "$(basename "$OUT").sha256" )

if [ -n "${BACKUP_REMOTE:-}" ]; then
  name=$(basename "$OUT")
  PROBE=$(mktemp -d)
  # 1) upload, 2) read it BACK and compare its sha256 with the local file: OFFSITE is true only when the copy that sits at the destination is byte-identical. A copy that was written but cannot be read back is a failure.
  case "$BACKUP_REMOTE" in
    s3://*)     aws s3 cp "$OUT" "${BACKUP_REMOTE%/}/$name" --only-show-errors && aws s3 cp "$OUT.sha256" "${BACKUP_REMOTE%/}/$name.sha256" --only-show-errors \
                  && aws s3 cp "${BACKUP_REMOTE%/}/$name" "$PROBE/$name" --only-show-errors && UPLOADED=true ;;
    rclone:*)   rclone copyto "$OUT" "${BACKUP_REMOTE#rclone:}/$name" && rclone copyto "$OUT.sha256" "${BACKUP_REMOTE#rclone:}/$name.sha256" \
                  && rclone copyto "${BACKUP_REMOTE#rclone:}/$name" "$PROBE/$name" && UPLOADED=true ;;
    [A-Za-z]:/*) mkdir -p "$BACKUP_REMOTE" && cp "$OUT" "$OUT.sha256" "$BACKUP_REMOTE/" && cp "$BACKUP_REMOTE/$name" "$PROBE/$name" && UPLOADED=true ;;  # a Windows drive path, not host:path
    *:*)        scp -q "$OUT" "$OUT.sha256" "${BACKUP_REMOTE%/}/" && scp -q "${BACKUP_REMOTE%/}/$name" "$PROBE/$name" && UPLOADED=true ;;
    *)          mkdir -p "$BACKUP_REMOTE" && cp "$OUT" "$OUT.sha256" "$BACKUP_REMOTE/" && cp "$BACKUP_REMOTE/$name" "$PROBE/$name" && UPLOADED=true ;;
  esac
  if [ "${UPLOADED:-false}" = true ] && [ "$(sha256sum "$PROBE/$name" | cut -d' ' -f1)" = "$(sha256sum "$OUT" | cut -d' ' -f1)" ]; then
    OFFSITE=true; REMOTE_VERIFIED_AT=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  else
    echo "WARNING: the off-site copy FAILED its integrity check (or could not be uploaded); the backup is not safely stored off this server" >&2
  fi
  rm -rf "$PROBE"
  # The same 30-day Google content limit applies to the remote copy: this backup holds nothing older than REDACT_DAYS, so the remote must not keep it longer than KEEP days. Enforced here where the destination allows listing
  # by age; for S3 set a lifecycle rule that expires objects after KEEP days (this script cannot see or change it, and says so).
  case "$BACKUP_REMOTE" in
    s3://*)     echo "NOTE: set the bucket's lifecycle rule to expire objects after $KEEP days (not enforced or verified by this script)" >&2 ;;
    rclone:*)   rclone delete "${BACKUP_REMOTE#rclone:}" --min-age "${KEEP}d" --include 'flowqr-*.sql.gz*' >/dev/null 2>&1 || echo "WARNING: remote pruning failed" >&2 ;;
    [A-Za-z]:/*|/*) find "$BACKUP_REMOTE" -maxdepth 1 -name 'flowqr-*.sql.gz*' -mtime +"$KEEP" -delete 2>/dev/null || true ;;
    *:*)        h=${BACKUP_REMOTE%%:*}; d=${BACKUP_REMOTE#*:}; ssh -o BatchMode=yes "$h" "find '$d' -maxdepth 1 -name 'flowqr-*.sql.gz*' -mtime +$KEEP -delete" >/dev/null 2>&1 || echo "WARNING: remote pruning failed" >&2 ;;
  esac
else
  echo "WARNING: BACKUP_REMOTE not set: the backup has NOT been copied off this server" >&2
fi

SIZE=$(du -k "$OUT" | cut -f1); SIZE_MB=$(awk "BEGIN{printf \"%.2f\", $SIZE/1024}")
echo "wrote $OUT (${SIZE_MB} MB) encrypted=$ENCRYPTED offsite=$OFFSITE"
write_status true "" "$(basename "$OUT")" "$SIZE_MB"
find "$DIR" -name 'flowqr-*.sql.gz*' -mtime +"$KEEP" -delete
BACKUP_DIR="$DIR" "$HERE/prune-manual-dumps.sh" || echo "WARNING: pruning manual dumps failed" >&2   # manual pre-release dumps hold Google content too
[ "$OFFSITE" = true ] && [ "$ENCRYPTED" = true ]   # exit non-zero when the backup is not fully safe, so cron mails you
