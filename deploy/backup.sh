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
#   BACKUP_KEEP_DAYS        local retention (default 14). Set remote retention in the remote's own lifecycle rules.
# Without a passphrase the backup is written unencrypted and the status says so (the Operations page then shows a warning).
set -uo pipefail
COMPOSE=${COMPOSE:-docker compose}
KEEP=${BACKUP_KEEP_DAYS:-14}
DIR=${BACKUP_DIR:-backups}   # BACKUP_DIR lets staging and production keep separate folders and status files
STATUS="$DIR/status.json"
mkdir -p "$DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
RAW="$DIR/flowqr-${STAMP}.sql.gz"
OUT="$RAW"
ENCRYPTED=false
OFFSITE=false
REMOTE_NOTE=""

prev_verified() { [ -f "$STATUS" ] && sed -n 's/.*"restore_verified_at": *"\([^"]*\)".*/\1/p' "$STATUS" | head -1; }
write_status() {  # ok error file size_mb
  local v vj=null; v=$(prev_verified); [ -n "$v" ] && vj="\"$v\""
  printf '{"ok": %s, "error": "%s", "finished_at": "%s", "file": "%s", "size_mb": %s, "encrypted": %s, "offsite": %s, "restore_verified_at": %s}\n' \
    "$1" "$2" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$3" "${4:-0}" "$ENCRYPTED" "$OFFSITE" "$vj" > "$STATUS.tmp" && mv "$STATUS.tmp" "$STATUS"
}
fail() { echo "BACKUP FAILED: $1" >&2; rm -f "$RAW" "$RAW.enc"; write_status false "$1" "" 0; exit 1; }

$COMPOSE exec -T db pg_dump -U flowqr -d flowqr --no-owner | gzip -9 > "$RAW" || fail "pg_dump failed"
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
  case "$BACKUP_REMOTE" in
    s3://*)     aws s3 cp "$OUT" "${BACKUP_REMOTE%/}/$name" --only-show-errors && aws s3 cp "$OUT.sha256" "${BACKUP_REMOTE%/}/$name.sha256" --only-show-errors && OFFSITE=true ;;
    rclone:*)   rclone copyto "$OUT" "${BACKUP_REMOTE#rclone:}/$name" && rclone copyto "$OUT.sha256" "${BACKUP_REMOTE#rclone:}/$name.sha256" && OFFSITE=true ;;
    [A-Za-z]:/*) mkdir -p "$BACKUP_REMOTE" && cp "$OUT" "$OUT.sha256" "$BACKUP_REMOTE/" && OFFSITE=true ;;  # a Windows drive path, not host:path
    *:*)        scp -q "$OUT" "$OUT.sha256" "${BACKUP_REMOTE%/}/" && OFFSITE=true ;;
    *)          mkdir -p "$BACKUP_REMOTE" && cp "$OUT" "$OUT.sha256" "$BACKUP_REMOTE/" && OFFSITE=true ;;
  esac
  [ "$OFFSITE" = true ] || { echo "WARNING: the off-site copy FAILED; the backup exists only on this server" >&2; }
else
  echo "WARNING: BACKUP_REMOTE not set: the backup has NOT been copied off this server" >&2
fi

SIZE=$(du -k "$OUT" | cut -f1); SIZE_MB=$(awk "BEGIN{printf \"%.2f\", $SIZE/1024}")
echo "wrote $OUT (${SIZE_MB} MB) encrypted=$ENCRYPTED offsite=$OFFSITE"
write_status true "" "$(basename "$OUT")" "$SIZE_MB"
find "$DIR" -name 'flowqr-*.sql.gz*' -mtime +"$KEEP" -delete
[ "$OFFSITE" = true ] && [ "$ENCRYPTED" = true ]   # exit non-zero when the backup is not fully safe, so cron mails you
