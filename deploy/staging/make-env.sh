#!/usr/bin/env bash
# Generates .env.staging with fresh random secrets (never committed; .env.* is git-ignored).
# Usage: deploy/staging/make-env.sh [staging-domain]     e.g. flowqr-staging.dev
set -euo pipefail
D=${1:-flowqr-staging.dev}
OUT=.env.staging
[ -e "$OUT" ] && { echo "$OUT exists; refusing to overwrite (delete it first)"; exit 1; }
rand() { openssl rand -hex "$1"; }
FERNET=$(openssl rand -base64 32 | tr "+/" "-_" | tr -d "
")   # url-safe base64 of 32 random bytes (a Fernet key); no Python needed
umask 077
cat > "$OUT" <<ENV
APP_ENV=staging
SECRET_KEY=$(rand 32)
TOKEN_ENCRYPTION_KEY=$FERNET
POSTGRES_PASSWORD=$(rand 16)
APP_DB_PASSWORD=$(rand 16)
MARKETING_DOMAIN=$D
APP_DOMAIN=app.$D
API_DOMAIN=api.$D
CARD_DOMAIN=go.$D
NEXT_PUBLIC_SITE_URL=https://$D
FRONTEND_URL=https://app.$D
PUBLIC_CARD_BASE_URL=https://go.$D
CORS_ORIGINS=https://app.$D
GOOGLE_REDIRECT_URI=https://app.$D/api/v1/google/callback
COOKIE_SECURE=true
ACME_EMAIL=ops@$D
PLATFORM_ADMIN_EMAILS=admin@$D
# --- integrations: fill in REAL staging credentials here (leave empty to keep the feature in 'configuration pending') ---
GEMINI_API_KEY=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
RAZORPAY_KEY_ID=
RAZORPAY_KEY_SECRET=
RAZORPAY_WEBHOOK_SECRET=
CARD_PRICE_PAISE=
# --- email: set a real provider here. The default below is the local Mailpit sink from docker-compose.mail-sink.yml ---
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_STARTTLS=false
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=FlowQR Staging <no-reply@$D>
ENV
echo "wrote $OUT (mode 600)"
