#!/usr/bin/env bash
# Proves a backup can be restored, WITHOUT touching the live database: decrypts it, restores it into a throwaway PostgreSQL container,
# checks that the schema and data are really there, deletes the container, and records the proof in backups/status.json
# (the admin Operations page then shows "restore last proven <date>").
#
#   deploy/verify-restore.sh                       newest local backup in ./backups
#   deploy/verify-restore.sh backups/flowqr-XXXX.sql.gz.enc
#   deploy/verify-restore.sh --from-remote         fetch the newest copy from BACKUP_REMOTE first (proves the OFF-SITE copy, the one that matters in a disaster)
# Needs: docker, openssl (when encrypted). Settings: BACKUP_PASSPHRASE_FILE, BACKUP_REMOTE (see backup.sh), MIN_TABLES (default 20).
set -uo pipefail
DIR=backups
STATUS="$DIR/status.json"
MIN_TABLES=${MIN_TABLES:-20}
NAME="flowqr-restore-check-$$"
WORK=$(mktemp -d)
trap 'docker rm -f "$NAME" >/dev/null 2>&1; rm -rf "$WORK"' EXIT
die() { echo "RESTORE CHECK FAILED: $1" >&2; exit 1; }

FILE=${1:-}
if [ "$FILE" = "--from-remote" ]; then
  [ -n "${BACKUP_REMOTE:-}" ] || die "BACKUP_REMOTE is not set"
  case "$BACKUP_REMOTE" in
    s3://*)   latest=$(aws s3 ls "${BACKUP_REMOTE%/}/" | awk '{print $4}' | grep -E 'sql\.gz(\.enc)?$' | sort | tail -1); [ -n "$latest" ] || die "no backup found at $BACKUP_REMOTE"
              aws s3 cp "${BACKUP_REMOTE%/}/$latest" "$WORK/$latest" --only-show-errors && aws s3 cp "${BACKUP_REMOTE%/}/$latest.sha256" "$WORK/$latest.sha256" --only-show-errors ;;
    rclone:*) latest=$(rclone lsf "${BACKUP_REMOTE#rclone:}" | grep -E 'sql\.gz(\.enc)?$' | sort | tail -1); [ -n "$latest" ] || die "no backup found at $BACKUP_REMOTE"
              rclone copyto "${BACKUP_REMOTE#rclone:}/$latest" "$WORK/$latest" && rclone copyto "${BACKUP_REMOTE#rclone:}/$latest.sha256" "$WORK/$latest.sha256" ;;
    [A-Za-z]:/*) latest=$(ls -1 "$BACKUP_REMOTE" | grep -E 'sql\.gz(\.enc)?$' | sort | tail -1); [ -n "$latest" ] || die "no backup found at $BACKUP_REMOTE"
              cp "$BACKUP_REMOTE/$latest" "$BACKUP_REMOTE/$latest.sha256" "$WORK/" ;;
    *:*)      latest=$(ssh "${BACKUP_REMOTE%%:*}" "ls -1 ${BACKUP_REMOTE#*:} | grep -E 'sql\.gz(\.enc)?\$' | sort | tail -1"); [ -n "$latest" ] || die "no backup found at $BACKUP_REMOTE"
              scp -q "${BACKUP_REMOTE%/}/$latest" "${BACKUP_REMOTE%/}/$latest.sha256" "$WORK/" ;;
    *)        latest=$(ls -1 "$BACKUP_REMOTE" | grep -E 'sql\.gz(\.enc)?$' | sort | tail -1); [ -n "$latest" ] || die "no backup found at $BACKUP_REMOTE"
              cp "$BACKUP_REMOTE/$latest" "$BACKUP_REMOTE/$latest.sha256" "$WORK/" ;;
  esac
  FILE="$WORK/$latest"; [ -f "$FILE" ] || die "download failed"
  SOURCE="off-site copy"
else
  [ -n "$FILE" ] || FILE=$(ls -1 "$DIR"/flowqr-*.sql.gz* 2>/dev/null | grep -v '\.sha256$' | sort | tail -1)
  [ -f "$FILE" ] || die "no backup file found"
  SOURCE="local copy"
fi
echo "checking $FILE ($SOURCE)"

if [ -f "$FILE.sha256" ]; then ( cd "$(dirname "$FILE")" && sha256sum -c "$(basename "$FILE").sha256" >/dev/null ) || die "checksum does not match: the file was damaged or altered"; echo "checksum ok"; fi

PLAIN="$WORK/restore.sql.gz"
if [[ "$FILE" == *.enc ]]; then
  [ -s "${BACKUP_PASSPHRASE_FILE:-}" ] || die "encrypted backup but BACKUP_PASSPHRASE_FILE is not set"
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass "file:$BACKUP_PASSPHRASE_FILE" -in "$FILE" -out "$PLAIN" 2>/dev/null || die "could not decrypt (wrong passphrase or damaged file)"
else
  cp "$FILE" "$PLAIN"
fi
gzip -t "$PLAIN" || die "archive is corrupt after decryption"

docker run -d --name "$NAME" -e POSTGRES_PASSWORD=restore-check -e POSTGRES_DB=restorecheck postgres:16-alpine >/dev/null || die "could not start the throwaway database"
for i in $(seq 1 40); do docker exec "$NAME" pg_isready -U postgres -d restorecheck >/dev/null 2>&1 && [ "$(docker logs "$NAME" 2>&1 | grep -c 'ready to accept connections')" -ge 2 ] && break; sleep 1; done
# the dump references the roles it was taken with; create them so ownership/grants restore exactly as in production
docker exec "$NAME" psql -U postgres -d restorecheck -qc "CREATE ROLE flowqr SUPERUSER LOGIN; CREATE ROLE flowqr_app LOGIN;" >/dev/null 2>&1
gunzip -c "$PLAIN" | docker exec -i "$NAME" psql -U postgres -d restorecheck -v ON_ERROR_STOP=1 --single-transaction -q >/dev/null 2>"$WORK/err.txt" || die "restore failed: $(head -c 300 "$WORK/err.txt")"

q() { docker exec "$NAME" psql -U postgres -d restorecheck -Atc "$1"; }
TABLES=$(q "select count(*) from information_schema.tables where table_schema='public'")
REV=$(q "select version_num from alembic_version")
TENANTS=$(q "select count(*) from tenants")
USERS=$(q "select count(*) from users")
CARDS=$(q "select count(*) from qr_cards")
RLS=$(q "select count(*) from pg_policies where policyname='tenant_isolation'")
echo "restored: tables=$TABLES migration=$REV tenants=$TENANTS users=$USERS qr_cards=$CARDS rls_policies=$RLS"
[ "${TABLES:-0}" -ge "$MIN_TABLES" ] || die "too few tables ($TABLES)"
[ -n "$REV" ] || die "no migration version in the restored database"
[ "${RLS:-0}" -ge 5 ] || die "row-level security policies did not restore"

NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
if [ -f "$STATUS" ]; then
  if grep -q '"restore_verified_at"' "$STATUS"; then sed -i "s/\"restore_verified_at\": *\(null\|\"[^\"]*\"\)/\"restore_verified_at\": \"$NOW\"/" "$STATUS"; else sed -i "s/}\$/, \"restore_verified_at\": \"$NOW\"}/" "$STATUS"; fi
fi
echo "RESTORE VERIFIED ($SOURCE) at $NOW. The live database was not touched."
