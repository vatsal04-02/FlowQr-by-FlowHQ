#!/usr/bin/env bash
# Independent dead-man's switch for the worker and beat.
#
# WHY: the app's own alerting (`ops_watch`) runs inside the worker, so if beat, the worker, Redis or the server stops, nothing inside can tell you. This script runs from the HOST's cron, reads the
# beat -> worker heartbeat key straight from Redis (it does not go through the app or Celery), and pings an EXTERNAL monitor only while that heartbeat is fresh. When the pings stop, the external
# service e-mails or messages you. It therefore also notices Docker or the whole server being down, which no in-stack check can.
#
# Install (as the deploy user, once; this file is NOT installed by any release step):
#   1. create a "heartbeat" / dead-man's-switch check at an external service (Healthchecks.io, Better Stack, Cronitor...): expected every 1 minute, grace 5 minutes, alert to you by e-mail
#      or a messaging app. Put its ping URL in /opt/flowqr/.env.heartbeat as:   HEARTBEAT_PING_URL=https://...        (chmod 600; it is a secret-ish URL)
#   2. crontab -e:   * * * * * /opt/flowqr/deploy/vps/heartbeat-ping.sh
# Optional settings (environment or .env.heartbeat): REDIS_CONTAINER (default flowqr-production-redis-1), HEARTBEAT_KEY (default flowqr:ops:heartbeat), MAX_AGE_SECONDS (default 180).
# What counts as healthy: the key exists and is at most MAX_AGE_SECONDS old. beat writes it through the worker every 60 seconds, so a fresh key proves beat scheduled the task, Redis carried
# it and the worker ran it. Reads only: it never writes to Redis or the database. Exit code 0 = a ping was sent, 1 = unhealthy (no ping), 2 = misconfigured.
set -uo pipefail
HERE=$(cd "$(dirname "$0")/../.." && pwd)
[ -f "$HERE/.env.heartbeat" ] && { set -a; . "$HERE/.env.heartbeat"; set +a; }
URL=${HEARTBEAT_PING_URL:-}
[ -n "$URL" ] || { echo "heartbeat-ping: HEARTBEAT_PING_URL is not set" >&2; exit 2; }
CONTAINER=${REDIS_CONTAINER:-flowqr-production-redis-1}
KEY=${HEARTBEAT_KEY:-flowqr:ops:heartbeat}
MAX=${MAX_AGE_SECONDS:-180}
raw=$(docker exec "$CONTAINER" redis-cli get "$KEY" 2>/dev/null | tr -d '\r')
case "$raw" in ''|'(nil)') echo "heartbeat-ping: no heartbeat in redis (worker or beat not running, or redis down): no ping sent" >&2; exit 1;; esac
age=$(awk -v now="$(date +%s)" -v hb="$raw" 'BEGIN { a = now - hb; if (a < 0) a = 0; printf "%d", a }')
if [ "$age" -gt "$MAX" ]; then echo "heartbeat-ping: heartbeat is ${age}s old (limit ${MAX}s): no ping sent" >&2; exit 1; fi
curl -fsS -m 10 --retry 2 -o /dev/null "$URL" || { echo "heartbeat-ping: could not reach the external monitor" >&2; exit 1; }
exit 0
