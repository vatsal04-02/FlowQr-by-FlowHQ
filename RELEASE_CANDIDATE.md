# Release candidate for approval

Prepared 2026-11-23 from branch `hardening/production-readiness-audit`. **Nothing is deployed, pushed, merged or tagged on any remote.** The candidate is the local git tag `rc/2026-11-23-1`; `git rev-parse rc/2026-11-23-1` is the exact commit. Companions: `PRODUCTION_READINESS_AUDIT.md`, `PRODUCTION_TEST_MATRIX.md`, `PRODUCTION_DEPLOYMENT_RUNBOOK.md`, evidence in `docs/evidence/production-audit-2026-11-22/`.

**Decision requested:** approve (or not) deploying this candidate to production, following section 6. Production deployment has not been approved and will not happen without your word.

## 1. What is being released

* 10 application source files (6 backend, 4 frontend) fixing 6 defects. **No migration** (alembic stays `0065`), **no environment variable**, **no dependency**, no change to the Dockerfile or compose files.
* Everything else in the candidate is tests, scripts, evidence and documents, none of which is loaded by the running application.
* Decisions you gave: the operator screen is deferred (agency stays internal-only, no code change); migration 0066 and the foreign-key indexes are deferred to a separate investigation with real query plans; Sentry is verified and a set-up recommended (section 5). None of those changes the candidate.
* **Not touched at all:** billing and Cashfree, authentication, WhatsApp, the agency services, consent and authorization logic, Google authorization modes, existing customer connections, any environment or compose file.

## 2. Git ancestry (checked against a fresh `git fetch`)

| Fact | Result |
|---|---|
| `origin/release/gbp-agency` | `0604555` |
| Merge-base of the candidate and `origin/release/gbp-agency` | `0604555` itself |
| Is `origin/release/gbp-agency` an ancestor of the candidate? | **Yes** |
| Ahead / behind | the candidate is **13 ahead, 0 behind** (before this round's documentation commit) |
| The 11 marketing commits (`14bacab` to `0604555`, home-page hero only, 5 frontend files) | **All 11 are ancestors of the candidate: they are the base it was built on. Nothing was re-applied, re-created, squashed or rebased, so their hashes and authorship are unchanged.** |
| Files changed by the marketing commits | `(marketing)/page.tsx`, `globals.css`, `HeroActions.tsx`, `HomeHero.tsx`, `content/marketing/en.ts` |
| Files changed by the candidate's own commits | none of those five (verified with `git diff 0604555 <candidate> --name-only`) |
| Other remote branches | `release/ui-premium` and `release/ui-redesign-cashfree` are other lines of work; untouched |
| What I pushed | nothing, to any branch of any remote |

Because the remote branch is an ancestor, bringing it up to date is a **plain fast-forward** (`git push origin <candidate>:release/gbp-agency`): no merge commit, no force, no rewrite of anyone's commits. Do that only after the release is verified, and only after checking whether `release/gbp-agency` is Vercel's production branch (runbook step 7).

## 3. Review of the full diff (all six fixes, line by line)

| Fix | Files | What changes at run time | Who could be affected | Verdict |
|---|---|---|---|---|
| F-01 sync stuck on "running" | `google/sync.py` | Any exception that is not a known Google error, raised during a location sync, is now logged with its traceback, stored as a plain error on that location, counted and backed off (5 min, doubling, up to 6 h). `GoogleNotConfigured` still propagates; all known Google errors take the same paths as before. | Customers' hourly syncs on the normal path: **no change** (the new branch only runs when an exception escapes). | Safe. Two honest side effects below. |
| F-02 starvation | `workers/tasks.py`, `agent/posts.py`, `media.py` | `due()` takes an `exclude` list (default empty, so every other caller is unchanged); the post and photo jobs ask for one item at a time and exclude those already inspected. Up to 500 inspected per run, at most 40 posts or 20 photos sent. | Scheduled posts and photos of every business: the same items are sent in the same order; held items are simply no longer able to hide the ones behind them. Fewer rows are locked at once (1 instead of 5). | Safe. 209 related tests pass, including reinstatement and crash-safety suites. |
| F-03 form crash | `frontend/src/lib/form.ts` | Blur validation reads the latest values from a ref instead of calling a setter inside a state updater. | The 13 screens that use `useForm`: login, register, forgot and reset password, onboarding, account, billing payments, settings, team, AI voice, new campaign, locations, admin cards. Sign-up, onboarding and campaign creation were driven in a real browser; the other screens share the same hook. | Safe; guarded by tests that fail on the old code. |
| F-04 landmarks | `LandingFrame.tsx` | In preview mode only, `div` and `p` replace `main` and `h1`. | Only the live preview inside the dashboard. The customer's page is unchanged. | Safe. |
| F-05 agency 404 | `api/v1/google.py`, `AgencyManager.tsx`, `GoogleConnection.tsx` | `GET /google/status` gains `agency_available` (a bare boolean). The panel requests `/google/agency/status` only when it is true. | Every customer sees one fewer failing request. The agency routes themselves are **unchanged** (still 404 for anyone not entitled). An old frontend ignores the field; a new frontend treats its absence as "not available". Nothing is enabled or exposed. | Safe. One cost below. |
| F-06 blank reply | `schemas/reviews.py` | Reply text is trimmed and must have at least 2 characters; the stored text is the trimmed text. | Anyone saving a reply draft: a blank one is now refused with "Write a reply first." Valid replies are unchanged (they were already trimmed on creation). | Safe. |

**Costs and side effects I found while reviewing (none blocks the release):**
1. `/google/status` now opens one extra short-lived database session per call **when the agency switches are on** (production's configuration), to read the grant table. Each API worker has a pool of 10 plus 20 overflow connections; that is negligible at today's scale and cannot be reached by a handful of customers. If customer numbers grow into the hundreds of simultaneous users, cache the answer for a few seconds.
2. An unexpected sync error no longer triggers Celery's automatic retries (up to 3, after 1 to 15 minutes); it is retried by the normal schedule after the 5-minute back-off instead. A brief database outage during a sync therefore marks the locations being synced at that moment as "error" for at least 5 minutes, with the message "FlowQR could not process Google's answer for this profile", which is generic for that cause.
3. Sentry (if configured) will receive that new exception log, whose message can carry a fragment of what Google returned (for example a malformed timestamp). It is scrubbed of bodies, headers and locals, but see the 30-day retention advice in section 5.

## 4. Test evidence

| Check | Command or method | Result |
|---|---|---|
| **pip-audit** | `pip-audit` inside the production image (Python 3.13.18, pinned requirements) | **No known vulnerabilities found.** Full output and the 57 installed packages: `pip-audit-production-image.txt`. All 14 exact pins match what is installed. |
| **Backend on Linux with the exact pinned requirements** | `docker build ./backend` (the real Dockerfile), plus only `requirements-dev.txt` on top; whole repo mounted; 8 shards, one PostgreSQL 16 database each | **3,445 passed, 0 failed, 0 skipped** (shards: 391, 429, 331, 480, 388, 433, 447, 546; all exit 0). This replaces the earlier Linux run, which used an older test image. `backend-suite-pinned-requirements.txt` |
| Frontend | `npx tsc --noEmit`; `npm test`; `npm run build`; `npm audit --omit=dev` | 0 errors; 131 of 131; clean; 0 vulnerabilities |
| Browser, real UI | `node e2e/production-audit-journeys.js` | 40 of 40; 147 page loads clean |
| Real worker and beat, mock Google | `python e2e/audit-worker-sync/drive_sync.py` | 21 of 21 |
| **Startup guard, migration and preflight, in a throwaway production-shaped project** | `deploy/vps/rehearse-release.sh audit <backup> <passphrase file>` (2 min 20 s) | **REHEARSAL PASSED**: guard accepts the production-shaped configuration and refuses the three unsafe ones (including the 2026-11-22 incident); a 0065 backup restored; `migrate` exited 0 with the database at head `0065`; the preflight ran; api, worker and beat came up together with both compose files, `/api/ready` true, heartbeat present, no error lines, operator endpoints 401, docs 404. Log: `rehearsal-script-run.log`. |
| Cross-tenant attack sweep, operator, analytics, sync, scheduling, agency-visibility tests | `tests/test_hardening_*.py` | all pass (23 tests, included in the suite) |

The preflight's own FAIL lines in that rehearsal are expected there and are not release findings: SMTP (the host is deliberately unresolvable), AI key, Sentry and backups (none exist in a fake environment). One is a **real defect in the preflight itself**: it demands Razorpay keys ("paid plans cannot be bought") although production bills through Cashfree, so with Cashfree that line always reports FAIL. That is a stale check, not a production problem; fix it in the separate milestone.

## 5. Production monitoring: what is verified, what is not, what I recommend

* **Not verified live.** I tried a strictly read-only inspection of the production API container (booleans, counts and statuses only; `deploy/vps/readonly-status.py`). The tool's safety check **denied the ssh connection** and I did not look for another route. So I cannot tell you whether production has `SENTRY_DSN` set, whether SMTP alerts work, or what Admin > Operations currently shows. **To get this, run the command in the runbook (step 1) yourself, or tell me explicitly that I may run it.** Public facts only: `/api/ready` is true, registration is `allowlist`, operator routes demand a login, API docs are not served.
* **Verified from the repository.** `SENTRY_DSN` and `SENTRY_ENVIRONMENT` are passed through by the compose files (so setting them works); Sentry, when set, reports unexpected exceptions and failed Celery tasks in the API, worker and beat, scrubbed.
* **The Celery failure-reporting issue, explained.** When Google fails, the sync job records the failure on the location (status, count, back-off) and finishes normally, so Celery calls it "succeeded" and Sentry never sees it. That is deliberate (it stops retry storms) and the failure is not lost: it shows in Admin > Operations. **The real weakness is who gets told:** the "Failed publishing and sync" check is only a **warning** until 10 items fail, and e-mails and the Sentry "ops critical" message go out only for **critical**. With a few customers, a location that cannot sync, or a revoked connection, never alerts anyone.
* **Recommendation (monitoring set-up), in order of value:** (1) an external uptime monitor on `https://api.flowqr.site/api/ready` and the website with alerts to you: the alert job runs inside the stack it watches, so if worker, Redis or beat stop, nothing else can tell you; (2) `SENTRY_DSN` for the backend, `SENTRY_ENVIRONMENT=production`, 30-day event retention, e-mail on new issues, Sentry added to the privacy notice's processors; (3) a small follow-up change so that a selected location in error for more than 6 hours, or any revoked connection, grades **critical** (then the existing e-mail and Sentry message fire); (4) confirm the alert e-mail actually arrives; (5) until (3) exists, run the status script daily and treat the first failing location as an incident. None of this is in the candidate.

## 6. Deployment plan (full detail and rollback in `PRODUCTION_DEPLOYMENT_RUNBOOK.md`)

0. Approve this candidate. Choose how the marketing and hardening work are published (fast-forward after verification, section 2).
1. Starting state, read-only: `ps`, `alembic current` (expect `0065`), `docker port` (expect `172.17.0.1:18000`), `/api/ready`, md5 of both compose files, the saved fingerprint, **and the status baseline** `status-before.txt` (also tells us the Sentry, SMTP and Operations facts above).
2. Backup then restore proof: `./deploy/backup.sh`, `cat backups/status.json`, `./deploy/verify-restore.sh`. (It will not be off-site; that gate stays open.)
3. Build `flowqr-backend:prod-<short sha>` from a clean `git archive` of the tag; confirm the image id is identical locally and on the server. Run `pip-audit` again on that exact image.
4. `deploy/vps/rehearse-release.sh prod-<short sha> <latest backup> <passphrase file>` must print `REHEARSAL PASSED`.
5. Real guard against the real `.env.production`, in a throwaway container: `... run --rm --no-deps -T api python -c "import app.main"` must exit 0 with no "Unsafe" text. If it refuses: stop, nothing has changed.
6. Migration step (a no-op): `... run --rm --no-deps -T migrate`; alembic stays `0065`.
7. Recreate `api worker beat` together, `--no-deps`, **both compose files**; at once check `docker port` (172.17.0.1:18000), `/api/ready`, env diff = image tag only, compose md5 unchanged.
8. Frontend from the tag with the Vercel CLI (no push), record the new and previous deployment ids, check the aliases.
9. Smoke tests, rows 1 to 17 in the runbook, then `status-after.txt` and its diff against the baseline.
10. Only then announce anything. Then, optionally, the fast-forward push.

**Rollback** (any time, no data loss because there is no migration): `FLOWQR_TAG=<previous tag>` with `up -d --no-deps api worker beat` and both compose files; promote the previous Vercel deployment. Previous images stay on the server. Details and the agency, emergency-stop and restore cases are in runbook sections 5 and 6.

**Rollback triggers:** `/api/ready` not true within 60 seconds of the recreate; any "Unsafe" line; a container restarting; a customer location newly `error` or `running` for more than 30 minutes; a Traceback in the first 10 minutes of logs; the New campaign dialog or Locations screen showing a console error.

## 7. What is still incomplete (and so what I am not claiming)

The application is **not** claimed to be fully production-ready. These remain open and are all outside this candidate: **agency activation** (operator registration, a real client's consent, Google's written answer; agency stays internal-only and no writes are enabled), **live billing verification** (Cashfree sandbox or a controlled live check by you), **real e-mail testing** (a real mailbox for verification, reset, invitation and alert mail), **off-site backups** (no destination yet), and the unverified production monitoring facts in section 5. Also not live-verified by me: the current state of the two customer syncs and Google owner OAuth, which the post-deployment checks 15 and 16 will prove against production.

## 8. Needs from you

1. Approve or reject this candidate for production deployment.
2. Either run the read-only status command (runbook step 1) and send me the output, or tell me I may run it.
3. How to publish the branch (fast-forward after verification), and whether `release/gbp-agency` is Vercel's production branch.
4. The follow-ups you want scheduled: alert grading (section 5), the stale Razorpay preflight check, the operator screen, the index investigation.
