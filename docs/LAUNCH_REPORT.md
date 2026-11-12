# Launch report: growth-platform build (2026-11-12)

Branch `feature/growth-platform`, local commits only. Not pushed, not deployed.

## Test results (exact)

| Gate | Result | Kind |
|---|---|---|
| Backend suite (pytest, throwaway Postgres in Docker) | **791 passed, 0 failed** (6m27s) | **Mocked** Google (fake provider / mock transport) and scripted AI |
| Frontend typecheck (`tsc --noEmit`) | clean | n/a |
| Frontend production build | compiled | n/a |
| Browser e2e `e2e/agent-and-posts.js` | **25/25** | Seeded DB rows; **no Google call made**. The "publish" check expects an honest failure |
| Browser e2e `e2e/qr-and-access.js` (regression) | **23/23** | Same |
| Migration 0016–0017 | up to 0017, down to 0015, up again: OK on a fresh DB | real Postgres |
| Local stack deploy | 6 services healthy; real DB at 0017; data fingerprints (tenants, users, reviews, campaigns, locations, subscriptions) identical before/after | live local |
| Celery | new tasks registered (`publish_due_posts`, `daily_agent`, `purge_deleted_accounts`) | live local |
| **Live Google** (accounts, locations, reviews, posts) | **NOT VERIFIED.** No consent completed; Business Profile APIs not confirmed enabled/approved | blocked |
| AI drafting with the real provider | not exercised in e2e (would spend quota); covered by scripted-AI tests | mocked |

## Blocked, and by what

- **Live Google:** enable the Business Profile APIs on project 806581490238 and get access approved; complete OAuth consent with an account that manages a verified location; then run `python -m app.cli google-smoke --connection <id>` (read-only).
- **Payments:** Razorpay keys.
- **Meta / WhatsApp / rank provider:** credentials; pages are "Setup required" only.
- **Email:** SMTP and a support address (privacy page says the address is unset until configured).

## Owner action list

1. Complete Google consent at `/google`, then run the smoke test.
2. Rotate the OAuth client secrets that were pasted into chat earlier.
3. Add Razorpay keys; set support email, SMTP, AI provider key.
4. Have counsel review `/privacy`, `/terms`, `/data-deletion`.

## Known limitations

No photo file upload; no review date/sentiment filters; global location picker only on new pages; AI Review Assistant page not yet split into customer/owner/usage views; no plan gating for the agent; no GST invoices; no error-monitoring hooks; auto-publish intentionally off. Docker Desktop on this machine stopped on its own several times during testing (environment, not the app).

## Production launch checklist

See `CHECKLIST.md` and `STAGING_READINESS.md`; additionally: backup before migrating (done locally: `flowqr-before-0016-0017.dump`), set strict config secrets, confirm beat is running, confirm `publish_due_posts` runs every 60s.
