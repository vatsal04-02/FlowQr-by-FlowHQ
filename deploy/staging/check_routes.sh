#!/usr/bin/env bash
# Verifies Caddy routing for the 4 hostnames over TLS (resolves them to 127.0.0.1, trusts Caddy local CA). Exits non-zero on any failure.
D=${STAGING_DOMAIN:-flowqr-staging.dev}; CA=${CADDY_ROOT_CA-/tmp/caddy-root.crt}   # CADDY_ROOT_CA='' (empty): trust the system store, for real certificates
BODY=$(mktemp); trap 'rm -f "$BODY"' EXIT
# Git Bash on Windows runs a native curl.exe that does not understand /tmp paths: hand it Windows-style paths
if command -v cygpath >/dev/null 2>&1; then [ -n "$CA" ] && CA=$(cygpath -m "$CA"); BODY_ARG=$(cygpath -m "$BODY"); else BODY_ARG=$BODY; fi
CACERT=(); [ -n "$CA" ] && CACERT=(--cacert "$CA")
# RESOLVE_IP=none: run inside the compose network, where the hostnames already resolve (Caddy network aliases from docker-compose.local-tls.yml)
RESOLVE_IP=${RESOLVE_IP:-127.0.0.1}; RES=()
[ "$RESOLVE_IP" = none ] || for h in $D www.$D app.$D api.$D go.$D; do RES+=(--resolve "$h:443:$RESOLVE_IP" --resolve "$h:80:$RESOLVE_IP"); done
fails=0
t() { # name url expected_code [needle]
  local out code
  out=$(curl -sS --noproxy '*' "${CACERT[@]}" "${RES[@]}" -o "$BODY_ARG" -w "%{http_code} %{redirect_url}" ${METHOD:+-X $METHOD} "$2" 2>&1); code=${out%% *}
  local extra=""
  if [ -n "${4:-}" ]; then if grep -qF -- "$4" "$BODY" 2>/dev/null || [[ "$out" == *"$4"* ]]; then extra=" has[$4]"; else extra=" MISSING[$4]"; code=BAD; fi; fi
  local s=PASS; [ "$code" = "$3" ] || { s=FAIL; fails=$((fails+1)); }
  printf "%-4s %-50s -> %s%s\n" $s "$1" "$out" "$extra"
}
echo "== marketing ($D)"
t "GET /" https://$D/ 200 "FlowQR"; t "GET /pricing" https://$D/pricing 200 "Growth"
for pg in about demo google-business review-cards ai-growth-agent industries privacy terms refund-policy data-deletion; do t "GET /$pg stays on the marketing host" https://$D/$pg 200 "FlowQR"; done
t "marketing host serves the live plans (pricing page needs it)" https://$D/api/v1/billing/plans 200 starter; t "marketing host serves legal info" https://$D/api/v1/legal/info 200 company; METHOD=POST t "marketing host reaches the demo form endpoint (validation error, not a redirect)" https://$D/api/v1/public/leads 422
t "marketing host does NOT expose other API routes" https://$D/api/v1/auth/me 302; t "marketing host does NOT expose the API docs/health" https://$D/api/health 302
t "GET /robots.txt" https://$D/robots.txt 200 "Sitemap: https://"; t "GET /sitemap.xml uses the public origin" https://$D/sitemap.xml 200 "https://$D/pricing"; t "GET /marketing/restaurants.jpg (asset)" https://$D/marketing/restaurants.jpg 200
t "GET /login leaves marketing host" https://$D/login 302 "https://app.$D/login"; t "GET /api/health not exposed" https://$D/api/health 302
t "www -> apex (301)" https://www.$D/pricing 301 "https://$D/pricing"
echo "== app (app.$D)"
t "GET /login" https://app.$D/login 200 "Welcome back"; t "GET /api/health (Caddy->api)" https://app.$D/api/health 200 '"ok"'
t "GET /api/v1/billing/plans" https://app.$D/api/v1/billing/plans 200 starter; t "/api/docs hidden in staging" https://app.$D/api/docs 404; t "/api/openapi.json hidden" https://app.$D/api/openapi.json 404
echo "== api (api.$D)"
t "GET /api/health" https://api.$D/api/health 200 '"ok"'; t "GET / (no frontend served)" https://api.$D/ 200 "FlowQR API"; t "GET /login (not served)" https://api.$D/login 200 "FlowQR API"
METHOD=POST t "POST webhook without signature -> rejected" https://api.$D/api/v1/billing/razorpay/webhook 400
echo "== card (go.$D)"
t "GET /c/<token> landing page" https://go.$D/c/abcdefghijklmnopqrstuvwx 200 "<html"; t "public API unknown token -> not_found" https://go.$D/api/v1/public/c/abcdefghijklmnopqrstuvwx 404 not_found
t "GET /dashboard -> redirect to app" https://go.$D/dashboard 302 "https://app.$D/dashboard"
t "/api/v1/auth/me NOT proxied" https://go.$D/api/v1/auth/me 302; t "/api/health NOT proxied" https://go.$D/api/health 302; t "/api/v1/billing/plans NOT proxied" https://go.$D/api/v1/billing/plans 302
echo "== http -> https"
t "http://go upgrades" http://go.$D/c/abc 308 "https://go.$D/c/abc"; t "http://marketing upgrades" http://$D/pricing 308
echo "== security headers (app)"
curl -sSI --noproxy '*' "${CACERT[@]}" "${RES[@]}" https://app.$D/login | grep -iE "strict-transport|x-frame|x-content-type|referrer-policy|^server:|x-powered|permissions" 
echo; echo "ROUTE FAILURES: $fails"
exit $((fails>0))
