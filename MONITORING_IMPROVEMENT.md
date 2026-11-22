# Monitoring improvement (separate from the release candidate)

Branch `monitoring/sync-error-critical`, created from the release-candidate tag `rc/2026-11-23-1` (commit `05405771`), which is **unchanged**. This branch is not part of the candidate. Nothing here is pushed, merged or deployed.
Evidence from the production checks is in `docs/evidence/release-verification-2026-11-23/`.

## 1. The change: a location failing to sync for 6 hours is critical

**Code:** `backend/app/services/ops.py` (`check_stuck_sync`, registered in `run_checks`) and `backend/tests/test_monitoring_stuck_sync.py`. No migration, no setting, no new environment variable (so nothing to add to the compose overlay).

**Behaviour**
* Any selected customer location whose status is `error` and whose last **successful** sync is 6 hours old or more (a never-synced location is measured from its creation) makes the check **critical**, even if it is the only location in the system. The old "Failed publishing and sync" check still only warns below 10 failures and is unchanged.
* It goes through the existing `alert_on_new_critical`, so with no new alerting code: platform admins are e-mailed within one `ops_watch` cycle (15 minutes), **once**, again once a day while it lasts, and again if it clears and breaks again; and the Sentry message is sent when a DSN exists.
* A sync runs every 30 minutes, so "last success 6 hours ago and still in error" means it failed on every attempt since.
* Not counted: a location that is no longer selected, and a business that is suspended or scheduled for deletion. **Counted on purpose: a revoked Google connection that stays in error** (the owner has to reconnect). If an owner abandons Google deliberately, that will e-mail once a day until they disconnect it properly; say so if you would rather exclude revoked connections.
* The text carries **counts only**: no business name, location title or address, because the same text goes to Sentry.

**Proof:** 12 new tests (threshold at 5.9 h, 6.1 h and 30 h; one location is enough; never-synced; revoked; deselected, suspended and deleting businesses; recovery; the privacy rule; the actual e-mail to two admins, once, and again only after it clears; the Operations page and overall status). **They fail (12 of 12) against the release candidate's `ops.py` and pass with the change.** Full Linux suite with the pinned requirements: see section 7.

## 2. Independent worker and beat monitoring: recommendation

**The problem.** `ops_watch` runs inside the worker. If beat, the worker, Redis, Docker or the server stops, the thing that would e-mail you is the thing that stopped. The Operations page also cannot be seen when nobody is looking. Production evidence that it matters: the job's own counter shows 569 failures over about 6 days (the last 24.6 hours before the check), so for most of last week the alert path was itself broken and nothing said so.

**Recommended (three layers, all external or host-level, all with free tiers):**

| Layer | What | Catches | Setup |
|---|---|---|---|
| 1. **Dead-man's switch** (recommended first) | `deploy/vps/heartbeat-ping.sh` from the host's cron, every minute. It reads the beat-to-worker heartbeat directly from Redis and pings an external monitor **only while the heartbeat is fresh** (under 180 s). | beat not scheduling, worker not running, Redis down, Docker down, **the whole server down or offline** (the pings stop either way) | Create a heartbeat check at Healthchecks.io, Better Stack or Cronitor (every 1 minute, 5 minutes' grace, alert to you by e-mail or a messaging app); put its URL in `/opt/flowqr/.env.heartbeat` (mode 600); one cron line. Tested locally in 8 cases and its Redis read was confirmed on production (key readable without auth, 50 s old). |
| 2. **External HTTP monitor** | Check `https://api.flowqr.site/api/ready` (database, Redis and migrations in one answer) and `https://www.flowqr.site/` every minute, alert on two failures in a row | API down, proxy or certificate trouble, database or Redis unreachable, migrations behind the image, the website down | UptimeRobot, Better Stack or the same vendor as layer 1 |
| 3. **Sentry** | `SENTRY_DSN` for the backend | unexpected exceptions and failed Celery tasks, with tracebacks | section 3 |

Why not only the app's own heartbeat: it is the right signal but must be judged **from outside**. Why not Prometheus or Grafana: more to run and watch than a one-person operation needs; revisit with more customers.

Things that would **not** be caught even with all three, so keep them in the daily routine for now: a location failing (covered by section 1), a backup that did not reach off-site (see section 5), and mail that is accepted by the server but never reaches an inbox.

## 3. Sentry and SMTP, as found in production on 2026-11-22

* **Sentry: not configured.** `sentry_dsn_set = False`; the Operations page shows "Error reporting" as **critical** because of it. The variable reaches the containers through the compose files, so setting it works. Recommendation: one Sentry project for the backend, `SENTRY_ENVIRONMENT=production`, traces off, **30-day event retention** (matching Google's storage limit, because an exception message can carry a fragment of what Google returned), e-mail on every new issue, Sentry added to the privacy notice's processors. Validate with the throwaway guard before recreating containers. Note that while the DSN is unset, the "Error reporting: critical" row is already an open critical alert, so that e-mail is sent once a day to the platform admin until it is set.
* **SMTP: configured and working at login level.** A host and a user are set, it is not a local sink, port 587 with STARTTLS (certificate verified against the default store), authentication succeeded, and the retained api and worker logs hold 0 delivery failures. **No message was sent**, so delivery to a real inbox (and spam placement) is still untested: send one test message with `python -m app.cli preflight --smtp-test <your address>` when you approve.

## 4. The stale Razorpay checks (production bills through Cashfree)

Production reads `billing_provider = cashfree`, `cashfree_enabled = True`, `cashfree_env = production`, `prepaid_checkout_enabled = True` and **no Razorpay keys**. Two health surfaces still assume Razorpay:

| Where | Lines | What it does wrong | Recommended correction |
|---|---|---|---|
| Operations page (live today, a permanent yellow row) | `backend/app/services/ops.py` 275 to 277 (`razor = ...; out.append(row("razorpay", "Razorpay", "ok" if razor else "warn", "... Not configured: paid plans cannot be bought" ...))`) | Warns "Not configured: paid plans cannot be bought" although paid plans are sold through Cashfree | Make it provider-aware: when `settings.billing_provider == "cashfree"` (or Razorpay keys are absent and Cashfree is configured) show a **Cashfree** row: ok when `cashfree_configured` and a webhook secret (`cashfree_webhook_secret` or the client secret) exist, with the environment (`production` or `sandbox`) in the text; keep the Razorpay row only when Razorpay keys exist |
| Deployment preflight | `backend/app/ops_cli.py` 119 to 126, in particular the `else` at line 126: `r.add(FAIL if hardened else WARN, "Razorpay", "keys not set: paid plans cannot be bought")` (also the header at line 4 and the pass text at line 60) | **Fails the preflight in production for a correct configuration**, so it can never print "No blocking failures" | Same rule: a Cashfree block (client id and secret set, environment, webhook secret, `PREPAID_CHECKOUT_ENABLED`); Razorpay only when Razorpay keys are set. The existing guard in `config.py` already refuses mixing the two |
| Lapsed-subscription check | `ops.py` line 270 (`Subscription.source == "razorpay"`) | Only counts Razorpay-sourced subscriptions, so a lapsed Cashfree subscription is not reported there | Count both sources, or all paid sources |

I have **identified, not changed** these (your instruction). They are low-risk and each needs a test; say if you want them prepared on this branch.

## 5. Backup facts found on the server (read-only)

* Latest nightly backup `flowqr-20261122T104602Z.sql.gz.enc`: `ok true`, `encrypted true`, **`offsite false`**, `restore_verified_at` 2026-11-15 (a week old). The nightly cron (`10 2 * * *`, server time) exists; `.backup.pass` exists with mode 600; `.env.backup` exists and defines **no** `BACKUP_REMOTE`. Plain `pre-grants-...sql.gz` and `pre-internal-...sql.gz` manual dumps are also in `backups/` (unencrypted gzip; the nightly script prunes manual dumps after 14 days). For the release, take the pre-deployment dump with `backup.sh` (encrypted and redacted), not a raw `pg_dump`.
* **The Operations page cannot read the backup status**: the API container gets `PermissionError` on the status file, so the row shows "cannot be read by this container (permissions)" instead of the real state. Fix by making a status-only folder or file readable by the application user (the app's own hint says the same).
* The weekly restore proof is overdue by the repository's own rule; run `./deploy/verify-restore.sh` before and after the release.

## 6. Other things the production status showed

* 3 trials end within 3 days (Operations "Subscriptions"): worth knowing before a release window.
* `ops_watch` history: see section 2.
* `whatsapp_enabled = True`: unchanged and untouched by everything here.

## 7. Test evidence for this branch

See the final report. The new tests: `backend/tests/test_monitoring_stuck_sync.py` (12). Heartbeat script: `docs/evidence/release-verification-2026-11-23/heartbeat-ping-script-test.txt` (8 cases). Full suite: `docs/evidence/release-verification-2026-11-23/backend-suite-monitoring-branch.txt`.
