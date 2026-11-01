# Deployment guide (single VPS with Docker Compose + Caddy)

> The Compose files validate with `docker compose config`, but **images were not built or started in the authoring environment (no Docker daemon)**. Do a staging run first and report anything that needs adjusting.

## 1. Prerequisites
* A Linux server (2 vCPU / 4 GB RAM is plenty to start), Docker Engine + Compose v2.
* DNS A/AAAA records for `APP_DOMAIN` (e.g. `app.flowqr.co.in`) **and** `CARD_DOMAIN` (e.g. `go.flowqr.co.in`) → the server. Ports 80/443/udp443 open.
* An SMTP provider (invitations & password resets) and, when ready, Google + Gemini credentials.

## 2. Choose the card domain carefully
`PUBLIC_CARD_BASE_URL` is encoded into every printed QR/NFC card. **Set it to the final card domain (`https://go.flowqr.co.in`) before generating any batch**; the backend refuses to start in production with a `localhost` value.

## 3. Configure
```bash
git clone <repo> /opt/flowqr && cd /opt/flowqr
cp .env.example .env && chmod 600 .env
```
Set at least: `APP_ENV=production`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY` (**back this key up; losing it makes stored Google tokens unreadable**), `POSTGRES_PASSWORD`, `APP_DB_PASSWORD`, `FRONTEND_URL=https://app.…`, `PUBLIC_CARD_BASE_URL=https://go.…`, `CORS_ORIGINS=https://app.…`, `COOKIE_SECURE=true`, `GOOGLE_REDIRECT_URI=https://app.…/api/v1/google/callback`, `PLATFORM_ADMIN_EMAILS`, `APP_DOMAIN`, `CARD_DOMAIN`, `ACME_EMAIL`, SMTP_*.

## 4. Start
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose ps                 # migrate should show "Exited (0)"
docker compose logs -f api worker beat
curl -fsS https://app.example.in/api/health
```
Register your platform-admin account (email in `PLATFORM_ADMIN_EMAILS`) **before** announcing the site, then remove nothing; additional admins are made by adding emails and registering.

The first start creates the non-superuser `flowqr_app` role (`db/init/01-app-role.sh`). **If you reuse an existing Postgres volume that predates this script, create the role manually** (see README), otherwise the API cannot connect.

## 5. Google Business Profile setup (when ready)
1. Google Cloud project → enable *My Business Account Management API*, *My Business Business Information API* and the Business Profile reviews API (v4) and **apply for Business Profile API access** (approval is manual and can take time).
2. OAuth consent screen (external; scope `https://www.googleapis.com/auth/business.manage`; your privacy-policy URL), then an OAuth client (Web). Authorised redirect URI = `GOOGLE_REDIRECT_URI`.
3. Put `GOOGLE_CLIENT_ID/SECRET` in `.env`, `docker compose up -d api worker beat`. The "Configuration pending" banner disappears. Until Google approves API access, Google itself returns 403 and sync shows an error. Manual-link mode keeps working.

## 6. Operations
* **Backups**: `0 2 * * * cd /opt/flowqr && ./deploy/backup.sh >> backups/backup.log 2>&1`; copy `backups/` to off-site storage; rehearse `deploy/restore.sh`.
* **Updates**: `git pull && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` (migrations run automatically via the `migrate` service).
* **Scaling**: raise `--concurrency` on `worker`; API `--workers`. Redis/Postgres are single instances: move them to managed services when needed (`DATABASE_URL`, `MIGRATION_DATABASE_URL`, `REDIS_URL`).
* **Logs** contain no tokens, passwords or review text from customers.
* **Rotating `SECRET_KEY`** invalidates OAuth state in flight only; sessions are server-side. **Rotating `TOKEN_ENCRYPTION_KEY`** requires re-connecting Google accounts.

## 7. Production checklist
See [SECURITY.md](SECURITY.md#pre-launch-checklist).
