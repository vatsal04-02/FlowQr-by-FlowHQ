# FlowQR production-readiness audit and hardening

Date: 2026-11-22. Branch: `hardening/production-readiness-audit` (local only: not pushed, not merged, not deployed). Based on `origin/release/gbp-agency` at `0604555`.
Companion files: `PRODUCTION_TEST_MATRIX.md` (every check with a result), `PRODUCTION_DEPLOYMENT_RUNBOOK.md` (release, rollback, recovery), `docs/evidence/production-audit-2026-11-22/` (raw outputs).
WhatsApp was out of scope: its code, configuration, templates and webhooks were not changed, and nothing about it is claimed here.

## 1. Verdict

**Ready for a controlled production release of the code in this branch. Not ready to be called complete for the agency path or for off-site disaster recovery**, because those depend on things only people can do (section 8).

* The application is in good shape. The full backend suite (3,445 tests) passes on Linux, the frontend type-checks, tests and builds, and 40 real-browser checks plus a 21-check worker/beat run pass. Tenant isolation held under a 45-request attack sweep.
* The audit found and fixed **6 defects** (2 at P1, 2 at P2, 2 at P3), none of which changes the database, an environment variable or a dependency.
* **Nothing real was verified against Google, Cashfree, an AI provider, a mailbox or the production servers' insides.** Every "PASS" about those is against a test double and is labelled so. The matrix marks them BLOCKED or NOT TESTED, not PASS.

## 2. What was done, and the safety limits kept

Read the repository (backend: 45 API modules and 486 routes in the access manifest, 62 migrations in one chain with head 0065, 31 Celery schedules; frontend: 115 pages), established a baseline, wrote reproductions before fixes, fixed causes, added regression tests, re-ran everything.

| Rule from the brief | How it was kept |
|---|---|
| No destructive tests on customer data; no fake production records | All state-changing work used a throwaway PostgreSQL and Redis in Docker, local API, local frontend. Nothing was written to production. |
| No real Google, Cashfree, WhatsApp; no real charges | Google was a file-driven test double. Cashfree and AI were covered by the repository's mocked tests only. WhatsApp untouched. |
| Only read-only contact with production | Plain public GETs (health, readiness, redirects, headers, certificate dates): `docs/evidence/.../production-public-readonly-checks.txt`. No login, no ssh, no database access, no card token. |
| No deploy, no merge, no production migration, no push | None done. The branch exists only in a local git worktree. |
| Never print secrets | Evidence files were scanned; the only "secret-like" match is the URL `/forgot-password`. Backup rehearsal used a throwaway passphrase file. |

## 3. The production context in the brief, checked

| Statement in the brief | Status |
|---|---|
| Backend branch `release/gbp-agency`, latest commit `6dc3739` | **Differs.** `origin/release/gbp-agency` is now `0604555`: `6dc3739` plus 11 marketing-site commits that change only the home hero (5 frontend files, no backend). Which frontend build is live on Vercel was not checked. |
| Backend image `prod-10bcbbe` | Not verifiable from outside. `10bcbbe` is an ancestor of `6dc3739` ("Data export includes the agency tenant grant list"), so it is consistent. |
| Migration `0065` | **Confirmed in code** (head, applies cleanly to an empty database, tested). Production's own revision is reported by `/api/ready`: `{"ready":true,"checks":{"database":"ok","redis":"ok","migrations":"ok"}}`, which means the database is at the head the running image expects. |
| API, worker, beat healthy; both customer locations synced | API and readiness: **confirmed** (public GETs). Worker, beat and the two syncs: **not verified by me** (needs a shell or the admin Operations page). |
| Operator `vatsal@flowhq.co.in` allowlisted but not registered; no grant, no consent; internal-only on | Not verifiable without database access. Public facts that agree: registration mode is `allowlist`; `GET /api/v1/agency-ops/tenants` answers 401 without a login. |
| Off-site backup implemented and tested, destination not configured | **Confirmed as a mechanism** (section 5, "Backup"); the destination remains unconfigured by design. |
| Public third-party agency access gated on Google's written clarification | Enforced in code and covered by tests (`operations_enabled`, config guard). Google's answer is not something that can be verified from a repository. |

## 4. Feature inventory

"Verified" means what was actually run. "Mocked" means a repository test double stood in for the external service. The full list of checks is in the matrix.

| # | Feature | Frontend entry | Backend | Data | External | Verified status |
|---|---|---|---|---|---|---|
| 1 | Register, verify e-mail, log in/out, reset password, change password | `/register` `/login` `/verify-email` `/forgot-password` `/reset-password` | `api/v1/auth.py` | users, auth_sessions, verification and reset tokens, registration_allowlist | SMTP | Browser (register, verify, wizard) and about 100 backend tests across the auth, security and account files. Real mail delivery: not tested. |
| 2 | Registration gate (closed, allowlist, open) | register page | `services/registration.py` | registration_allowlist | none | Backend tests; production mode read as `allowlist`. |
| 3 | Continue with Google (sign-in) | login/register | `auth_google.py`, `google/login.py` | users | Google OIDC | Mocked only. |
| 4 | Onboarding and tenant creation | `/onboarding` (4 steps) | `tenants.py`, `provisioning.py` | tenants, subscriptions, locations | none | **Browser PASS**, including inline validation and a 7-day no-card trial. |
| 5 | Team, roles, location-limited staff | `/settings/team` | `tenants.py`, `deps.py` | memberships, membership_locations, invitations | SMTP | Backend tests; routes in the access manifest. |
| 6 | Customer dashboard (Home, Growth score, Reports) | `/overview` `/growth*` | `analytics.py`, `growth_score.py` | reviews, scan_events, review_events | none | Browser sweep; numbers compared with the database (section 6, F-07 check). |
| 7 | Business admin console (FlowHQ staff) | `/admin/*` | `admin*.py` | everything, under RLS bypass | none | **Browser sweep, 12 screens x 3 viewports**; owner is shown "Platform admins only" and gets 403 from its APIs. |
| 8 | Operator access (agency) | **none** | `agency_ops.py`, CLI `google-agency-grant` | google_agency_tenant_grants | none | Backend: 13 existing tests plus 6 new. **There is no screen for it** (section 7, O-1). |
| 9 | Google owner OAuth | `/gbp/locations` | `api/v1/google.py`, `google/tokens.py` | google_connections (Fernet-encrypted tokens) | Google OAuth | Mocked, through the real API, worker and beat. Live: not tested. |
| 10 | Account and location discovery, mapping | `/gbp/locations` | `google.py discover_locations` | google_locations | Business Profile API | Mocked. |
| 11 | Review sync | `/gbp/reviews` | `google/sync.py`, `workers/tasks.py` | reviews | Business Profile API | Mocked, real worker + beat (21/21). **F-01 fixed here.** |
| 12 | Review management, filters, details | `/gbp/reviews` | `reviews.py` | reviews, reply_drafts | none | Backend tests; browser sweep. |
| 13 | AI-assisted replies (draft, approve, publish) | review detail | `reviews.py`, `services/ai/*`, `agent/content_exec.py` | reply_drafts, reply_logs | AI provider, Google | Mocked provider. Draft never publishes itself. **F-06 fixed here.** |
| 14 | Template auto-replies to positive reviews | `/settings/ai/*` | `auto_reply.py` | agent_* | Google | Backend tests (no AI writes the text). |
| 15 | QR campaigns (create, edit, pause, archive, regenerate) | `/gbp/campaigns` | `review_growth.py` | review_campaigns | none | **Browser PASS.** **F-03 fixed here.** |
| 16 | QR generation and download (PNG, SVG, PDF poster) | campaign page | `services/qr.py`, `qr_style.py` | qr styles | none | **Browser PASS**: PNG and SVG decoded back to the exact address. |
| 17 | Public review page and feedback topics | `/r/{id}` `/q/{token}` `/n/{token}` | `review_public.py`, `public.py` | review_sessions, review_events | AI (optional) | **Browser PASS on a phone**, English and Hindi, empty, invalid and paused states. |
| 18 | NFC and permanent print redirect | `/n/{token}`, `go.flowqr.site` | `go.py` | qr_cards | none | **Browser and API PASS**: 302, no-store, QR and NFC doors, unknown token 404, no open redirect. |
| 19 | Physical card inventory | `/gbp/cards`, admin | `cards.py`, `admin.py` | card_batches, qr_cards | none | Browser (issue, assign, pause). |
| 20 | Analytics and reports | dashboard, `/growth/reports` | `analytics.py`, `reports.py` | derived | none | New test against the database at the India midnight boundary. |
| 21 | Billing: plans, checkout, subscription, webhooks | `/settings/billing` | `billing.py`, `webhooks.py`, `cashfree.py`, `prepaid.py` | subscriptions, payments, webhook events | Cashfree | Mocked: about 200 existing tests across the Cashfree, prepaid and billing files (signature, stale timestamp, duplicate, ordering, cross-tenant, reconciliation). Sandbox: blocked. |
| 22 | Background jobs | worker, beat | `workers/*` | many | Redis | **Real worker and beat run** (section 6). |
| 23 | Agency Manager (client consent, status, stop) | `/gbp/locations` panel | `google_agency.py`, `google/agency*.py` | google_agency_* | Google | Backend tests (about 260). Live: blocked. **F-05 fixed here.** |
| 24 | Privacy: export, deletion, retention | `/settings/account` | `account.py`, `google_retention.py` | many | none | Backend tests. |
| 25 | Website builder, SEO, rank tracking, posts, photos | `/seo` `/gbp/posts` `/gbp/photos` | `sites/*`, `rank*.py`, `posts.py`, `photos.py` | many | Cloudflare, Google | Backend tests. **F-02 fixed here.** Sites were reported off in production. |
| 26 | Health, readiness, monitoring, backup | `/admin/ops` | `main.py`, `ops.py`, `deploy/*.sh` | status files | Sentry, off-site store | Local rehearsal PASS; production destination blocked. |

## 5. Test coverage and baseline

| Area | Result |
|---|---|
| Backend, Linux, Python 3.13 (the production Python), full repo mounted, 8 shards, final tree | **3,445 passed, 0 failed, 0 skipped**. The `flowqr-test` image predates the current `requirements.txt` (PyJWT 2.10.1 instead of the pinned 2.15.1, no `sentry-sdk`), so this run did not use the exact production dependency set. The Windows run (Python 3.12) did, and passed except the three artefacts below, but it was the baseline taken before the fixes. Neither run is a build of the production Dockerfile; nothing in this change touches the Dockerfile or `requirements.txt`. |
| Backend baseline before any change (Windows) | 3,424 passed, 3 failed. All three are Windows artefacts and pass on Linux: `test_ops` (the Windows clock is coarse, one tick in 2,000 consecutive reads here, so a "later" event can share a timestamp), `test_qr_assets` (asyncio self-pipe socket is blocked by the test's no-network guard), `test_admin` payments (depends on which tests share a database: passes alone, passes in the final run). |
| Migrations | All 62 revisions apply to an empty database in one linear chain, single head `0065` (ids 0034, 0038 and 0039 do not exist on purpose; see `docs/MIGRATION_RECONCILIATION.md`); a restored backup also reports `0065`, 118 tables, 96 RLS policies |
| Frontend | `tsc --noEmit` 0 errors; 131 of 131 unit tests; `next build` clean with no warnings; `npm audit --omit=dev` 0 vulnerabilities |
| Browser (Chromium, real UI) | **40 of 40** checks; **111** app and public page loads and **36** admin page loads at desktop, tablet and phone: no crash, page error, broken image, failed request, sideways scroll or unlabeled control |
| Worker and beat, real Celery and Redis, mock Google | **21 of 21** checks |
| New regression tests | 23 backend tests in 5 files, 3 frontend guards, 1 browser script, 1 worker script |

## 6. Findings

Severity follows the brief: P0 data loss/security/cross-tenant/outage, P1 broken critical feature, P2 non-critical defect, P3 polish.

| ID | Sev | Finding | Root cause | Fix | Regression test |
|---|---|---|---|---|---|
| F-01 | **P1** | A location's sync could stay on "running" forever with no failure counted and no back-off. The same location was re-queued and failed again every 15 minutes (3 Celery retries each time) while the dashboard and operations page showed nothing wrong. | `sync_google_location` committed "running", then only caught Google API errors. A review in a shape FlowQR could not parse (reproduced with a malformed timestamp) raised past it. | Unexpected errors are logged with traceback, stored as a plain-sentence error, counted and backed off. `GoogleNotConfigured` still propagates. | `test_hardening_sync.py` (5). Also proven through the real worker: status `error`, failures 2, back-off set, then automatic recovery with no duplicate. |
| F-02 | **P1** | Scheduled posts and photos of one business could stop every other business's from publishing. | The job fetched the oldest five due rows, then dropped the ones it had already looked at **in Python**. A business that is suspended or deleting keeps its due posts `scheduled`; with five or more, the batch was always "already seen" and the loop ended. | `due()` takes the ids already inspected and excludes them in the query; a run inspects up to 500 items and still sends at most 40 posts or 20 photos. | `test_hardening_scheduling.py` (2): 7 held posts of a suspended business, a healthy business's post still publishes, the held ones publish on the very next run once reinstated, each exactly once. **A first attempt (parking held items for 10 minutes) broke an existing test about reinstatement; the full suite caught it and it was replaced, not the test.** |
| F-03 | P2 | Filling the New campaign dialog threw React error #185 ("Maximum update depth exceeded") three times per use. The campaign was still created, but any other form with blur validation had the same fault. | `useForm`'s blur handler called `setErrors` inside a `setValues` updater, which must be pure. | Validate outside the updater from the latest values, set state only when the message changes. | `form-hook.test.mjs` (3; fails on the old code, passes on the fix) and the browser journey (zero page errors). |
| F-04 | P3 | The campaign page had two `main` landmarks and two `h1` titles. | The embedded customer-page preview rendered its own. | Preview renders neutral elements. | Browser check (exactly one of each). |
| F-05 | P3 | Every customer's browser made a request that is known to fail (`/google/agency/status` answers 404 by design) on every visit to Locations, logged as a console error. | The agency panel always asked. | `/google/status` returns `agency_available` (a bare yes/no); the panel asks only when true. The 404 contract is unchanged. | `test_hardening_agency_visibility.py` (4); browser sweep has no HTTP error. |
| F-06 | P2 | A reply of only spaces was saved as an empty draft that could then be approved and sent toward Google. | The length rule counted spaces. | Strip first, require real text. | `test_hardening_operator_and_data.py` (blank create and edit refused). |

A seventh change corrects a message I introduced and then reconsidered: the F-01 error said "FlowQR has been told", which is only true when error reporting is configured. It now says only what is certain.

### Checks that found nothing wrong (so they can be trusted)

* **Cross-tenant attack sweep** (`test_hardening_isolation.py`): a second business, a valid administrator of its own business, sent 45 requests across GET, POST, PATCH, PUT and DELETE to every id-based route (locations, reviews, drafts, campaigns, QR and poster files, Google connections and profiles, posts, staff, agency and operator routes) with the victim's real ids. All refused (never 2xx), nothing of the victim echoed, victim data identical afterwards. A guard test proves the same ids work for their owner, so the sweep cannot pass by using wrong routes. The `X-Tenant-Id` header cannot select a foreign business (403), nor a malformed one (400).
* **Operator access** (`test_hardening_operator_and_data.py`, 6 tests): refused with the same 404 as an unknown path when unverified, signed out, deactivated or removed from the list; the list is read per request (no restart); CSRF and input validation hold; every grant and revoke is audited with the signed-in operator; an operator has no access to a customer's data and cannot record consent for one.
* **Dashboard numbers vs the database**, at the 23:59:59 and 00:00:00 India time boundary, all-time totals, rating distribution, reply rate, empty ranges (no data is `null`, never 0 stars), and a second business seeing none of it.
* **Live API probes** (local): an evil origin's preflight is refused and the site origin accepted; protected routes answer 401 without a session; login is rate-limited (429 once one address has made 10 attempts in a minute); injection-style tokens are 404; security headers present; API docs exist only outside hardened mode (production answers 404).
* **Mass assignment**: every `setattr` loop over a request body was read; the input schemas contain no privileged fields.
* **Edges with timeouts**: every outbound HTTP client has a timeout; a Google 5xx is retried 1, 2, 4 seconds in-request and then backed off 5 minutes to 6 hours.
* **Backup**: see O-3 and the matrix. The real scripts ran end to end on a throwaway database: redacted, AES-256 encrypted, sha256 recorded, read back from the "off-site" folder and compared, restored into a throwaway container (118 tables, migration 0065, 96 RLS policies, row counts equal). A corrupted copy is rejected.
* **Worker and beat**: beat to worker heartbeat 3 to 12 s old; a scheduled sync picked up an edited and a new review without anyone pressing Sync (61 to 81 s); a Google outage for one business left another business syncing; revoked access shown as "Reconnect"; no duplicates through 2-page responses that repeat an item.

## 7. Remaining observations (not fixed)

| ID | Sev | Observation | Why not fixed | Suggested action |
|---|---|---|---|---|
| O-1 | P2, product decision (**deferred to a separate milestone by the owner; agency stays internal-only**) | **No screen for the operator endpoints.** Operators work through the CLI (needs a shell on the server) or the raw API with a signed-in session and CSRF header. The brief asks for "frontend route protection" for operators; there is no frontend to protect. | The brief says not to invent features. | Decide whether an operator page is wanted. Until then the runbook's CLI steps are the supported path. |
| O-2 | design note | When Google fails, the Celery task reports **succeeded** with `status: error` in its result. The failure is real and visible (row status, `check_failed_work`, notifications) but a "task succeeded" log line next to it can mislead. | Deliberate: failures are stored as state so Celery retry storms do not multiply Google calls. | Keep; rely on the Operations page, not worker logs. |
| O-3 | P3 | Backup encryption is `openssl enc` AES-256-CBC with PBKDF2: confidential but **not authenticated**. Integrity rests on `gzip -t`, the sha256 file and the restore check (each of the three refused a flipped byte: `gzip -t`, the sha256 check and `verify-restore.sh`, see the evidence file). | Replacing the tool changes the backup format and the restore path. | Consider an authenticated format (for example age). Not urgent. |
| O-4 | P3 (**deferred by the owner: investigate with real query plans, separately; no migration 0066 now**) | **134 of 266 foreign keys have no leading index.** On growing tables this includes `reviews.location_id`, `scan_events.location_id` and `campaign_id`, `review_events.session_id` and `location_id`, `audit_logs.user_id`, `ai_generation_logs.location_id`, `reply_logs.draft_id`, `google_locations.connection_id`. It costs nothing until a parent row (a location, campaign, tenant or user) is deleted or listed by that column. | It is a production schema change and the data is small today. | One reviewed migration `0066` creating these indexes `CONCURRENTLY` before the customer count grows. Needs your approval. |
| O-5 | P3 test hygiene | `test_admin::test_admin_sees_payments_separately...` asserts a global empty list, so it depends on which tests share a database. | Pre-existing; the assertion is not mine to loosen. | Scope the query to the test's own tenant. |
| O-6 | P2 for a small customer base | Production error reporting (Sentry) was reported as not configured in the repository's own readiness notes; **still unverified** (a read-only look was denied, 2026-11-23). The variable does reach the containers. Separately, **alerting is too quiet**: failed syncs are only a warning until 10 items fail, and e-mails and the Sentry message fire only for critical, so a customer's location that cannot sync alerts nobody. The alert job also runs inside the stack it watches. | Verifying needs the status script run by you; the grading change is a code change outside this candidate. | Set a DSN, add an external uptime monitor on `/api/ready`, grade a location in error for over 6 hours (or a revoked connection) as critical, confirm an alert e-mail arrives. See `RELEASE_CANDIDATE.md` section 5. |
| O-7 | info | Browser coverage is Chromium emulation of phone and tablet. Safari/WebKit, Firefox and real devices were not run. Accessibility was checked for names, landmarks and sideways scroll, not contrast or a screen reader. | Out of reach here. | One pass on a real iPhone and Android before wide launch. |
| O-8 | info | No load test and no query-count (N+1) measurement was done. | Out of scope for the time available. | Before a large onboarding wave. |

## 8. What needs a person (external gates), none marked complete

1. **Operator registration and verification.** The allowlisted operator address must register at the sign-up page and verify the mailbox (a mail the server sends). Until then agency operations cannot be started from the app, which is the safe state.
2. **Real client consent.** A business's own administrator must press agree. No consent exists and none was or can be fabricated.
3. **Agency sync with a genuinely authorised client.** Follows 1 and 2, with the operator opening the path for that business first.
4. **Off-site backup destination and credentials** (`BACKUP_REMOTE`, plus the passphrase kept off the server). Until then `status.json` shows `offsite:false` and disaster recovery is not complete.
5. **Google's written answer on third-party agency use.** Public access stays disabled and the internal-only rule stays on.
6. **Live Google check** on an authorised account: the repository's read-only `google-smoke` command is the supported way; it was not run because it needs production credentials.
7. **Cashfree sandbox or live-small-amount check** with credentials you hold; webhook signature validation was not weakened in any way.
8. **Mailbox delivery check** (registration, verification, password reset, invitations) with the production SMTP.
9. **Decisions:** operator screen (O-1), the index migration (O-4), Sentry (O-6).

## 9. Definition of production-ready (brief, section 17), item by item

| Criterion | Met? | Evidence or reason |
|---|---|---|
| Every in-scope feature inventoried | Yes | Section 4 and the matrix. |
| Critical journeys pass | Partly | 1, 4, 5, 8, 9 pass on the local stack; 2 and 6 with a test double only; 3 and 7 mocked; live external parts blocked. |
| P0 and P1 defects resolved | Yes | No P0 found. P1: F-01, F-02 fixed and re-proven. |
| Frontend and backend builds pass | Yes | Section 5. |
| Migrations consistent | Yes | 62-revision chain applies to an empty database, single head, and a restore at 0065. No new migration. |
| Google owner OAuth works | **Not shown live** | Works against the test double through the real API, worker and beat. The brief's "both locations synced" is the production report's claim, not mine. |
| Google Business Profile works for authorised accounts | **Not shown live** | Same. |
| Agency Manager authorization enforced | Yes (code and tests) | Operator, grant, consent, revoke, resolution and isolation tests; 404 for everyone not entitled. Live activation: pending (section 8). |
| Tenant isolation verified | Yes | RLS (96 policies), 45-request attack sweep, header tests. |
| Existing scheduled syncs healthy | **Not verified by me** | Production worker and beat not inspected. Locally healthy. |
| QR and NFC work | Yes | Browser and API, section 6. |
| AI behaves safely | Yes against test doubles | Drafts never publish themselves; a blank reply cannot be saved; flagged reviews need acknowledgement. Live provider not run. |
| Billing works in sandbox | **Not shown** | Mocked tests pass; no sandbox credentials. |
| Security checks pass | Yes | Section 6, `npm audit` 0, no secrets in evidence. |
| No critical browser console or API errors | Yes | 40/40 and 147 clean page loads. |
| Monitoring and recovery documented | Yes | `PRODUCTION_DEPLOYMENT_RUNBOOK.md`; recovery rehearsed locally. |

**Update 2026-11-23:** a second round, requested after this report, is in `RELEASE_CANDIDATE.md`. It adds: `pip-audit` clean in the production image; the full backend suite re-run with the **exact pinned requirements** (3,445 passed, 0 failed, 0 skipped), which supersedes the "older image" caveat in section 5; a repeatable throwaway rehearsal of the startup guard, migration step and preflight (`deploy/vps/rehearse-release.sh`, passed); the Git ancestry of the 11 marketing commits; and the monitoring findings. Your decisions are recorded there: the operator screen (O-1) and migration 0066 (O-4) are deferred, and agency stays internal-only. A read-only look at the production configuration was attempted and **denied by the tool's safety check**, so O-6 stays unverified.

**Overall: technically ready for a controlled release of this branch, with the external gates in section 8 still open.** "Technically ready" here means the code and its tests; it does not mean the live Google, Cashfree, mail and off-site pieces were exercised.

## 10. Risk of deploying this branch

Low. The change set is 6 backend and 4 frontend source files plus tests and scripts. **No migration, no environment variable, no dependency, no change to a route's URL or to the agency, WhatsApp or billing logic.** The only API change is one extra boolean in `GET /google/status`; old frontends ignore it and the new frontend treats its absence as "not available". Rollback is the previous image and Vercel deployment (runbook section 6). The two behavioural changes worth watching after release are the new sync error state (F-01) and the scheduled-publishing loop (F-02): both have a one-line check in the runbook.
