#!/usr/bin/env bash
# Verifies Caddy routing for the 4 hostnames over TLS (resolves them to 127.0.0.1, trusts Caddy local CA). Exits non-zero on any failure.
D=${STAGING_DOMAIN:-flowqr-staging.dev}; CA=${CADDY_ROOT_CA:-/tmp/caddy-root.crt}
RES=(); for h in $D www.$D app.$D api.$D go.$D; do RES+=(--resolve "$h:443:127.0.0.1" --resolve "$h:80:127.0.0.1"); done
fails=0
t() { # name url expected_code [needle]
  local out code
  out=$(curl -sS --noproxy '*' --cacert $CA "${RES[@]}" -o /tmp/body -w "%{http_code} %{redirect_url}" ${METHOD:+-X $METHOD} "$2" 2>&1); code=${out%% *}
  local extra=""
  if [ -n "${4:-}" ]; then if grep -qF -- "$4" /tmp/body 2>/dev/null || [[ "$out" == *"$4"* ]]; then extra=" has[$4]"; else extra=" MISSING[$4]"; code=BAD; fi; fi
  local s=PASS; [ "$code" = "$3" ] || { s=FAIL; fails=$((fails+1)); }
  printf "%-4s %-50s -> %s%s\n" $s "$1" "$out" "$extra"
}
echo "== marketing ($D)"
t "GET /" https://$D/ 200 "AI-powered"; t "GET /pricing" https://$D/pricing 200 "Simple pricing"
t "GET /login leaves marketing host" https://$D/login 302 "https://app.$D/login"; t "GET /api/health not exposed" https://$D/api/health 302
t "www -> apex (301)" https://www.$D/pricing 301 "https://$D/pricing"
echo "== app (app.$D)"
t "GET /login" https://app.$D/login 200 "Welcome back"; t "GET /api/health (Caddy->api)" https://app.$D/api/health 200 '"ok"'
t "GET /api/v1/billing/plans" https://app.$D/api/v1/billing/plans 200 essential; t "/api/docs hidden in staging" https://app.$D/api/docs 404; t "/api/openapi.json hidden" https://app.$D/api/openapi.json 404
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
curl -sSI --noproxy '*' --cacert $CA "${RES[@]}" https://app.$D/login | grep -iE "strict-transport|x-frame|x-content-type|referrer-policy|^server:|x-powered|permissions" 
echo; echo "ROUTE FAILURES: $fails"
exit $((fails>0))
