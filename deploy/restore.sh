#!/usr/bin/env bash
# Restore a backup into the running database. DESTRUCTIVE: replaces current data.
set -euo pipefail
FILE=${1:?usage: deploy/restore.sh backups/flowqr-XXXX.sql.gz}
read -r -p "This will REPLACE the current database with ${FILE}. Type 'yes' to continue: " ok
[ "$ok" = "yes" ] || { echo aborted; exit 1; }
docker compose stop api worker beat frontend
docker compose exec -T db psql -U flowqr -d postgres -c "DROP DATABASE IF EXISTS flowqr WITH (FORCE)" -c "CREATE DATABASE flowqr OWNER flowqr"
gunzip -c "$FILE" | docker compose exec -T db psql -U flowqr -d flowqr
docker compose exec -T db psql -U flowqr -d flowqr -c "GRANT CONNECT ON DATABASE flowqr TO flowqr_app"
docker compose run --rm migrate   # re-applies grants/policies if the dump predates them
docker compose start api worker beat frontend
