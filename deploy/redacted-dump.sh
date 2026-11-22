#!/usr/bin/env bash
# Write a database dump (plain SQL, gzip) in which Google content older than REDACT_DAYS has been redacted, WITHOUT touching the live database.
#   deploy/redacted-dump.sh <output.sql.gz> [redact_days]
# How: dump the live database, restore that dump into a scratch database inside the same Postgres container, run deploy/backup-redact.sql there, check that nothing older than the limit survived,
# dump the scratch database, drop it. The unredacted intermediate exists only in the pipe and the scratch database (dropped on exit, also on failure).
# Why: Google's published storage limit is 30 calendar days. A backup kept K days must hold nothing older than (30 - K) days: backup.sh passes REDACT_DAYS = 30 - K - 1.
# Environment: COMPOSE (as in backup.sh), DB_USER (default flowqr), DB_NAME (default flowqr). Everything else on the database is dumped exactly as it is: recovery of the rest is unchanged.
set -uo pipefail
OUT=${1:?usage: redacted-dump.sh <output.sql.gz> [redact_days]}
DAYS=${2:-15}
COMPOSE=${COMPOSE:-docker compose}
DB_USER=${DB_USER:-flowqr}
DB_NAME=${DB_NAME:-flowqr}
SCRATCH=flowqr_redact_$$
HERE=$(cd "$(dirname "$0")" && pwd)
case "$DAYS" in ''|*[!0-9]*) echo "redact_days must be a whole number" >&2; exit 2;; esac
[ "$DAYS" -ge 1 ] && [ "$DAYS" -le 29 ] || { echo "redact_days must be 1 to 29" >&2; exit 2; }
psql_in() { $COMPOSE exec -T db psql -U "$DB_USER" -d "$1" -q -v ON_ERROR_STOP=1 "${@:2}"; }
cleanup() { $COMPOSE exec -T db psql -U "$DB_USER" -d postgres -q -c "DROP DATABASE IF EXISTS $SCRATCH" </dev/null >/dev/null 2>&1; }
trap cleanup EXIT
psql_in postgres -c "CREATE DATABASE $SCRATCH" </dev/null || { echo "cannot create the scratch database" >&2; exit 1; }
$COMPOSE exec -T db pg_dump -U "$DB_USER" -d "$DB_NAME" --no-owner | psql_in "$SCRATCH" -o /dev/null || { echo "restore into the scratch database failed" >&2; exit 1; }
psql_in "$SCRATCH" -v days="$DAYS" -o /dev/null < "$HERE/backup-redact.sql" || { echo "redaction failed" >&2; exit 1; }
LEFT=$(printf '%s\n' "SELECT (SELECT count(*) FROM reviews WHERE first_seen_at < now() - make_interval(days => :days) AND (text IS NOT NULL OR reviewer_name IS NOT NULL OR google_reply_text IS NOT NULL)) + (SELECT count(*) FROM gbp_metric_daily WHERE first_fetched_at < now() - make_interval(days => :days)) + (SELECT count(*) FROM gbp_snapshots WHERE fetched_at < now() - make_interval(days => :days) AND (info IS NOT NULL OR posts IS NOT NULL OR media IS NOT NULL OR performance IS NOT NULL)) + (SELECT count(*) FROM reply_drafts WHERE created_at < now() - make_interval(days => :days) AND status IN ('draft','approved','failed','rejected'))" | psql_in "$SCRATCH" -At -v days="$DAYS")  # (psql does not interpolate :days inside -c, so the query goes in on stdin)
[ "${LEFT:-x}" = "0" ] || { echo "redaction check failed: $LEFT record(s) older than $DAYS days still hold Google content" >&2; exit 1; }
$COMPOSE exec -T db pg_dump -U "$DB_USER" -d "$SCRATCH" --no-owner | gzip -9 > "$OUT" || { rm -f "$OUT"; echo "dump of the redacted copy failed" >&2; exit 1; }
gzip -t "$OUT" || { rm -f "$OUT"; echo "redacted archive is corrupt" >&2; exit 1; }
echo "redacted dump written: $OUT (Google content older than $DAYS days removed; the live database was not changed)"
