#!/bin/sh
# Runs once on first database initialisation. Creates the NON-superuser role the API connects as,
# so PostgreSQL Row-Level Security policies are actually enforced (superusers bypass RLS).
set -e
psql -v ON_ERROR_STOP=1 -v pw="$APP_DB_PASSWORD" --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-'EOSQL'
  CREATE ROLE flowqr_app LOGIN PASSWORD :'pw' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
  GRANT CONNECT ON DATABASE flowqr TO flowqr_app;
EOSQL
