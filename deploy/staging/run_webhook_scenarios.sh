#!/usr/bin/env bash
# Runs the Razorpay webhook scenarios against the running staging stack. Requires /tmp/out/seed.json from smoke_stack.py.
set -euo pipefail
cd "$(dirname "$0")/../.."
COMPOSE=${COMPOSE:-"docker compose -p flowqr-staging --env-file .env.staging -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.mail-sink.yml -f docker-compose.local-tls.yml"}
SECRET=$(grep '^RAZORPAY_WEBHOOK_SECRET=' .env.staging | cut -d= -f2)
run() { docker run --rm --network flowqr-staging_default -v "$PWD/deploy/staging:/s:ro" -v /tmp/caddy-root.crt:/ca.crt:ro -v /tmp/out:/out \
  -e SSL_CERT_FILE=/ca.crt -e STAGING_DOMAIN=flowqr-staging.dev -e RAZORPAY_WEBHOOK_SECRET="$SECRET" flowqr-backend:local python "/s/$1"; }
TENANT=$(python3 -c "import json;print(json.load(open('/tmp/out/seed.json'))['tenant_id'])")
COMPOSE="$COMPOSE" deploy/staging/seed_billing.sh "$TENANT" >/dev/null
rc=0
run razorpay_webhook_scenarios.py | grep -v '^PHASE2' || rc=$?
echo "-- (simulating 8 days passing without a successful retry: shifting past_due_since back)"
$COMPOSE exec -T db psql -U flowqr -d flowqr -v ON_ERROR_STOP=1 -q <<'SQL'
SELECT set_config('app.bypass_rls','on',false);
UPDATE subscriptions SET past_due_since = now() - interval '8 days' WHERE razorpay_subscription_id='sub_STAGING0001';
SQL
run razorpay_webhook_phase2.py || rc=$?
exit $rc
