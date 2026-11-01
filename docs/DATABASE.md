# Database architecture

PostgreSQL 16, SQLAlchemy 2 models in `backend/app/models`, schema owned by Alembic (`0001` tables, `0002` RLS + grants, `0003` card-code sequence, `0004` billing/verification/suspension + plan seeds + RLS for `payments`/`card_orders`). All primary keys are UUIDs.

```
tenants ─┬─ memberships ── users            (role: owner|admin|staff; unique tenant+user)
         ├─ invitations
         ├─ subscriptions (1:1)             (plan, INR, AI quota, max locations)
         ├─ locations ─┬─ google_locations ── google_connections   (encrypted tokens)
         │             ├─ reviews ── reply_drafts ── reply_logs    (unique google_location_id+external_id)
         │             └─ qr_cards ── card_assignments (history)
         ├─ scan_events      (card_id, tenant_id/location_id snapshot, type, is_bot, daily-salted visitor hash)
         ├─ ai_generation_logs (kind, provider, model, sizes, status — never text)
         └─ audit_logs       (append-only for the app role)
card_batches ── qr_cards  (tenant_id NULL while unassigned)
billing_plans (seeded: essential 39900 / growth 79900 / multi 149900 paise)
subscriptions (plan, status, limits, features, trial/period dates, razorpay_subscription_id unique)
payments (kind: subscription | card_order — separate; razorpay_payment_id unique) ── card_orders (physical cards; idempotency key)
webhook_events (provider+event_id unique: webhook idempotency; not tenant scoped)
email_verification_tokens
auth_sessions, password_reset_tokens   (not tenant scoped; token hashes only)
```

## Tenant isolation
1. Every tenant-owned row has `tenant_id` + FK (`ON DELETE CASCADE` from `tenants`).
2. Endpoints filter by the server-derived tenant.
3. **RLS**: `ENABLE` + `FORCE ROW LEVEL SECURITY` and policy `tenant_isolation` on 16 tables (incl. `payments`, `card_orders`) + `tenants`:
   `USING/WITH CHECK (app.bypass_rls = 'on' OR tenant_id = nullif(app.tenant_id,'')::uuid)`. The context is set per transaction by the `after_begin` hook (`core/db.py`). The runtime role `flowqr_app` is `NOSUPERUSER NOBYPASSRLS`; migrations run as owner `flowqr`.
4. Tests assert RLS with raw SQL on the real app role: no context → 0 rows; tenant A context → only A rows; inserting a row for tenant B fails `WITH CHECK`.

## Notable constraints & indexes
* `qr_cards.card_code` unique, `qr_cards.public_token` unique (144-bit random).
* `reviews (google_location_id, external_id)` unique → duplicate-free sync; `(tenant_id, location_id, review_created_at)` index for the inbox.
* `google_locations (tenant_id, google_location_name)` unique.
* `scan_events` indexes on `(tenant_id, created_at)`, `(card_id, created_at)`, `(event_type, created_at)`.
* `audit_logs` / `reply_logs`: `UPDATE, DELETE` revoked from the app role.
* Scan history survives reassignment: events snapshot `tenant_id/location_id` at event time; `card_assignments` records ownership history.

## Backups
`deploy/backup.sh` (pg_dump, gzip, 14-day local retention) and `deploy/restore.sh`. Copy backups off-host. Test a restore before relying on it.
