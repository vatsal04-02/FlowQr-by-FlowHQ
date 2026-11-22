#!/usr/bin/env bash
# Rehearse a release in a THROWAWAY compose project before anything touches production: the real startup guard (accepts a production-shaped configuration, refuses three unsafe ones, including the
# 2026-11-22 incident), the migration step, the deployment preflight, and the recreate of api, worker and beat with both compose files.
#
#   deploy/vps/rehearse-release.sh <image tag> [encrypted backup file] [passphrase file]
#
#   <image tag>   an image already built as flowqr-backend:<tag>  (docker build -t flowqr-backend:<tag> ./backend)
#   backup file   optional: a backup made by deploy/backup.sh, restored into the rehearsal database first, so the migration step runs against production-shaped data
#
# Safety: its own compose project (fq-rehearsal), network, containers and volumes; every secret is generated for the occasion and is fake; the SMTP host does not resolve; no Google, Razorpay, Cashfree or
# AI key is set, so nothing here can reach a real service; the API is published only on 127.0.0.1:18010. It refuses to run under the production project name. It removes everything it created on exit.
# The switches mirror production as reported on 2026-11-22 (agency on, internal-only, adopt-existing on, retention on, registration allowlist) so a change that the real guard would refuse shows up here.
# NOT proven by this script: the real production environment file (it cannot see it), real Google/mail/payment behaviour, the shared proxy. Exit code 0 = every expected result happened.
set -uo pipefail
TAG=${1:?usage: rehearse-release.sh <image tag> [backup file] [passphrase file]}
BACKUP=${2:-}
PASSFILE=${3:-}
PROJECT=fq-rehearsal
[ "$PROJECT" != "flowqr-production" ] || { echo "refusing to run under the production project name" >&2; exit 2; }
cd "$(dirname "$0")/../.."
docker image inspect "flowqr-backend:$TAG" >/dev/null 2>&1 || { echo "image flowqr-backend:$TAG does not exist: build it first" >&2; exit 2; }
ENVF=$(mktemp)
rand() { openssl rand -base64 24 | tr -d '/+=\n' | head -c 32; }
fernet() { docker run --rm --entrypoint python "flowqr-backend:$TAG" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"; }
cat > "$ENVF" <<EOF
FLOWQR_TAG=$TAG
APP_ENV=production
POSTGRES_PASSWORD=$(rand)
APP_DB_PASSWORD=$(rand)
SECRET_KEY=$(openssl rand -hex 32)
TOKEN_ENCRYPTION_KEY=$(fernet)
AGENCY_TOKEN_ENCRYPTION_KEY=$(fernet)
FRONTEND_URL=https://www.flowqr.site
CORS_ORIGINS=https://www.flowqr.site
COOKIE_DOMAIN=.flowqr.site
COOKIE_SECURE=true
REQUIRE_VERIFIED_EMAIL=true
PUBLIC_CARD_BASE_URL=https://go.flowqr.site
GOOGLE_CLIENT_ID=rehearsal-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=$(rand)
GOOGLE_REDIRECT_URI=https://api.flowqr.site/api/v1/google/callback
PLATFORM_ADMIN_EMAILS=admin@flowhq.example
REGISTRATION_MODE=allowlist
SMTP_HOST=smtp.invalid.example
SMTP_PORT=587
SMTP_FROM=FlowQR <no-reply@flowqr.site>
GOOGLE_AGENCY_MANAGER_ENABLED=true
GOOGLE_AGENCY_OPERATIONS_ENABLED=true
GOOGLE_AGENCY_PROJECT_MODEL=flowhq_own_project
GOOGLE_AGENCY_INTERNAL_ONLY=true
GOOGLE_AGENCY_OPERATOR_EMAILS=operator@flowhq.example
GOOGLE_AGENCY_INTERNAL_DECISION=rehearsal only: not a Google approval
GOOGLE_AGENCY_LOCATION_GROUP_ID=accounts/114863040359228435467
GOOGLE_AGENCY_ADOPT_EXISTING_ACCESS=true
GOOGLE_AGENCY_CLIENT_TOKEN_KEEP_HOURS=720
GOOGLE_CONTENT_RETENTION_ENABLED=true
GOOGLE_CONTENT_RETENTION_DAYS=30
AUTONOMY_EMERGENCY_STOP=true
FLOWQR_API_PORT=18010
FLOWQR_API_DOCKER0=127.0.0.1
EOF
C="docker compose -p $PROJECT --env-file $ENVF -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml"
FAILS=0
ok() { echo "  PASS  $1"; }
bad() { echo "  FAIL  $1"; FAILS=$((FAILS + 1)); }
cleanup() { $C down -v --remove-orphans >/dev/null 2>&1; rm -f "$ENVF"; }
trap cleanup EXIT
refuses() {  # refuses <label> <expected text> <docker run args...>: the guard must exit non-zero and say why
  local label=$1 want=$2; shift 2
  local out; out=$($C run --rm --no-deps -T "$@" api python -c "import app.main" </dev/null 2>&1); local rc=$?
  if [ $rc -ne 0 ] && echo "$out" | grep -q "Unsafe production configuration" && echo "$out" | grep -q "$want"; then ok "guard refuses: $label"; else bad "guard did not refuse: $label (exit $rc)"; fi
}

echo "== 1. compose renders with both files"
$C config -q && ok "compose config" || bad "compose config"
echo "== 2. throwaway database and redis"
$C up -d db redis >/dev/null 2>&1
for _ in $(seq 1 30); do [ "$($C ps --format '{{.Health}}' db 2>/dev/null)" = "healthy" ] && break; sleep 2; done
[ "$($C ps --format '{{.Health}}' db 2>/dev/null)" = "healthy" ] && ok "db healthy" || bad "db not healthy"
echo "== 3. the real startup guard"
out=$($C run --rm --no-deps -T api python -c "import app.main" </dev/null 2>&1); rc=$?
{ [ $rc -eq 0 ] && ! echo "$out" | grep -q "Unsafe"; } && ok "guard accepts the production-shaped configuration" || { bad "guard refused the production-shaped configuration"; echo "$out" | tail -5; }
refuses "adopt-existing on while the manager switch is off (the 2026-11-22 incident)" "GOOGLE_AGENCY_ADOPT_EXISTING_ACCESS needs GOOGLE_AGENCY_MANAGER_ENABLED" -e GOOGLE_AGENCY_MANAGER_ENABLED=false
refuses "insecure cookies" "COOKIE_SECURE must be true" -e COOKIE_SECURE=false
refuses "agency operations without a recorded basis" "GOOGLE_AGENCY_OPERATIONS_ENABLED needs GOOGLE_AGENCY_POLICY_REFERENCE" -e GOOGLE_AGENCY_INTERNAL_DECISION=
echo "== 4. optional restore of a production-shaped backup"
if [ -n "$BACKUP" ] && [ -n "$PASSFILE" ]; then
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 600000 -pass "file:$PASSFILE" -in "$BACKUP" | gunzip | $C exec -T db psql -U flowqr -d flowqr -q -o /dev/null >/dev/null 2>&1
  rev=$($C exec -T db psql -U flowqr -d flowqr -At -c "select version_num from alembic_version" 2>/dev/null)
  [ -n "$rev" ] && ok "backup restored, alembic at $rev" || bad "backup did not restore"
else echo "  (skipped: no backup given; the migration step below runs from an empty database)"; fi
echo "== 5. the migration step"
$C run --rm --no-deps -T migrate </dev/null >/dev/null 2>&1 && ok "migrate exited 0" || bad "migrate failed"
head=$($C run --rm --no-deps -T api python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('alembic.ini')).get_current_head())" </dev/null 2>/dev/null | tail -1)
cur=$($C exec -T db psql -U flowqr -d flowqr -At -c "select version_num from alembic_version" 2>/dev/null)
[ -n "$head" ] && [ "$head" = "$cur" ] && ok "database is at the image's head ($cur)" || bad "database $cur is not at the image's head $head"
echo "== 6. the deployment preflight (informational: it will FAIL on mail, AI, payment and Sentry here by design; read the rest)"
$C run --rm --no-deps -T api python -m app.cli preflight </dev/null 2>&1 | grep -E "PASS|FAIL|WARN|MANUAL|passed" | grep -v "WhatsApp settings" | cut -c1-150
echo "== 7. recreate api, worker, beat together, --no-deps, both compose files"
$C up -d --no-deps api worker beat >/dev/null 2>&1
for _ in $(seq 1 40); do [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:18010/api/ready)" = "200" ] && break; sleep 3; done
ready=$(curl -s -m 10 http://127.0.0.1:18010/api/ready)
echo "$ready" | grep -q '"ready":true' && ok "/api/ready: $ready" || bad "/api/ready: $ready"
for _ in $(seq 1 40); do hb=$($C exec -T redis redis-cli get flowqr:ops:heartbeat 2>/dev/null | tr -d '\r'); [ -n "$hb" ] && break; sleep 5; done
[ -n "${hb:-}" ] && ok "beat -> worker heartbeat present in redis" || bad "no heartbeat after 200 s"
[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18010/api/v1/agency-ops/tenants)" = "401" ] && ok "operator endpoints demand a login" || bad "operator endpoints answered unexpectedly"
[ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:18010/api/docs)" = "404" ] && ok "API docs are not served" || bad "API docs are served"
$C logs --since 10m api worker beat > "$ENVF.log" 2>&1
n=$(grep -c -i -e Traceback -e Unsafe -e " ERROR" "$ENVF.log"); rm -f "$ENVF.log"
[ "$n" = "0" ] && ok "no error lines in the api, worker and beat logs" || bad "$n error-like log lines"
echo; [ $FAILS -eq 0 ] && echo "REHEARSAL PASSED" || echo "REHEARSAL FAILED: $FAILS check(s)"
exit $((FAILS > 0))
