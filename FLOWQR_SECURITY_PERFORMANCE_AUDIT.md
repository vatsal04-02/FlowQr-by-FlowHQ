# FlowQR security and performance audit

Date: 2026-11-25 · Branch: `feature/google-marketing-studio` (local work, **not pushed, not deployed**) · Production at the time of the audit: backend `prod-a4a27d0` (alembic 0069), Vercel `flowqr-qf28ytvho`.

**How to read this.** Everything here was measured or tested in this session unless it says "not measured" or "blocked". Performance numbers come from a local copy of the real backend (real PostgreSQL with forced row-level security) and a local production build of the real frontend; they are **not** production numbers and **not** real-phone numbers. No secret value appears in this document: services and variable names only. Nothing was run against production except read-only checks (the live JavaScript bundles were downloaded and scanned; headers, TLS and CORS were inspected; server memory and disk were read). No load test, scan or fuzz was run against production, Google or any payment provider.

Evidence (scripts and raw results) is in [`audit/`](audit/): `audit/scripts/` (benchmark, secret scanners, browser measurement, CSP survey) and `audit/results/` (raw JSON, build logs, summaries).

---

## 1. Security findings

### Verified safe (with how it was checked)

| Area | Result | Evidence |
|---|---|---|
| Secrets in the browser | **None found.** The live production JavaScript (downloaded) and a full local production build were scanned for key/token/secret patterns and for the actual secret values the server holds. Only public identifiers (Google client ID, API origin) appear, which are meant to be public. | `audit/scripts/scan.py` |
| Secrets in git history | **None found** in the full history (patterns only; matches would have been printed redacted). | `audit/scripts/histscan.py` |
| Secrets in API responses | **None.** New test `test_no_secrets_in_responses.py` reads **every readable (GET) route**, built from the live route table so new routes are covered automatically, as the owner, as location-limited staff and as a platform admin (plus the owner against admin routes). It checks each body for field names that only secrets have, for the real secret values this environment holds (Google tokens and client secret, token-encryption key, AI keys, SMTP password, payment secrets, database URLs), and for stack traces / driver text. >200 route×actor checks. A self-test proves the detector catches a leaked value, a secret-named field and a stack trace. | `backend/tests/test_no_secrets_in_responses.py` |
| Tenant isolation, API level | Existing hardening sweeps (owner A cannot read or write business B's data on any route) pass. | `test_hardening_isolation.py`, `test_phase2_security_audit.py` |
| Tenant isolation, database level | **New:** `test_rls_filters_every_tenant_table.py` connects as the **application role** and, for every table with a `tenant_id` column (read from the live catalogue, ≥30 tables), asserts business A sees exactly its own rows, business B exactly its own, a business that owns nothing sees **zero**, and a session with **no** tenant set and no bypass sees **zero** rows. Proves the policies filter, not just that they exist. The application role is a non-superuser without BYPASSRLS and RLS is FORCEd. | `backend/tests/test_rls_filters_every_tenant_table.py` |
| Route authorization | Every route is classified in `route_access_manifest.txt` and a test fails if a route is added unclassified or a protected route answers anonymously. | existing |
| Transport, headers, CORS | HTTPS with a valid certificate; HSTS on both hosts; the API sends a deny-all CSP, `nosniff`, `X-Frame-Options: DENY` and Referrer-Policy; the site sends `nosniff`, `X-Frame-Options: DENY`, Referrer-Policy, Permissions-Policy; a foreign origin gets no CORS allow-origin header (re-checked 2026-11-25). | live inspection |
| Payment and WhatsApp webhooks | Cashfree/Razorpay signatures are checked with constant-time comparison on the raw body, with a 5-minute replay window; bad signature / stale timestamp / garbage change nothing (tests exist and pass). WhatsApp outbound webhook endpoints that could reach private addresses (loopback, link-local, a name resolving to any private address) are refused (SSRF tests exist and pass). | `test_cashfree_provider.py`, `test_prepaid_checkout.py`, `test_whatsapp_integrations.py` |
| Rate limits | Login, registration, public scans, card lookups, data export, agency start, geo-grid and others are rate-limited, each with a test. | existing tests |
| AI is text only | Only text chat-completions requests for one model; no image/audio generation anywhere (a test greps the code). | `test_ai_text_only.py` |

### Findings and what was done

| # | Severity | Finding | Status |
|---|---|---|---|
| S1 | P1 | **An OpenAI API key was pasted into the chat** (not into any file or repository). It is stored only in the server's private environment file. It must be treated as exposed. | **Needs you:** rotate it and set a spend limit on the OpenAI side (see section 5). The platform's own $0.05/month cap protects spend through the app, not the key itself. |
| S2 | P2 | Content-Security-Policy is a safe subset only (no `script-src`/`connect-src`/`frame-src`): an injected script could call any site. | **Mitigated in code, not enforced.** Added the full policy as `Content-Security-Policy-Report-Only` (cannot block anything). Survey of 21 pages (15 signed-in, 6 public) on the local build: **nothing would be blocked.** Not exercised: Razorpay/Cashfree checkout, Facebook SDK (WhatsApp connect), which need a test payment / live connect. `script-src` still needs `'unsafe-inline'` until nonces are added. |
| S3 | P2 | A customer-facing message told the owner the name of the server setting (`OPENROUTER_API_KEY`). Harmless but leaks configuration detail and is wrong now. | **Fixed** in the assistant page. |
| S4 | P2 | No two-factor authentication for platform-admin (operator) accounts. | **Open.** Larger feature; recommended before more operators are added. |
| S5 | P2 | Background tasks had **no time limit**: one hung network call would hold one of the two worker slots for ever. | **Fixed** (see section 4). |
| S6 | P3 | Unused credentials are present in the production environment file (an unused Gemini key and an expired OpenRouter key). | **Needs you:** remove them; no code reads them (the provider choice has no fallback, tested). |
| S7 | P3 | Error reporting (Sentry) is not configured, so server errors are not collected anywhere central. | **Blocked on you:** a Sentry DSN (or a choice of GlitchTip). |
| S8 | P3 | Unknown paths on the API host answer `200 "FlowQR API"` instead of 404. | Open, cosmetic. |
| S9 | P3 | The public `/privacy` page shifts (CLS 0.22) when the legal-info request returns (see section 3). | Open. |

No critical or high vulnerability (data exposure across businesses, secret exposure, authentication bypass) was found. That is a statement about what these checks cover, not a guarantee: no authenticated penetration test was run against production (not authorised), and Google-side and payment-side live behaviour was not tested.

---

## 2. Backend health

- **Database access.** Forced RLS on every tenant table (verified functionally, above). Index use checked with `EXPLAIN ANALYZE` on the dashboard filters at realistic volume (audit log 6,000 rows, metrics 13,140 rows, reviews 900): audit log, metrics and review lists use their indexes; no missing index found. Table scans that remain are on tiny tables (tenants, users, sessions: ≤ 41 rows), which Postgres correctly prefers to scan.
- **N+1 queries (two found and fixed).** `/posts` ran one query per post for the location name (110 SQL statements for 100 posts); `/reviews` ran one query per review for its drafts (30 statements for 20 reviews). Both now batch (10 and 11 statements). Detail in section 4.
- **Still heavy but acceptable:** `/analytics/overview` runs 31 statements (27 distinct) at ~97 ms p50 on the benchmark data. It is the next candidate if the dashboard feels slow; it was **not** changed because the gain is unproven and it feeds money-related numbers.
- **Workers.** Celery: acks-late, prefetch 1, concurrency 2, ~31 scheduled tasks. Now with time limits and process recycling (section 4). Reviewed that tasks are idempotent-by-state (publish/recover-stuck patterns, retry counters); an earlier, separate hardening branch (`hardening/production-readiness-audit`, local only, not merged) fixed a stuck-sync and a held-post starvation bug; those fixes are not part of this branch.
- **Server headroom (read-only).** The API container was at ~79% of its memory limit at the time of the check. Not changed (needs a deployment change you approve). Recommendation in section 7.
- **Caching.** None added. The measured wins came from removing query waste; a cache keyed per business/permission would add staleness and leak risk for no measured need. Nothing private is cached under a shared key anywhere.

---

## 3. Frontend performance

Measured on a local production build (`next build` + `next start`), real Chrome, 11 signed-in pages × 6 widths (320, 360, 375, 390, 414, 768 px) = 66 page loads per run, plus public pages and a throttled profile. The test PC's antivirus injects its own 178 kB script into every page; it is **excluded** from all figures below.

**Bundle sizes (from the build, gzip).** Shared JS for every page: **103 kB**. Heaviest first loads: `/admin/cards` 236 kB, `/gbp/cards` 228 kB, `/seo`, `/seo/performance`, `/pricing` 198 kB, `/` 190 kB, `/overview` 187 kB. Typical app page 160–190 kB. No page is over 240 kB.

**Cold first visit, 390 px (empty cache):** `/overview` 543 kB over the wire (395 kB JS, 40 kB fonts), of which ~100 kB are route chunks Next prefetches for the six nearest menu links. The next pages reuse the cache (`/gbp/reviews` 69 kB, `/seo` 86 kB, `/gbp/posts` 115 kB).

**Unthrottled, local server (not a phone):** median LCP ≈ 0.59 s, max 1.1 s after the changes; CLS ≈ 0 on most pages.

**Throttled (CPU ×4, 1.6 Mbps, 150 ms latency — a mid-range phone on a weak network, 360 px):**

| Page | LCP | Main-thread blocked (long tasks) | Layout shift |
|---|---:|---:|---:|
| `/overview` | 4.6 s | 2.4 s | 0.165 |
| `/gbp/reviews` | 3.5 s | 2.0 s | 0 |
| `/gbp/posts` | 4.8 s | 1.8 s | 0 |
| `/seo` | 3.8 s | 2.0 s | 0.133 |
| `/settings/billing` | 4.0 s | 2.0 s | 0 |

This is the honest mobile weak point: on a slow phone the app takes 3.5–5 s to show its main content, and ~2 s of that is JavaScript running. Real-device and field (RUM) numbers were **not measured**; this is a lab emulation. See section 7.

**Fixes with before → after (same method, same data):** see section 4 and `audit/results/frontend-summary.md`.

**Public pages (360 px, cold):** `/login` 385 kB (260 kB JS), `/register` 39 kB, `/pricing` 226 kB (133 kB fonts), `/` 401 kB (118 kB images). `/privacy` shows a layout shift of 0.22 (the text changes when the legal-info request returns); recommended fix is to render the company details on the server (kept out of this change because hiding the text until it loads would remove it from the HTML that Google's reviewers and crawlers read).

**Mobile layout (320/360/375/390/414/768):** no page scrolls sideways after the fixes (one did before); tap targets: the three text buttons under 32 px were made 44 px on phones. What remains under 32 px are screen-reader skip links and 18 px radio buttons inside larger labels.

---

## 4. Fixes implemented (all on the working branch, none deployed)

| Fix | Files | Result |
|---|---|---|
| `/posts` N+1 (location titles looked up once per page) | `backend/app/api/v1/posts.py`, `marketing.py` | 110 → 10 SQL statements, p50 298.6 → 53.7 ms |
| `/reviews` N+1 (drafts loaded in one extra query) | `backend/app/api/v1/reviews.py` | 30 → 11 SQL, p50 113.8 → 37.4 ms |
| Worker time limits: soft 15 min, hard 20 min; recycle a worker process after 200 tasks | `backend/app/workers/celery_app.py`, test `test_worker_limits.py` | one hung task can no longer hold a worker slot for ever |
| Identical GET requests made at the same moment share one request (no cache; writes clear it; calls with an abort signal or custom headers are never joined) | `frontend/src/lib/api.ts`, new `lib/inflight.ts`, `tests/inflight.test.mjs` | API calls per page at 360 px: `/settings/team` 17 → 12, `/settings/billing` 19 → 15, `/overview` 25 → 23, `/gbp/reviews` 16 → 14; 0 identical duplicate requests left on the 11 pages |
| Billing page: three plan cards were squeezed to ~87 px each at tablet width because the app menus take ~430 px; the page was 14 px wider than the screen | `components/billing/BillingPlans.tsx` | three-column layout now from 1100 px, otherwise the one-plan switcher phones already use; overflow gone |
| Billing page layout shift 0.181 (loading skeleton was 128 px, real card 272–522 px) | `settings/billing/page.tsx` | 0.181 → 0.001 |
| Campaigns row ("Send link / Poster / PNG") ran 16 px off-screen at 360 px | `gbp/campaigns/page.tsx`, `PlanTile.tsx` (text now wraps) | fixed |
| Tap targets under 32 px on phones ("Open Studio", chart "Table", "Edit goal") | `Marketing.tsx`, `AreaChart.tsx`, `Bars.tsx`, `growth/page.tsx` | 44 px on phones |
| Owner-facing text no longer names a server setting | `reputation/assistant/page.tsx` | S3 |
| Report-only full Content-Security-Policy | `frontend/next.config.mjs` | S2 |
| New security tests (secret sweep, RLS filters, worker limits) | `backend/tests/` | section 8 |
| Stale tests repaired: 14 migration tests hard-coded the head as `0067` (it is `0069` since the Marketing Studio and review-limit migrations); they now read the head from the scripts. One retention test used the local date while the app uses UTC, so it failed between 00:00 and 05:30 IST. | `tests/conftest.py` + 12 test files | these were test debt, not product bugs |

### Benchmarks (backend, local, 41 businesses; the busy one has 900 reviews, 13,140 metric rows, 300 posts, 6,000 audit rows; 25 timed requests per endpoint after a warm-up; "after" is the median of three full runs)

| Endpoint | p50 before (ms) | p50 after (ms) | change | p95 before | p95 after | SQL before | SQL after |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/posts` | 298.6 | 53.7 | **5.6×** | 396.4 | 71.0 | 110 | 10 |
| `/reviews` | 113.8 | 37.4 | **3.0×** | 137.5 | 55.7 | 30 | 11 |
| `/analytics/overview` | 108.6 | 96.5 | unchanged | 122.7 | 155.2 | 31 | 31 |
| `/analytics/google-metrics` | 81.5 | 69.4 | unchanged | 97.4 | 101.3 | 14 | 14 |
| `/agent/activity` | 63.6 | 60.5 | unchanged | 142.4 | 88.2 | 19 | 19 |
| every other endpoint | see `audit/results/benchmark-summary.md` | | unchanged | | | | |

**Noise floor:** endpoints I did not touch moved between 0.7× and 1.7× between runs, so only the `/posts` and `/reviews` changes (and the SQL-statement counts, which are exact) are real. I did not claim any other speedup.

### Frontend before → after (local build, 66 page loads each)

| | before | after |
|---|---:|---:|
| Pages that scroll sideways | 1 (billing at 768 px) | **0** |
| Page loads with layout shift > 0.1 | 7 of 66 | 2 of 66 (`/overview` 375 px 0.133, `/gbp/reviews` 320 px 0.104; intermittent) |
| API calls, all 11 pages at 360 px | 158 | 141 |
| Identical duplicate GETs on the 11 pages | several per page (e.g. locations ×3, google status ×3) | 0 |

Per-page table: `audit/results/frontend-summary.md`.

---

## 5. Credential rotation (no values shown)

| Service | Variable | Action |
|---|---|---|
| OpenAI | `OPENAI_COMPAT_API_KEY` | **Rotate** (pasted in chat), then set a monthly spend limit in the OpenAI dashboard. Update only the server environment file and restart `api` and `worker`. |
| Google Gemini | `GEMINI_API_KEY` | Unused: remove from the server environment file. |
| OpenRouter | `OPENROUTER_API_KEY` | Expired and unused: remove. |
| Sentry | `SENTRY_DSN` | Not set: needs a DSN from you. |

Nothing else shows signs of exposure (browser, history, API responses all clean), so no other rotation is indicated by this audit. Nothing was rotated or changed in production.

---

## 6. Remaining vulnerabilities and gaps

1. S1: pasted OpenAI key (needs rotation by you).
2. S2: CSP not enforced; `script-src` needs nonces for a strong policy.
3. S4: no two-factor authentication for operator accounts.
4. S7: no central error reporting.
5. Not tested at all (blocked or not authorised): authenticated penetration test and fuzzing against production; load testing; live Google API behaviour (writes were never proven live); real payment with Razorpay/Cashfree; WhatsApp/Facebook connect; real-device mobile performance; dependency vulnerability scanning (`npm audit` / `pip-audit` were not run in this session; run them before release).
6. Operational gates from earlier audits remain yours: off-site backup copy, lawyer review of the legal drafts, Google policy answers.

---

## 7. Production recommendations (priority order)

- **P0 (you):** rotate the OpenAI key and set its spend limit (S1).
- **P1:** supply a Sentry DSN so errors are collected; then run the existing preflight check.
- **P1:** raise the API container memory limit (it sat at ~79%); needs a deployment-file change.
- **P2:** deploy this branch (below), then watch worker logs for `SoftTimeLimitExceeded` for a few days (a task that legitimately needs more than 15 minutes would show up there).
- **P2:** enforce the CSP once the report-only console is clean during a test payment and a WhatsApp connect; then add nonces and drop `'unsafe-inline'`.
- **P2:** mobile speed. The lever is main-thread JavaScript (~2 s on a throttled phone): lazy-load the chart code and the start-up animation, and trim the six menu-link prefetches on mobile. Measure on a real mid-range phone first.
- **P3:** two-factor authentication for operators; render legal-page company details on the server; the `/analytics/overview` query count if the dashboard feels slow.

**Deploying this branch (needs your explicit go-ahead):** no migration and no environment variable change. Backend: normal image build and `up -d --no-deps api worker beat` with both compose files. Frontend: Vercel deploy. Rollback: the previous tag/deployment named at the top. The CSP header is report-only and the request sharing is behind no flag; both are small and reversible.

---

## 8. Test results

Run locally on Windows, Python 3.12, PostgreSQL in a container, Redis intentionally unavailable (tests use the in-memory limiter), Google as a test double.

| Suite | Result |
|---|---|
| Whole backend suite (≈3,700 tests), in two runs | **3,672 passed, 20 failed on first sight**: 14 migration tests with a stale hard-coded head (`0067`; real head `0069`), 1 retention test and 1 QR-inventory test that used the local date while the app uses UTC (fail between 00:00 and 05:30 IST), 1 `/review-growth/campaigns` test that did not expect the default campaign added earlier, 1 WhatsApp migration test (stale head), 1 `test_ops` timing test (Windows' 15 ms clock tick), 1 `test_qr_assets` test (Windows-only, see below). The first run stopped at 15 failures, so the files after `test_migration_0067` were run separately (2,430 passed, 5 failed). **All five of the second run's failures were reproduced on a clean checkout of the branch's last commit (`a7fc72a`): none were caused by this audit's changes.** |
| After repairing those tests | The 19 repairable ones **pass** (re-run: 100 + 140 tests). **1 still fails: `test_qr_assets::test_the_check_endpoint_validates_without_saving_or_fetching`.** It forbids any socket `connect` to prove the server never fetches an admin-supplied address; on Windows the asyncio event loop itself uses `connect` to build its internal socket pair, so it trips before reaching the app code. Not verified on Linux here (expected to pass there; run it on CI/Linux before release). |
| New tests for this audit | `test_no_secrets_in_responses.py` 3 passed · `test_rls_filters_every_tenant_table.py` 2 passed · `test_worker_limits.py` 2 passed · frontend `inflight.test.mjs` 5 passed |
| After the N+1 changes: handlers' own suites | post publishing, Marketing Studio, Google and reviews, hardening isolation, route-access audit, secrets sweep, RLS sweep, AI text-only: **93 passed** |
| Frontend unit tests | **165 passed, 0 failed** |
| Frontend type check (`tsc --noEmit`) | clean |
| Frontend production build | succeeded (4 builds during the audit) |
| Browser measurements | 66 page loads per run, 6 widths, 11 pages; public pages; throttled profile; CSP survey of 21 pages (raw JSON in `audit/results/`) |

**Blocked / not run:** production penetration test, load test, fuzzing (not authorised); live Google writes; real Razorpay/Cashfree payment; WhatsApp/Facebook connect; real-device and field performance; `npm audit` / `pip-audit`; Lighthouse (no network-throttled field data; the lab throttling in section 3 is the substitute); the end-to-end script `e2e/review-onetap-journey.js` was updated earlier in the session but never run.

---

## 9. Final readiness assessment

| Dimension | Assessment | Why |
|---|---|---|
| **Security** | **Ready, with two owner actions.** No data-exposure, secret-exposure or isolation defect found; isolation proven at both the API and database level; detectors self-tested. Before wider launch: rotate the pasted key (S1), add operator 2FA (S4), enforce CSP (S2). Not covered: production penetration test, live payment/Google behaviour. | measured above |
| **Backend reliability** | **Ready.** Two real N+1 problems fixed with measured gains; worker tasks can no longer hang a slot; indexes adequate at the tested volume. Watch memory headroom and add error reporting. Not covered: load test, production-scale data. | benchmarks, tests |
| **Frontend performance** | **Acceptable on a normal connection, weak on a slow phone.** Bundles are moderate (103 kB shared; ≤ 240 kB per page), requests de-duplicated, layout stable. Throttled mid-range-phone emulation shows 3.5–5 s to main content. | section 3 |
| **Mobile performance** | **Layout: ready. Speed: needs work.** No sideways scrolling at six widths on 11 pages, tap targets fixed, tablet billing layout fixed. Speed on slow phones is the open item; no real-device data yet. | section 3 |
| **Deployment readiness** | **Ready to deploy on your word.** Nothing was pushed, deployed, or changed in production; no migration; no env change. | section 7 |
