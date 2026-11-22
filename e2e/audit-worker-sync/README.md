# Worker, beat and sync journey (mock Google)

Proves, with the real API, Celery worker, Celery beat, Redis and PostgreSQL, that a connected location is synced on schedule, that one failing customer cannot stop another, that a review Google
returns in a shape FlowQR cannot parse ends in a visible backed-off error (not "running" forever) and recovers by itself, that retries create no duplicates, and that revoked Google access is shown
as a reconnect message. **Only the Google provider is replaced**, by a file-driven fake (`mockgoogle.py`). Nothing here talks to Google, Cashfree or an AI provider.

**Use a disposable local stack only. Never point it at production** (it registers throwaway businesses and edits sync rows with SQL).

```bash
# 1. a throwaway Postgres (roles flowqr and flowqr_app, see db/init) and Redis, migrated:  python -m alembic upgrade head
# 2. the same environment for all three roles (APP_ENV=development, REGISTRATION_MODE=open, dummy GOOGLE_CLIENT_ID/SECRET, REVIEW_SYNC_INTERVAL_MINUTES=1, FRONTEND_URL, TOKEN_ENCRYPTION_KEY, ...)
export FLOWQR_BACKEND=<repo>/backend FAKE_GOOGLE_CONTROL=<tmp>/fake_google.json API_PORT=8700
echo '{}' > "$FAKE_GOOGLE_CONTROL"
python e2e/audit-worker-sync/mockgoogle.py api    > api.log 2>&1 &      # the dev API (its log carries the development "emails")
python e2e/audit-worker-sync/mockgoogle.py worker > worker.log 2>&1 &
python e2e/audit-worker-sync/mockgoogle.py beat   > beat.log 2>&1 &
E2E_API_LOG=$PWD/api.log PG_CONTAINER=<postgres container> PG_DB=<database> REDIS_CONTAINER=<redis container> OUT_DIR=<folder> python e2e/audit-worker-sync/drive_sync.py
```

Takes about 8 minutes (it waits on beat's 30-second cycle several times). Exit code 0 means every check passed. The fake lists reviews newest-update-first, two per page, repeating one item across pages, as
Google does; the sync's early stop relies on that order.
