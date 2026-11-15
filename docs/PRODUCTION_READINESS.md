# Production readiness: what is done, what is yours to do

Status as of 2026-11-15. "Verified" = executed here; "Yours" = needs your accounts, keys or a decision. Nothing in this file has been deployed or committed.

## Built and verified
| Area | State |
|---|---|
| Backend tests (pytest, real PostgreSQL 16, migrations from scratch to 0025) | **995 passed, 0 failed** (2026-11-15, after the AI upgrade). Google and the AI are test doubles in these tests, so this proves our code, not Google or the model |
| Browser tests (Playwright, Edge, isolated stack, final build) | `ops.js` 5/5, `agent-and-posts.js` 31/31, `google-business-agent.js` 10/10, `qr-and-access.js` 23/23. Google Business calls are stubbed (mocked, not live); the Local ranking step makes one real Places search. `smoke.js` is a legacy suite for the pre-redesign UI and is not maintained. Four locator fixes in the suites this round were test-side (hidden duplicate text), not product defects |
| Live Google, **read-only** (`python -m app.cli google-smoke --connection <id>`) | PASS: profile, services, special hours, reviews, posts, photos, search keywords, performance |
| Live Google, **writes** (reply, post, photo, profile edit) | **Not tested.** Do one controlled test with a throwaway item before launch |
| Tenant isolation (API + PostgreSQL RLS), CSRF, rate limits, encrypted tokens, audit log | Covered by tests |
| Error handling in the UI | Route error page, global error page, 404 page, instant loading skeleton (added) |
| Accessibility basics | Keyboard rail/palette, 44 px targets, visible focus, `aria` names, reduced motion, light/dark contrast checked |
| Config guard | `APP_ENV=production` refuses to start with dev secrets, `COOKIE_SECURE=false`, no SMTP, test Razorpay keys, localhost URLs |
| Reverse proxy | `deploy/Caddyfile` sets HSTS and security headers (validated with Caddy 2.8.4 earlier) |
| Backups | **Encrypted (AES-256), off-site copy, status file, restore proven**: a real backup of the dev database was encrypted, copied to a stand-in off-site folder, then restored into a throwaway PostgreSQL (46 tables, migration, 37 RLS policies, your data) with the live DB untouched; wrong passphrase and a tampered file are refused. A real remote (S3, SFTP, rclone) is yours to configure |
| Production-mode boot (isolated stack, `REQUIRE_HARDENED`) | All 7 services (db, redis, migrate, api, worker, beat, frontend) healthy; migrations ran from an empty database to 0024; worker heartbeat recorded by beat; Operations checks ran for real; `preflight` flagged exactly the missing real credentials. Caddyfile validated with `caddy validate`; prod compose config valid |
| Operations monitoring | `/admin/ops` + 15-minute `ops_watch` with admin email alerts; Sentry wiring (needs your DSN); AI budget, subscriptions, Google health, failed jobs, backup freshness (tested: 16 tests) |
| Autonomous agent | Six capabilities as one agent, autonomy matrix served from code and tested ([AI_AUTONOMY.md](AI_AUTONOMY.md)); public actions always need approval |
| AI intelligence upgrade | Business-intelligence layer, task-specific prompts, quality validators, post ideas, six-part optimizer recommendations, AI Output Acceptance Rate, benchmark + regression guards (60 tests). **Measured with the real model on 56 invented cases; no human has rated the outputs and the acceptance rate has no real decisions yet.** See [AI_INTELLIGENCE.md](AI_INTELLIGENCE.md) and [ai-eval/RESULTS.md](ai-eval/RESULTS.md) |

## Yours to do before real customers
1. **Production `.env`**: set `APP_ENV=production`, a random `SECRET_KEY` (32+ chars), a different Fernet `TOKEN_ENCRYPTION_KEY`, `COOKIE_SECURE=true`, real `FRONTEND_URL`, `PUBLIC_CARD_BASE_URL`, `CORS_ORIGINS`, a production database password. The app will not start otherwise, by design.
2. **Google Cloud project** (see "Google APIs" below): enable the APIs, add production redirect URIs, complete OAuth verification for the `business.manage` scope, request Business Profile API access if the project is not yet approved.
3. **Email**: a real SMTP provider (`SMTP_HOST`, user, password, `SMTP_FROM`). Verification, invitations, password resets and notification emails all depend on it.
4. **Razorpay**: live keys and webhook secret (checkout shows "configuration pending" without them).
5. **AI**: the Gemini key is set locally; put it and a monthly budget alert in production.
6. **Error monitoring**: built (Sentry for API, worker, beat and browser crashes); create a Sentry project and set `SENTRY_DSN`. Until you do, `/admin/ops` shows "critical" for it, on purpose.
7. **Legal pages** (privacy, terms, data deletion) are written but have not been reviewed by a lawyer; set the support email.
8. **Change the platform admin password** from the one issued in chat: `python -m app.cli set-admin-password --email <you>` on the production database. Keep `PLATFORM_ADMIN_EMAILS` to real staff only.
9. **Run migrations** (`docker compose up -d --build` runs the `migrate` service): this change set adds 0020 to 0025 (0025 adds `ai_outputs` and the audience field) (round trip 0022 → 0019 → 0022 tested with data preserved).
10. **First live write test** (needs your go-ahead and a test location): `python -m app.cli google-write-test` is a dry run until you add `--execute --confirm-location`; see GOOGLE_SETUP.md. Then approve one reply, one post and one photo through the app.
11. **Backups for real**: choose the off-site store, set `BACKUP_REMOTE` and `BACKUP_PASSPHRASE_FILE`, keep a copy of the passphrase off the server, cron `deploy/backup.sh` nightly and `deploy/verify-restore.sh --from-remote` weekly.
12. **Run `python -m app.cli preflight`** on the production server and clear every FAIL line; `--smtp-test you@example.com` proves real email delivery.

## Google APIs
Already used by FlowQR (all must be enabled in the Cloud project; the live read test passed for each):
- Google My Business API (v4): reviews, replies, posts, media
- My Business Account Management API
- My Business Business Information API: profile, categories, services, hours
- Business Profile Performance API: daily metrics and search keywords
- OAuth 2.0 (business.manage scope) and Google sign-in (separate OAuth client)

Optional, would add real features (each is a separate enable, verified against Google's current docs):
- **My Business Notifications API** (`mybusinessnotifications.googleapis.com`) + **Cloud Pub/Sub**: Google pushes new and updated reviews instead of FlowQR polling every 30 minutes, so replies can be drafted within seconds. Needs a Pub/Sub topic, granting `mybusiness-api-pubsub@system.gserviceaccount.com` publish rights, and a public webhook endpoint.
- **My Business Verifications API** (`mybusinessverifications.googleapis.com`): show a location's verification state and start verification from FlowQR. Photos only appear on Google once a profile is verified, so this removes a common "why isn't my photo live" support question.
- **My Business Place Actions API**: booking and order links on profiles (only if you want to manage those).
- **My Business Lodging API**: hotel amenities (only if you serve hotels).
- **Places API (New)**: powers GBP Manager › Local ranking (built; see "Local ranking" below). Billed Maps Platform product, separate from Business Profile.

Cannot be built: the Q&A API was discontinued by Google on 3 November 2025 with no replacement.

## Local ranking (Places API (New))
- Built: tracked search terms per location (max 10), positions measured from the first 20 Places results around the location, dated history, a weekly automatic re-check (Celery `check_ranks`, every 6 h picks what is due) and a monthly cap per business (`RANK_MONTHLY_CHECK_CAP`, default 300 calls). Owners/admins add terms and run checks; staff can read.
- Verified: 18 backend tests (request shape against Places docs via a mock transport, error mapping, cap, tenant isolation, roles, key never in a response); live read-only calls with the real key on 2026-11-14 (a real location found at position 1 for "physiotherapy"); browser run through UI, API and DB with one real Places search.
- It is a measured approximation, not Google Maps' exact order (the page says so). "Not in top 20" is never replaced by a number; failed checks show as failed.
- **Yours:** the key that was pasted in chat must be replaced with a new restricted key (Places API (New) only, server IP, quota cap, budget alert) in the production `.env` as `RANK_PROVIDER=google_places` and `RANK_PROVIDER_KEY`. Billing must be linked or checks fail with a clear message.

## Release decision (2026-11-15): READY WITH CONDITIONS
Not "READY": real customers must not be onboarded until the conditions below are met. The code, tests and tooling are done; what remains needs your accounts or decisions.

**Closed in this round (AI upgrade included: see AI_INTELLIGENCE.md; the AI quality work adds no new launch condition but its limits are listed there):** autonomy matrix and workflow visibility; operations dashboard and alerts; Sentry wiring; encrypted off-site backup with a proven restore; preflight, admin-password and guarded live-write commands; npm advisory (0 vulnerabilities); migration check; production-mode boot; security re-run (935 tests incl. tenant isolation, location permissions, OAuth, CSRF, route sweep, encrypted tokens, webhook signatures, prompt injection, billing and QR permanence).

**Conditions (in order):**
1. Replace the exposed Places key; set a new admin password (both were pasted in chat).
2. Production `.env` and `preflight` with zero FAIL lines: real SMTP, Razorpay live keys + webhook, Gemini key + `AI_MONTHLY_BUDGET_USD`, `SENTRY_DSN`.
3. Google: OAuth consent screen published, `business.manage` verification, Business Profile API access approved.
4. One controlled live Google write test (`google-write-test`, then one reply/post/photo through the app). **Not run: it needs your explicit approval and a test location.**
5. Real off-site backup target configured, one `verify-restore.sh --from-remote` against it.
6. Lawyer review of privacy, terms, refund and data-deletion pages (they exist and are linked, including account deletion, data export and a support contact, but are not legally reviewed).

**Accepted risks:** no `script-src` CSP (two static inline scripts, no user HTML; planned nonce policy); AI budget alerts but does not hard-stop; photo analysis is metadata-based.
Rollback: previous images and `alembic downgrade 0023` (drops the AI tracking table and the audience field, and the read grant on `alembic_version`); take a database backup first.
