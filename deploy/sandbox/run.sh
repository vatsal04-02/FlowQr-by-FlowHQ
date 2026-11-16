#!/usr/bin/env bash
# Local Cashfree sandbox stack. Usage (from the repo root):
#   bash deploy/sandbox/run.sh up       build and start db, redis, api, worker, frontend (http://localhost:3300) and the one-path webhook gate. No tunnel yet.
#   bash deploy/sandbox/run.sh tunnel   start the TEMPORARY tunnel to the webhook gate and print its public https address (paste it into Cashfree: Payment Gateway > Developers >
#                                       Webhooks > Subscriptions, version 2026-01-01, URL <address>/api/v1/webhooks/cashfree)
#   bash deploy/sandbox/run.sh status   what is running, whether credentials are loaded (never their values)
#   bash deploy/sandbox/run.sh down     stop everything, including the tunnel, and remove the sandbox containers (the sandbox database volume is kept; `down -v` removes it too)
set -euo pipefail
cd "$(dirname "$0")"
[ -f .env.sandbox ] || { echo "no credentials yet: run  bash deploy/sandbox/set-credentials.sh  first"; exit 1; }
export SANDBOX_TOKEN_KEY=${SANDBOX_TOKEN_KEY:-$(python3 -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())' 2>/dev/null || python -c 'import base64,os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')}
C="docker compose -f docker-compose.sandbox.yml"
case "${1:-}" in
  up)     $C up -d --build db redis migrate api worker frontend webhook-gate; $C ps ;;
  tunnel) $C --profile tunnel up -d tunnel; for i in $(seq 1 30); do u=$($C logs tunnel 2>&1 | grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' | tail -1 || true); [ -n "$u" ] && break; sleep 2; done
          [ -n "${u:-}" ] && echo "tunnel: $u   webhook URL: $u/api/v1/webhooks/cashfree" || { echo "no tunnel address yet: see  $C logs tunnel"; exit 1; } ;;
  status) $C ps; echo "credentials file: $(stat -c '%a' .env.sandbox 2>/dev/null || echo missing) (values never printed)"; curl -s -m 5 http://127.0.0.1:8300/api/ready || true; echo ;;
  down)   shift || true; $C --profile tunnel down "$@" ;;
  *)      sed -n 2,9p "$0"; exit 1 ;;
esac
