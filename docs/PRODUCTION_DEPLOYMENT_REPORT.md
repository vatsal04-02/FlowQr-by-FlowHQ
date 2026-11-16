# Production deployment report: flowqr.site (Vercel) + api.flowqr.site (Hostinger VPS)

Written 2026-11-15. Statuses: **PASS**, **FAIL**, **BLOCKED**, **NOT TESTED**. They are never merged: *code implemented* is not *tested*, *tested* is not *deployed*, *deployed* is not *tested on the real website*, and none of those is *tested against real external APIs* or *approved for customers*.

## Verdict

**FlowQR is NOT deployed to production.** The frontend builds and is deployed on Vercel (protected, on a `*.vercel.app` address, with no custom domain). The backend has **not** been deployed: the VPS cannot be reached (no working SSH access) and DNS for `flowqr.site` is at GoDaddy, which only you can edit. Everything that could be prepared, tested and verified without those two things is done.

**Exact Git commit prepared for deployment:** `7302031` on branch `phase-2/commercial-readiness` (pushed to `origin`). The Vercel deployment was made from the working tree by the Vercel CLI (not from Git) before that commit existed: **redeploy from the commit** (or connect the repository, below) so that what runs is what is recorded.

## Status table

| Item | Status | Evidence / note |
|---|---|---|
| Repository and Git audit; clean checkpoint; secrets scan | **PASS** | `docs/PHASE_2_CHECKPOINT.md`: 393 entries classified and committed, full history scanned (27 commits), no secrets or env files committed. Nothing force-pushed |
| VPS resource and infrastructure audit | **BLOCKED** | no SSH access. `docs/PRODUCTION_INFRASTRUCTURE_AUDIT.md`, `deploy/vps/audit.sh` |
| Isolated production stack definition (own project, network, volumes, DB, Redis; API on 127.0.0.1 only; no proxy; memory ceilings) | **PASS** (written and validated) | `deploy/vps/docker-compose.vps.yml` renders correctly with `docker compose config`: services `api, beat, db, migrate, redis, worker`; one published port, `127.0.0.1:18000`. **Not run on the VPS** |
| Production settings accepted by the strict config guard | **PASS** (with placeholder values) | the example environment, filled with dummy values, boots `APP_ENV=production`: guard problems `[]` |
| Backend deployed to the VPS | **BLOCKED** | no SSH access |
| Existing Caddy block for `api.flowqr.site` | **PASS** (written) / **NOT TESTED** | `deploy/vps/Caddyfile.flowqr-api`; **never validated against the real Caddy** (not reachable) |
| DNS: `api.flowqr.site` A `201.18.202.128` | **BLOCKED** | GoDaddy; no record exists today |
| DNS and TLS for `flowqr.site` / `www.flowqr.site` on Vercel | **BLOCKED** | GoDaddy; the apex and `www` still point at GoDaddy parking |
| Vercel project `flowqr` (team "vatsal's projects") | **PASS** | created, linked to the `frontend/` directory, Next.js auto-detected |
| Vercel environment variables | **PASS** | `NEXT_PUBLIC_API_URL=https://api.flowqr.site` and `NEXT_PUBLIC_SITE_URL=https://flowqr.site` for Production and Preview. No secret is a `NEXT_PUBLIC_` variable |
| Vercel production build | **PASS** | READY, `https://flowqr-npzrupwrw-vatsals-projects-e2c87193.vercel.app` (alias `https://flowqr-gold.vercel.app`). **Vercel Deployment Protection (Vercel login) is ON**, so the address is not public. It was the project's first deployment, so Vercel assigned it as the production deployment |
| Vercel Git connection (auto-deploy on push) | **NOT DONE** | needs the Vercel GitHub app authorised for this repository and the project's Root Directory set to `frontend` |
| Custom domains on Vercel (`flowqr.site`, `www.flowqr.site`) | **BLOCKED** | add after the DNS decision; choose the canonical host (recommended `flowqr.site`, with `www` redirecting to it) |
| Frontend works against a different-origin API (credentialed CORS, cookies, CSRF, cross-origin images, exposed headers, logout) | **PASS (locally)** | `e2e/split-host.js` 8/8 in Chromium: site on `localhost:3300`, API on `localhost:8100`. **Not tested** on the real domains, over TLS, or with a `Domain=.flowqr.site` cookie |
| Database migrations on the production database | **NOT TESTED** | the production database does not exist; see `docs/PRODUCTION_DATABASE_MIGRATION.md` |
| Backups and restore on the VPS | **NOT TESTED** (procedure proven elsewhere) | `docs/PRODUCTION_BACKUP_RESTORE.md` |
| Real workflows on the real website (20-point list) | **NOT TESTED** | the website has no backend |
| Real Google validation | **partly PASS (stage 1 only)**, rest **NOT TESTED** | `docs/PRODUCTION_EXTERNAL_VALIDATION.md` |
| Real Places validation | **partly PASS**, not a full stage | same file |
| Production security audit | **PASS (internal, pre-deployment)** | `docs/PRODUCTION_SECURITY_AUDIT.md`; nothing was audited on a live server |
| Cashfree | **BLOCKED — WEBSITE LIVE AND CASHFREE MERCHANT CONFIGURATION REQUIRED** | not integrated; Razorpay not configured |

## Architecture as built

* **Browser** loads the site from **Vercel** (`https://flowqr.site`), and sends every API request directly to **`https://api.flowqr.site`** (the existing Caddy on the VPS, which proxies to the FastAPI container on `127.0.0.1:18000`). Nothing is proxied through Vercel: that keeps the real client address for rate limits and avoids Vercel's request-size and time limits on uploads and AI calls.
* Site and API are different hosts of the **same site** (`flowqr.site`), so the session cookie works: `COOKIE_DOMAIN=.flowqr.site`, `Secure`, `HttpOnly`, `SameSite=Lax`; the CSRF cookie is readable by the site; the API allows exactly `https://flowqr.site` and `https://www.flowqr.site` with credentials (`CORS_ORIGINS`), never a wildcard.
* **Changes made to the application for this topology** (all tested): the frontend reads `NEXT_PUBLIC_API_URL` (`frontend/src/lib/config.ts`) and every API call, image and link uses it; the API **exposes** the custom response headers the frontend reads (`X-FlowQR-Not-For-Print`, `-Scannable`, `Content-Disposition`...), without which the "not for print" and "scannable" warnings would silently disappear in production; **`COOKIE_DOMAIN`, `SUPPORT_EMAIL`, `LEGAL_COMPANY_NAME` and `SESSION_TTL_HOURS` were not passed through Docker Compose at all** (the documented settings did nothing) and now are; the strict production guard now **refuses to start** if the site and API are on different hosts and `COOKIE_DOMAIN` does not cover both, or if `CORS_ORIGINS` omits the site's origin.
* **Media** (photos, logos) are stored in PostgreSQL (`LargeBinary`), so there is no file-storage service and the database backup covers them.

## DNS (you must do this in GoDaddy; nothing here has been changed)

| Name | Type | Value | Notes |
|---|---|---|---|
| `api` | A | `201.18.202.128` | exactly as you specified; remove nothing else |
| `flowqr.site` (apex) and `www` | per Vercel | **read the exact records from Vercel after adding the domains** (`vercel domains inspect flowqr.site`, or the project's Domains tab) | Today the apex has A records `3.33.130.190` / `15.197.148.33` and `www` is an alias, both GoDaddy parking. Replace **only those**; do not touch MX, TXT or other records (email, verification) |

Wait for `nslookup` to show the new values, then Vercel issues the certificates by itself. Choose one canonical host and let the other redirect to it (Vercel domain settings).

## Decisions I need from you

1. **Card address (permanent!).** `PUBLIC_CARD_BASE_URL` is printed into every QR code and NFC tag and cannot change afterwards. Options: **`https://flowqr.site`** (shortest; cards depend on Vercel and the API being up) or a dedicated **`https://go.flowqr.site`** served by the VPS (cards survive a frontend change; needs one more DNS record and Caddy block). **Do not print or write any card until this is set and `python -m app.cli card-url-audit --live --expect-domain <host>` passes.** The earlier plan used a separate card domain; this brief lists none.
2. **SSH access** (see the infrastructure audit) or the audit output.
3. **A real SMTP provider.** The production guard refuses to start without one (sign-up verification, invitations and password resets must reach real inboxes).
4. Where off-site backups go (a bucket, another server, or a mounted directory).

## Remaining steps once those exist (in order)

1. Run `deploy/vps/audit.sh`; complete the infrastructure audit; stop if resources are short.
2. Copy the repository to `/opt/flowqr` at the recorded commit; create `.env.production` from `deploy/vps/.env.production.example` (fresh secrets, `chmod 600`; **do not reuse the development `.env`**).
3. `docker compose -p flowqr-production --env-file .env.production -f docker-compose.yml -f deploy/vps/docker-compose.vps.yml up -d --build`; confirm `migrate` exits 0 and `alembic current` is `0031`.
4. Add `deploy/vps/Caddyfile.flowqr-api` to the existing Caddy; `caddy validate`; graceful `caddy reload`; check `https://api.flowqr.site/api/ready`.
5. Add the DNS records; add the domains in Vercel; redeploy the frontend from the recorded commit; confirm TLS.
6. Run `e2e/split-host.js` and the product checks against the real domains (labelled test accounts only).
7. Back up, restore into an isolated database, verify (`docs/PRODUCTION_BACKUP_RESTORE.md`).
8. Keep autonomous writes, maps and payments off for real customers until their own validation passes (below).

## Controls that stay on (nothing here is auto-enabled)

The emergency stop and approvals are unchanged. **Note:** autonomy and template auto-replies are **on by default for every business** by owner decision (2026-11-15). On a new production database that means a business is created with them on. Before the first real customer is connected to Google, either validate the write paths on your test profile (`docs/PRODUCTION_EXTERNAL_VALIDATION.md`) or set `AUTONOMY_EMERGENCY_STOP=true` in `.env.production`, which holds every Google write platform-wide until you lift it. Maps need approved allowances (set) **and** a Places key and cap; payments are not wired.

## Known risks

Vercel Deployment Protection is on (good) and a **protection-bypass secret was created by the Vercel CLI** while checking the deployment (revoke it: project settings, Deployment Protection). The Google OAuth consent screen is in **Testing** mode (100 testers, refresh tokens expire after 7 days) until the Business Profile scope is verified. No error-monitoring destination is configured. CI passed on earlier pushes; the latest run was still in progress when last checked.
