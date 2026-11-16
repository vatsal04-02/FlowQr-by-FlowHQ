#!/usr/bin/env bash
# Enter the Cashfree SANDBOX credentials locally, through hidden prompts. They are written only to deploy/sandbox/.env.sandbox (mode 600, ignored by git) and are never echoed, printed or
# passed on a command line. Run it in your own terminal:   bash deploy/sandbox/set-credentials.sh
# Refuses anything that does not look like a sandbox pair, so a production secret can never be put here by mistake.
set -euo pipefail
cd "$(dirname "$0")"
umask 077
read -r -p "Cashfree SANDBOX client id (App ID): " CID
read -r -s -p "Cashfree SANDBOX client secret (typed hidden): " SEC; echo
read -r -s -p "Webhook secret (press Enter to use the client secret, which is Cashfree's documented default): " WHS; echo
[ -n "$CID" ] && [ -n "$SEC" ] || { echo "both the client id and the secret are required"; exit 1; }
case "$SEC" in cfsk_ma_prod_*|*_prod_*) echo "that looks like a PRODUCTION secret: refusing"; exit 1;; esac
case "$CID$SEC" in *\'*|*\"*|*' '*|*$'\n'*) echo "quotes, spaces and newlines are not allowed"; exit 1;; esac
[ "${#SEC}" -ge 16 ] || { echo "the secret looks too short"; exit 1; }
{
  echo "CASHFREE_CLIENT_ID=$CID"
  echo "CASHFREE_CLIENT_SECRET=$SEC"
  [ -n "$WHS" ] && echo "CASHFREE_WEBHOOK_SECRET=$WHS"
} > .env.sandbox
chmod 600 .env.sandbox
echo "saved deploy/sandbox/.env.sandbox (client id $(printf %s "$CID" | cut -c1-6)..., secret $(printf %s "$SEC" | wc -c) characters, not shown)"
