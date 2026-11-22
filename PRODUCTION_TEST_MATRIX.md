# FlowQR production test matrix

Date: 2026-11-22. Branch `hardening/production-readiness-audit`. Result words: **PASS**, **FAIL**, **BLOCKED** (cannot be done without a credential, a consent or a person), **NOT TESTED**. PASS is used only where the check was run.
"Mock" means a repository test double replaced the external service; such a PASS says nothing about the real service. Evidence paths are under `docs/evidence/production-audit-2026-11-22/` (shortened to `ev/`). WhatsApp is excluded by the brief.

How the main runs were done (reproducible):

| Run | Command | Result |
|---|---|---|
| Backend, Linux (Python 3.13) | 8 containers of `flowqr-test` (older image: PyJWT 2.10.1, no sentry-sdk), repo mounted at `/repo`, `python -m pytest <shard files> -q` each against its own PostgreSQL 16 database | 3,445 passed, 0 failed, 0 skipped (`ev/backend-suite-summary.txt`) |
| Backend baseline, Windows (Python 3.12, exact pinned requirements), before any change | same 8-shard split against PostgreSQL 16 | 3,424 passed, 3 failed (Windows-only artefacts; the same tests pass on Linux) |
| Frontend | `npx tsc --noEmit`; `npm test`; `npm run build`; `npm audit --omit=dev` | 0 errors; 131/131; clean; 0 vulnerabilities (`ev/frontend-summary.txt`) |
| Browser | `node e2e/production-audit-journeys.js` (Chromium, real UI, local stack) | 40/40 (`ev/browser-journeys-run.log`, `ev/browser-journeys-results.json`) |
| Worker and beat | `python e2e/audit-worker-sync/drive_sync.py` (real Celery, Redis, PostgreSQL; mock Google) | 21/21 (`ev/worker-beat-sync-run.log`) |

## 1. Authentication, accounts, access control

| Feature | Test performed | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| Registration form | Browser: fill, 18+ box, submit, land on onboarding | PASS | browser J1 | none |
| E-mail verification | Browser: link read from the dev mail log, opened, "Email verified" | PASS | browser J1 | Real mailbox delivery in production not tested |
| Real e-mail delivery (verify, reset, invite) via production SMTP | none possible without registering a real address | NOT TESTED |  | Needs a person with a mailbox (audit section 8, item 8) |
| Login, logout, expired and revoked sessions, password change and reset | Existing backend tests (`test_auth_and_tenancy`, `test_phase2_security_audit`) in the 3,445 | PASS | backend summary | none |
| Registration gate | Backend tests; production mode read from the public API | PASS | `test_registration_gate`; `ev/production-public-readonly-checks.txt` shows `allowlist` | none |
| Protected routes without a session | Live local probes of 6 protected routes; backend manifest test over all 486 routes | PASS | 401 on each | none |
| Cross-tenant access, user A to user B | 45-request attack sweep, all id routes, 5 methods; victim data compared before and after | PASS | `test_hardening_isolation.py` | none |
| Tenant selector header | Foreign tenant id, malformed id, random id | PASS | `test_hardening_isolation.py` (403, 400, 403) | none |
| Row-level security | 96 policies present after a fresh restore; existing raw-SQL RLS test | PASS | backup rehearsal; `test_auth_and_tenancy` | none |
| Normal user attempting admin access | Browser: owner opens `/admin/*` and calls an admin API | PASS | browser: "Platform admins only", API 403 | none |
| Platform admin console | Browser sweep: 12 screens x 3 viewports with an admin session | PASS | `ev/browser-sweep-admin.json` | none |
| Mass assignment through update endpoints | Read all 9 `setattr` loops (profile, tenant, admin business, location, agent settings, notification preferences, two post routes) and each one's input schema: only named business fields, none privileged | PASS | audit section 6 | none |
| CSRF on cookie sessions | Backend test over every mutating route; operator endpoint without the header gets 403 | PASS | `test_security_audit`; `test_hardening_operator_and_data` | none |
| Rate limiting | Live: login 429 after 10 attempts in a minute from one address | PASS | local probe | Limits are per process memory when Redis is down (by design) |
| CORS | Live: evil origin preflight refused; site origin accepted with credentials | PASS | local probe | none |

## 2. FlowHQ operator (agency) access

| Feature | Test performed | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| Operator allowlist enforced per request | Delist a signed-in operator: next call 404, no restart | PASS | `test_hardening_operator_and_data` | none |
| Unverified, signed-out, deactivated operator refused | Three tests; a replayed signed-out cookie gets 401 | PASS | same | none |
| Operator has no access to a customer's data, cannot consent for them | Calls with the customer's tenant header: 403; consent attempt: 404, 0 authorizations | PASS | same | none |
| Operator grant and revoke, audited with who | Audit rows read back | PASS | same | none |
| Operator input validation and CSRF | Bad uuid, over-long note, extra field, missing header | PASS | same | none |
| Grant separate from client consent, revoke stops use at once | Existing tests (10) | PASS | `test_google_agency_internal` | none |
| Operator screen in the app | Looked for one | NOT TESTED | no frontend route exists | **Does not exist** (audit O-1): CLI or API only |
| Real operator registration and verification | Not possible without the person | BLOCKED |  | The allowlisted operator must register and verify |
| Real client consent and agency sync with a real client | Not possible: no consent exists | BLOCKED |  | Needs a business administrator's own consent and Google |
| Pending and denied states shown when no grant or consent exists | Business without a grant gets 404 from every agency route; Locations screen no longer asks | PASS | `test_hardening_agency_visibility`, `test_google_agency_internal` | none |
| Public third-party agency access stays off | Startup-guard and `operations_enabled` tests; production `/agency-ops` demands a login | PASS | existing config tests; public GET 401 | Google's written answer still outstanding |

## 3. Google owner path (all against a test double)

| Feature | Test performed | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| Authorization URL, signed state, nonce cookie, callback | Real API: connect, callback 303 with `connected=1`; bad state and mismatched nonce refused (existing) (against a test double) | PASS | worker-beat run; `test_google_and_reviews` | Real Google consent screen not exercised |
| Scope validation | Connect without `business.manage` is refused and the token revoked (against a test double) | PASS | `test_google_and_reviews` |  |
| Token encryption at rest | Database column starts with a Fernet prefix and holds no clear text; status API never returns a token | PASS | worker-beat run |  |
| Discover account and location, map to the tenant's own location | Two businesses, each mapped to its own location (against a test double) | PASS | worker-beat run | Real resource names not confirmed live |
| Review sync: pages, duplicates across pages, empty, updated, new | 2-page responses repeating an item, an edit, a new review (against a test double) | PASS | worker-beat run |  |
| Sync stops cleanly on errors: 5xx, rate limit, revoked, not approved | Outage then recovery; revoked shown as "Reconnect"; others existing (against a test double) | PASS | worker-beat run; backend tests |  |
| An unexpected or unparseable Google answer | Was **FAIL** before the fix (row stuck on "running", no back-off). Reproduced, fixed (F-01), re-proven through the real worker | PASS | `test_hardening_sync.py`; worker-beat run | none |
| Live Google owner connection and sync | Needs a real Google login and account | BLOCKED |  | The production report says both customer locations synced; **not verified by me** |
| Read-only live smoke (`google-smoke`) | Not run: needs production credentials and a connection | BLOCKED |  | Supported way to check live access |
| Disconnect and revoke | Existing tests (against a test double) | PASS | `test_google_and_reviews` |  |
| Another business's connection cannot be used | Sweep above: connection, selection, refresh, delete, profile routes all refused | PASS | `test_hardening_isolation.py` |  |

## 4. Reviews and AI

| Feature | Test performed | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| Review list, filters, search, details, status | Backend tests; browser sweep of `/gbp/reviews` | PASS | backend summary; sweep |  |
| Rating and date correctness at the India day boundary | Controlled data: 23:59:59 and 00:00:00 IST, totals, distribution, reply rate, empty range | PASS | `test_hardening_operator_and_data` |  |
| Review retention and redaction (30-day rule) | Existing tests; backup redaction in the rehearsal | PASS | `test_google_retention`, `test_backup_redaction` | First real expiry is about 2026-12-15 |
| AI draft: positive, neutral, negative, short, long, Hindi, English, empty, API failure, timeout | Existing mocked-provider tests (`test_ai_*`, `test_phase0_review_*`) (test double, not the real service) | PASS | backend summary | Real provider quality not tested |
| AI never publishes by itself | Draft needs approval; flagged reviews need acknowledgement; publish is governed and read back | PASS | `test_phase0_*`, `test_phase1_*` |  |
| Blank reply cannot be saved | Was **FAIL** (spaces accepted as a draft). Fixed (F-06) | PASS | `test_hardening_operator_and_data` | none |
| Live AI provider | No provider key locally; production review-AI was reported switched off pending terms | BLOCKED |  | Owner decision on the provider's written terms |

## 5. QR, NFC, public pages, English and Hindi

| Feature | Test performed | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| Campaign create, with empty form refused inline | Browser | PASS | browser J4 |  |
| New campaign dialog without page errors | Was **FAIL** (React #185, three per use). Fixed (F-03). Browser shows zero | PASS | browser J4; `form-hook.test.mjs` |  |
| QR PNG download decodes to the exact campaign address | Download in the UI, decode pixels with jsQR | PASS | browser J4 |  |
| QR SVG renders and decodes to the same address | Render in Chromium, decode | PASS | browser J4 |  |
| PDF poster is a real PDF | Magic bytes and size | PASS | browser J4 | Print quality on paper not tested |
| Phone landing page opens from the scanned code | Mobile emulation | PASS | browser J4 |  |
| No sideways scroll, no console error on the public flow | Check on a phone viewport | PASS | browser J4 |  |
| Empty review refused; button stays disabled | Browser | PASS | browser J4 |  |
| Hindi and English switch | Browser: Hindi heading appears, English returns | PASS | browser J4 | AI-written Hindi not tested live |
| Optional feedback topic | Toggle | PASS | browser J4 |  |
| Continue to Google opens the business review link in a new tab and FlowQR does not post for the customer | Browser, stubbed Google page | PASS | browser J4 |  |
| Counts: scan, feedback, approved, continued to Google | Campaign page after the flow, plus event rows | PASS | browser J4 |  |
| Invalid campaign address | Page and API | PASS | browser J4 (404, calm page) |  |
| One `main` and one `h1` on the campaign page | Was **FAIL** (two of each). Fixed (F-04) | PASS | browser J4 |  |
| NFC: tag URL, `/n/` door, 302, no-store, QR door, unknown token 404, query cannot redirect elsewhere | API and browser | PASS | browser J5 | Writing a physical tag was not done |
| Paused card shows "switched off" | Browser | PASS | browser J5 |  |
| Production redirect domain | Public GETs: `go.flowqr.site/` is a 302 to the website | PASS | `ev/production-public-readonly-checks.txt` | A real card token was not scanned in production |

## 6. Analytics, billing, jobs

| Feature | Test performed | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| Dashboard numbers equal the database | Controlled data, midnight boundary, rating distribution, reply rate | PASS | `test_hardening_operator_and_data` |  |
| Another business sees none of them | Second business | PASS | same |  |
| Cashfree webhook: signature, stale timestamp, duplicate, order, unknown subscription, cross-tenant, payment id reuse, reconciliation | About 200 existing mocked tests (test double, not the real service) | PASS | backend summary | Signature check not weakened |
| Cashfree sandbox checkout and webhook | No credentials; no real charge may be made | BLOCKED |  | Needs your sandbox credentials |
| Prepaid checkout | Existing mocked tests (test double, not the real service) | PASS | `test_prepaid_*` | Reported live and unproven by a real payment |
| Scheduled sync through the real worker and beat | 30-second beat cycle picked up an edit and a new review, 61 to 81 s, no click | PASS | worker-beat run |  |
| One failing customer does not stop another | Business A's Google down, business B keeps syncing | PASS | worker-beat run |  |
| Heartbeat | beat to worker, 3 to 12 s old in Redis | PASS | worker-beat run |  |
| Retries and recovery create no duplicate reviews | Database count | PASS | worker-beat run |  |
| Scheduled posts and photos: a suspended business no longer starves others | Was **FAIL**. Fixed (F-02); a first fix broke an existing test and was replaced | PASS | `test_hardening_scheduling.py`; `test_phase15_retention_and_live_prep` |  |
| Task failures visible | Failed location counted on the Operations check | PASS | `test_hardening_sync.py` | Celery reports "succeeded" for handled failures (audit O-2) |
| Production worker, beat and the two customer syncs | Needs a shell or the Operations page | NOT TESTED |  | Check Admin > Operations after release |

## 7. Database, security, infrastructure

| Feature | Test performed | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| Migrations from empty to head | Every shard rebuilds the schema; single head `0065` | PASS | backend summary |  |
| Migration 0065 | Existing test: table, platform-only RLS, one open grant per business | PASS | `test_migration_0065` |  |
| Foreign-key integrity | 266 constraints; FK index audit | PASS | audit O-4 | 134 lack a leading index: performance recommendation, not an integrity fault |
| SQL injection | Live injection-style tokens; raw SQL scan | PASS | local probe; audit |  |
| Security headers, docs hidden in production | Live local and public production | PASS | `ev/production-public-readonly-checks.txt` |  |
| Dependencies | `npm audit --omit=dev` | PASS | `ev/frontend-summary.txt` | `pip-audit` not run (PyPI too slow here) |
| Python dependency audit | `pip-audit` was not run (PyPI was too slow from this machine) | NOT TESTED |  | Run `pip-audit -r backend/requirements.txt` before the release; the previous release reported it clean |
| Secrets in evidence | Scan of the evidence folder | PASS | only the URL `/forgot-password` matches |  |
| Backup: redaction, AES-256, sha256, read-back, restore | Real scripts on a throwaway database; local folder as the "off-site" copy | PASS | `ev/backup-restore-rehearsal.txt` | Proves the mechanism only |
| Corrupted backup is rejected | Flipped byte: `gzip -t` fails, sha256 differs, `verify-restore.sh` refuses it | PASS | audit section 6 | Encryption is not authenticated (O-3) |
| Real off-site destination | None configured | BLOCKED |  | Needs `BACKUP_REMOTE` and an off-server passphrase copy |
| Production API ready | Public GET: `{"ready":true, database ok, redis ok, migrations ok}` | PASS | `ev/production-public-readonly-checks.txt` |  |
| Production site, redirects, headers, certificates | Public GETs; certificates valid to Feb 2027 | PASS | same |  |
| Container restart behaviour and the startup guard on the server | No server access | NOT TESTED |  | Use the throwaway-guard step in the runbook before any recreate |
| Error monitoring (Sentry) and alert e-mail | Not verifiable from outside | NOT TESTED |  | Audit O-6 |
| Load, N+1 queries, connection pool under stress | Not measured | NOT TESTED |  | Audit O-8 |

## 8. Responsive frontend and usability

| Feature | Test performed | Result | Evidence | Remaining issue |
|---|---|---|---|---|
| 22 owner screens x desktop, tablet, phone | Load each: crash, page error, broken image, failed request, HTTP error, sideways scroll, unlabeled control | PASS | `ev/browser-sweep-app-and-public.json` |  |
| 15 public pages x 3 viewports (customer page, marketing, legal, sign-in) | Same checks | PASS | same |  |
| 12 admin screens x 3 viewports | Same checks | PASS | `ev/browser-sweep-admin.json` |  |
| Locations screen without a failed request | Was a 404 on every visit. Fixed (F-05) | PASS | sweep |  |
| Onboarding validation, trial copy, no repeat of onboarding | Browser | PASS | browser J1 |  |
| Signed-in visit to `/login` redirects to the dashboard | Sweep | PASS | sweep |  |
| Safari, Firefox, real phones | Chromium emulation only | NOT TESTED |  | Audit O-7 |
| Contrast, screen reader | Names and landmarks only | NOT TESTED |  | Audit O-7 |
| WhatsApp | Excluded by the brief; code, configuration and templates untouched | NOT TESTED |  | Out of scope |
