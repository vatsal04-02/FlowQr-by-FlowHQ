# FlowQR staging readiness report

**Date:** 2026-11-01 · **Branch:** `claude/admiring-edison-e9a7s3` · **Stack under test:** isolated Compose project `flowqr-staging` (own containers, network, volumes, `.env.staging`).
**Tooling:** Docker 29.9.2 (daemon started manually in the sandbox), Compose v5.6.1, PostgreSQL 16.15, Redis 7, Caddy 2 (container) / 2.8.4 (validator), Mailpit 1.21.

## Verdict

| | |
|---|---|
| **Application + infrastructure** | **Staging-ready.** The full stack builds, starts, persists, survives crashes, routes four domains over TLS, backs up and restores with verified data integrity, and refuses unsafe configuration. |
| **External integrations** | **Not verified.** Real Gemini, Razorpay, Google and a real SMTP provider were **not** tested (no credentials; Razorpay hosts are denied by this sandbox's egress policy). What *was* verified is listed precisely below. |
| **Production** | **Not ready.** See [Deployment blockers](#deployment-blockers). |

**Status legend:** **PASS** executed and passed here · **FAIL** executed and failed · **BLOCKED** cannot be executed without something we don't have · **NOT TESTED** not executed.

**Environment safety statement.** No pre-existing deployment (including any Geeta Krishna Physiotherapy production system) exists in or was reachable from this environment, and none was touched. Everything ran in the isolated `flowqr-staging` project; test fixtures use synthetic data ("Staging Clinic …"). Earlier *local development* runs in this sandbox used a synthetic tenant that was named "Geeta Krishna Physiotherapy" in the e2e script; it is renamed "E2E Demo Physiotherapy" in the repo and existed only in a throw-away local database. **Never point staging at a production database or reuse its volumes, secrets or domain.**

---

## 1. Requested checks

| # | Check | Status | Evidence (details in §2) |
|---|---|---|---|
| 1 | Inspect environment & production configuration | **PASS** | §2.1: config guard; exposure & privilege inventory; no secrets in image/repo |
| 2 | Build all images; run the complete stack | **PASS** (with note) | Backend 379 MB, frontend 355 MB built from the repo Dockerfiles; 8 long-running containers healthy + the one-shot `migrate` (exit 0). *Note:* built with `deploy/staging/build-behind-proxy.sh` (plain `docker build`, same Dockerfiles) because this sandbox's TLS-inspecting proxy blocks `docker compose build`. `docker compose build` on a normal network: **NOT TESTED** |
| 3 | Fix Docker / migration / network / startup errors | **PASS** | First `up` had no startup errors; defects found by testing were fixed (§3) |
| 4 | PostgreSQL persistence; Redis/Celery operation | **PASS** | §2.2: data identical after DB restart, `down`/`up`, and hard SIGKILL; Redis AOF persists; 4 Celery tasks run via Redis; worker reconnects after Redis restart |
| 5 | Caddy routing for all four domains | **PASS** (with note) | 22/22 route checks over real TLS (§2.3). *Note:* hostnames are `*.flowqr-staging.dev` served by Caddy's **internal CA**; Let's Encrypt issuance on public DNS: **NOT TESTED** |
| 6 | Health checks & restart policies | **PASS** | 8 services report `healthy`; all `restart: unless-stopped`; all 7 long-running services recovered from SIGKILL (§2.2) |
| 7 | All backend tests + frontend production build | **PASS** | **139/139** backend tests (109 original + 30 added); `tsc` clean; `next build` 29/29 routes |
| 8 | Backup & restore with real test data | **PASS** | §2.4: 14-table content-checksum snapshot identical after disaster + restore |
| 9 | Registration, verification, reset, invitation with **real SMTP** | **BLOCKED** (real provider) / **PASS** (code path) | No provider credentials. All four flows **PASS** over real SMTP protocol to a Mailpit **sink**; production path (STARTTLS + AUTH + cert verification + failure modes) **PASS** against a TLS/auth-enforcing server I ran. Real delivery, SPF/DKIM/DMARC, inbox placement: **NOT TESTED** |
| 10 | Razorpay test mode: subscriptions, duplicate webhooks, failed payments, cancellation, renewals | **BLOCKED** (Razorpay) / **PASS** (our webhook handler) | No keys; `api.razorpay.com` and `checkout.razorpay.com` return **403 from the sandbox egress policy**. Handler scenarios **27/27 PASS** in-container with *dummy* keys and real HMAC signatures. Real checkout, real webhooks, real renewals/cancel: **NOT TESTED** |
| 11 | Gemini with a real API key | **BLOCKED** | No key. Real endpoint reached with an invalid key → `400 INVALID_ARGUMENT`, mapped to "writing help unavailable". A successful generation and output quality (esp. Hindi/Hinglish): **NOT TESTED** |
| 12 | Prepare Google OAuth config; document API approval | **PASS** (docs) / **BLOCKED** (approval) | [`GOOGLE_SETUP.md`](GOOGLE_SETUP.md). Google-process claims are **UNVERIFIED** (docs host unreachable) and flagged 🔎 |
| 13 | No test credentials / mocks / placeholder pricing can reach production | **PASS** | §2.5: guard refuses test keys, dev secrets, local URLs, sink SMTP, missing price; no mocks exist in `app/` (tested); placeholder price removed |
| 14 | Audit card URL configuration before printing | **PASS** (tool + staging) / **NOT DONE** for production domain | §2.6: `python -m app.cli card-url-audit --live`; real PNG/ZIP QR decode; **must be re-run against the real `go.` domain before printing** |
| 15 | This document | **PASS** | |

---

## 2. Evidence

### 2.1 Configuration & exposure
* API connects as **`flowqr_app`** (`rolsuper=f`, `rolbypassrls=f`); **17** `tenant_isolation` policies, **17** tables with FORCE RLS; Alembic at **0005**, applied from an empty DB by the `migrate` one-shot (exit 0).
* Only **Caddy** publishes ports (80, 443/tcp+udp). Postgres, Redis, API, frontend: unpublished. (Mailpit UI on `127.0.0.1:8025` exists only because the optional sink overlay is in use.)
* API/worker/beat run as uid 10001, frontend as uid 100; none privileged. No `.env` inside the image. `.env.staging` is git-ignored; the only tracked env-like file is `.env.example`.
* Staging/production responses hide `/api/docs` and `/api/openapi.json` (404); `Server` header stripped; HSTS, `nosniff`, `X-Frame-Options: DENY`, referrer & permissions policies present.
* Rate limiting is **not bypassable by spoofing `X-Forwarded-For`/`X-Real-IP`** through Caddy (limiter reached 429 on the 10th attempt with a different spoofed IP each time).
* Dependency audit: **`pip-audit` clean** after upgrading FastAPI 0.115→0.162 / Starlette 0.41→1.10 and removing unused `python-multipart` (they had ~15 advisories). **`npm audit`: 1 moderate + 1 high, both the PostCSS bundled inside Next** (source-map path handling; fix requires the Next 16 major upgrade). Only our own CSS is processed, at build time, so this is **not reachable at runtime**: **ACCEPTED RISK, tracked; not fixed** (see blockers).

### 2.2 Persistence, crash recovery, Celery
| Test | Result |
|---|---|
| `restart db` → 14-table snapshot (counts + md5 of content) | identical; API reconnected on its own |
| `compose down` (no `-v`) → `up` | identical; 4 volumes survived |
| SIGKILL of PID 1 for api, worker, beat, frontend, **db**, redis, caddy | all restarted (restartCount=1), all `healthy` again; **DB identical after crash** |
| `docker kill` | containers stay down. This is Docker's definition of a *manual stop* under `unless-stopped`, not a defect |
| Redis `appendonly yes`; restart | key persisted |
| Celery: registered tasks | `flowqr.billing_refresh`, `retry_failed_replies`, `sync_due_locations`, `sync_location` |
| Tasks executed through Redis | all 3 succeeded; `billing_refresh` really expired a past-due trial (1 → 0 expired-but-trialing) |
| Redis restarted under a running worker | "Connection to broker lost… Trying again", then the next task succeeded |
| Beat | starts with `PersistentScheduler`; **a scheduled (timer-fired) run was not waited for** (intervals 15–60 min): **NOT TESTED** |

### 2.3 Caddy routing (22 checks: `deploy/staging/check_routes.sh`)
* **marketing** `flowqr-staging.dev`: `/`, `/pricing` 200; `/login`, `/api/health` → 302 to `app.`; `www.` → 301 to apex.
* **app** `app.`: `/login` 200; `/api/health` 200 via Caddy→API; `/api/v1/billing/plans` 200; docs/openapi 404.
* **api** `api.`: `/api/health` 200; no frontend served (`/`, `/login` → "FlowQR API"); unsigned Razorpay webhook → 400.
* **card** `go.`: `/c/<token>` 200 HTML; `/api/v1/public/c/<unknown>` 404 `not_found`; **`/api/v1/auth/me`, `/api/health`, `/api/v1/billing/plans` are NOT proxied (302 away)**; `/dashboard` → 302 to `app.`.
* HTTP → HTTPS 308 on both card and marketing hosts.

### 2.3b Application flows in the running stack (HTTPS, via Caddy)
* `deploy/staging/smoke_stack.py`: **32/32 PASS**: registration, verification email (unverified owner blocked from inviting), single-use tokens, onboarding, invitation email + wrong-email rejection + accept, role enforcement, password reset (uniform answer for unknown emails, old sessions revoked, single use), card batch recording the `go.` base URL, assignment, public scan, no internal IDs leaked, scan event recorded.
* Browser e2e (`e2e/smoke.js`, Playwright desktop + 390 px mobile) against `https://app.flowqr-staging.dev`: **PASS** (secure cookies, verification via SMTP, public card page, pricing/subscription/payments/analytics/profile pages, suspension screen + card inactive while suspended, admin console, business user denied admin API and page; no horizontal overflow on mobile).

### 2.4 Backup & restore
1. Seeded state (5 tenants, 16 users, 15+ cards, 9 scans, 134 audit rows, 12 payments, 37 webhook events…) → snapshot **S0** (row counts + md5 of content for 14 tables + card-code sequence).
2. `deploy/backup.sh` → 28 KB `.sql.gz`, `gzip -t` OK, schema completeness check OK.
3. **Disaster:** deleted payments, card orders, scan events, memberships, locations, tenants; un-assigned cards; inserted a junk user.
4. `deploy/restore.sh` (drop DB `WITH (FORCE)`, recreate, load with `ON_ERROR_STOP` + single transaction, migrate, restart services).
5. **Result:** snapshot identical to S0 on all 14 tables; junk row gone; owner logs in with restored password hash; the **printed card token still resolves**; RLS (17 policies / 17 FORCE) and the append-only audit grant (`DELETE FROM audit_logs` → permission denied) intact; the next card batch continued at `FQR-0016` (no number reuse); Alembic 0005.
* **Not tested:** restoring on a *different* server/cluster, off-site copy, restore of a backup from an older release, point-in-time recovery (not implemented: logical dumps only).

### 2.5 "Can't be used in production by accident"
The API refuses to **start** when `APP_ENV` is `staging`/`production` and any of these hold (each verified by unit test **and** by booting the real image):
test Razorpay keys (`rzp_test_`) in production · live keys in staging · keys without webhook secret · `SECRET_KEY` default/short · invalid or reused `TOKEN_ENCRYPTION_KEY` · `COOKIE_SECURE=false` · non-https / localhost / `.test`/`.local`/IP card or app URLs · development DB password · no `PLATFORM_ADMIN_EMAILS` · no SMTP, or SMTP host that is a local sink in production · `REQUIRE_VERIFIED_EMAIL=false` · non-positive card price.
Also: `docker-compose.prod.yml` sets `REQUIRE_HARDENED=true`, so a forgotten `APP_ENV=development` cannot skip the guard · **there is no default card price** (unset ⇒ card ordering disabled and the UI says so; `.env.example` ships it blank) · `app/` contains no Fake/Stub/Mock classes (tested) · fakes exist only under `backend/tests/` · `.env.staging` holds **dummy** Razorpay keys that are labelled as such and that production rejects.

### 2.6 Card URL audit
`python -m app.cli card-url-audit [--live] [--expect-domain go.flowqr.co.in]` checks: public https domain; equals the expected domain; no path/query; URL shape; QR decodes (when OpenCV present); **every existing batch was generated with the current base URL** (each batch now records `base_url`); token uniqueness/length; and with `--live`: valid TLS, landing page, card API reachable, non-card paths redirect away, HTTP→HTTPS.
Results: correct staging config **PASS (11 checks)**; wrong expected domain **FAIL**; untrusted certificate **FAIL** (no verify bypass). Real staging artefacts: the card PNG and **2/2 PNGs in the batch ZIP decode (OpenCV) to exactly their manifest URLs**; the print sheet contains the QR codes.

### 2.7 SMTP
* Flows over the real SMTP protocol to Mailpit: verification, invitation, reset **PASS** (in smoke test).
* Production path against a server enforcing STARTTLS + AUTH with a private CA: correct CA + credentials **PASS**; **untrusted cert → refused** (`SSLCertVerificationError`, no plaintext fallback); wrong password → refused; STARTTLS disabled vs server requiring it → refused; unreachable host → refused. Logs contain only the exception class, never the message/link/credentials.
* **Defect fixed:** failures used to be swallowed, so the API said "invitation sent" when nothing was sent. Invitation responses now carry `email_sent`, the UI warns, and resend-verification reports it.

### 2.8 Razorpay (dummy keys, our handler only) – 27/27
Wrong/missing/tampered signature → 400 and no state change · `subscription.activated` → active on Growth · renewal charges recorded as captured subscription payments · **duplicate delivery → `duplicate`, no extra payment** · same payment under a new event id → not double-counted · `payment.failed` → `past_due`, access continues in grace, failure reason stored · after grace → inactive: writes `402`, reads allowed, **printed cards keep working** · recovery charge restores access · stale event ignored · `halted` → inactive · cancel/checkout against the **real** Razorpay API with dummy keys is not reachable here (egress denied) and fails safely (`502`, state unchanged) · `subscription.cancelled` keeps access to period end · card-order payment marks the order paid and is a separate payment kind.
**Not covered by these tests:** that Razorpay actually sends these payload shapes/headers (`X-Razorpay-Event-Id`), plan/subscription creation, checkout UI, GST.

### 2.9 Gemini / Google (invalid credentials against the real endpoints)
Gemini `generateContent` → **HTTP 400 `API key not valid`** → `AIUnavailable` (UI degrades honestly). Google token endpoint → **401 `invalid_client`**; Account Management API with bogus token → **401** → `GoogleAuthRevoked`. These prove reachability and error mapping only.

---

## 3. Defects found and fixed during this pass
1. **Cross-tenant payment write:** webhook upsert looked payments up by Razorpay id globally, so an event for tenant B could modify tenant A's payment row. Now scoped; regression test added.
2. **Silent email failure:** see §2.7.
3. **Placeholder card price** (`24900`) was a default and shipped in `.env.example`; removed (no default).
4. **Prod overlay could run with `APP_ENV=development`** (skipping the guard); now enforced via `REQUIRE_HARDENED`.
5. **Guard gaps:** no `staging` mode; test/live keys, dev passwords, sink SMTP and `.localhost`/IP hosts were not rejected; `env_ignore_empty` added so blank env vars mean "unset".
6. **Backend dependencies** with ~15 advisories (Starlette/python-multipart) upgraded.
7. **`dump.rdb` (Redis snapshot, no secrets) had been committed**; untracked and ignored. It remains in git history of commit `1994c7c`.
8. **Restore script** could leave a half-restored DB silently; now `ON_ERROR_STOP` + single transaction. Backup script now verifies the archive.
9. **Card batches** did not record which URL was printed; they do now (`card_batches.base_url`, migration 0005) and the audit compares.
10. Added health checks for frontend, worker, beat, caddy; single shared backend image tag; Caddy `tls_mode` hook for local CA; optional proxy-CA build support.

## 4. Sandbox limits (what this environment could not represent)
No public DNS or ACME (local CA used) · containers have no direct internet (provider calls tested from the host) · `api.razorpay.com`, `checkout.razorpay.com` and `developers.google.com` unreachable (policy / DNS) · Docker Hub anonymous rate limit (429) hit once, retried · single host, no load/performance testing · system clock is the sandbox's.

## 5. Outstanding credentials / inputs
| Needed | For |
|---|---|
| Real domains + DNS A/AAAA for `flowqr.co.in` (+`www`), `app.`, `api.`, `go.` (or a staging equivalent) | public TLS (Let's Encrypt) |
| SMTP provider (host, port, user, password, verified sender domain with SPF/DKIM/DMARC) | invitations, resets, verification |
| `GEMINI_API_KEY` (staging) | review assist, reply drafts |
| Razorpay **test** `key_id`/`key_secret`, **webhook secret**, Subscriptions enabled, webhook URL `https://api.<domain>/api/v1/billing/razorpay/webhook` | billing |
| Real **`CARD_PRICE_PAISE`** (business decision) | card orders |
| Google Cloud project, OAuth client, **Business Profile API approval**, consent-screen verification, privacy policy + terms URLs | Google features |
| `PLATFORM_ADMIN_EMAILS` (real FlowHQ admin addresses) | admin console |
| Off-site storage for `backups/` | disaster recovery |

## Deployment blockers
**Blocking go-live (production):**
1. Real SMTP, Razorpay (test then live), Gemini and Google flows have **never run for real** (§1 rows 9–12). Expect first-contact adjustments, especially Google field names.
2. Google Business Profile API approval and OAuth verification (can take days–weeks); **privacy policy and terms pages don't exist**.
3. No GST/tax invoicing, refunds, dunning emails; get tax/legal review before taking live payments.
4. Let's Encrypt issuance, DNS, and `go.` domain TLS untested on a public host; **run `card-url-audit --live` on the real domain before printing any card**.
5. Off-site backups and a rehearsed restore on the real server.
6. Real card price decision.

**Non-blocking, tracked:** Next 16 upgrade (PostCSS advisory, build-time only); `starlette.testclient`+`httpx` deprecation warning in tests; `docker compose build` on an unproxied network untested; beat's timer-driven runs not observed; no frontend component tests/CI; no MFA.

## 6. Exact commands

**A. Real public staging server** (public DNS already pointing at it; real SMTP; Let's Encrypt):
```bash
git clone https://github.com/vatsal04-02/FlowQr-by-FlowHQ.git && cd FlowQr-by-FlowHQ
git checkout claude/admiring-edison-e9a7s3
deploy/staging/make-env.sh staging.yourdomain.in          # writes .env.staging with fresh secrets (mode 600)
$EDITOR .env.staging                                       # set SMTP_*, RAZORPAY_* (rzp_test_), GEMINI_API_KEY, GOOGLE_*, CARD_PRICE_PAISE,
                                                           # PLATFORM_ADMIN_EMAILS, ACME_EMAIL; set SMTP_STARTTLS=true; replace the Mailpit SMTP block with your provider (the sink container is not part of this command)
docker compose -p flowqr-staging --env-file .env.staging -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -p flowqr-staging --env-file .env.staging -f docker-compose.yml -f docker-compose.prod.yml ps   # all healthy; migrate = Exited (0)
docker compose -p flowqr-staging --env-file .env.staging -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm api python -m app.cli card-url-audit --live --expect-domain go.staging.yourdomain.in
```
(`make-env.sh` creates `app./api./go.` subdomains of the domain you give it and a Mailpit-based `.env.staging`; replace the SMTP block with your provider.)

**B. Local / sandbox reproduction (what was run here: local CA, SMTP sink):**
```bash
deploy/staging/make-env.sh                                 # flowqr-staging.dev
export PROXY_CA=/path/to/proxy-ca.pem && deploy/staging/build-behind-proxy.sh      # only if behind a TLS-inspecting proxy; otherwise `docker compose build`
C="docker compose -p flowqr-staging --env-file .env.staging -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.mail-sink.yml -f docker-compose.local-tls.yml"
$C up -d --no-build
# add to /etc/hosts:  127.0.0.1 flowqr-staging.dev www.flowqr-staging.dev app.flowqr-staging.dev api.flowqr-staging.dev go.flowqr-staging.dev
docker cp flowqr-staging-caddy-1:/data/caddy/pki/authorities/local/root.crt /tmp/caddy-root.crt   # trust anchor for the checks
```

**C. Evidence scripts** (`deploy/staging/`): `check_routes.sh` (Caddy), `smoke_stack.py` (flows), `run_webhook_scenarios.sh` (+`seed_billing.sh`, Razorpay handler), `post_restore_check.py`, `snapshot.sh` (persistence/restore checksums), `fetch_card_artifacts.py`, plus `e2e/smoke.js` (browser). Backup/restore: `COMPOSE="$C" deploy/backup.sh` / `echo yes | COMPOSE="$C" deploy/restore.sh backups/<file>.sql.gz`.

**D. Tests:** `cd backend && pytest -q` (139) · `cd frontend && npx tsc --noEmit && npm run build` (29 routes).

**E. Stop / clean the staging stack (keeps data):** `$C down`. Destroy data: `$C down -v` (irreversible).
