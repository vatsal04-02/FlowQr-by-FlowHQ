#!/usr/bin/env bash
# Restore a backup into the running database. DESTRUCTIVE: replaces current data.
set -euo pipefail
COMPOSE=${COMPOSE:-docker compose}
FILE=${1:?usage: deploy/restore.sh backups/flowqr-XXXX.sql.gz}
read -r -p "This will REPLACE the current database with ${FILE}. Type 'yes' to continue: " ok
[ "$ok" = "yes" ] || { echo aborted; exit 1; }
$COMPOSE stop api worker beat frontend
$COMPOSE exec -T db psql -U flowqr -d postgres -c "DROP DATABASE IF EXISTS flowqr WITH (FORCE)" -c "CREATE DATABASE flowqr OWNER flowqr"
gunzip -c "$FILE" | $COMPOSE exec -T db psql -U flowqr -d flowqr -v ON_ERROR_STOP=1 --single-transaction   # any error aborts: never leave a half-restored DB
$COMPOSE exec -T db psql -U flowqr -d flowqr -c "GRANT CONNECT ON DATABASE flowqr TO flowqr_app"
$COMPOSE run --rm migrate   # no-op when the dump is current; upgrades the schema if the dump is from an older release (grants/RLS are part of the dump)
$COMPOSE start api worker beat frontend
