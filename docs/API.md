# API reference

Base path `/api/v1`. Interactive OpenAPI at `/api/docs` when `APP_ENV != production`. JSON in/out. Errors: `{"detail": "..."}` or `{"detail": {"code": "...", "message": "..."}}`.

**Auth**: HTTP-only cookie `flowqr_session`. State-changing requests must send header `X-CSRF-Token` (value of cookie `flowqr_csrf`, also returned by `POST /auth/login|register` and `GET /auth/me`). Roles: **S**taff < **A**dmin < **O**wner. *PA* = platform admin (FlowHQ).

| Method & path | Who | Purpose |
|---|---|---|
| `POST /auth/register` · `/auth/login` | public (rate-limited) | create account / log in (sets cookies) |
| `POST /auth/logout` · `GET /auth/me` | session | end session / profile, memberships, csrf token, integration flags |
| `PATCH /auth/profile` · `POST /auth/change-password` | session | profile; password change revokes other sessions |
| `POST /auth/password-reset/request` · `/confirm` | public | always `202` on request; token valid 30 min, single use, revokes sessions |
| `POST /auth/select-tenant?tenant_id=` | session | switch active business (membership verified) |
| `POST /auth/verify-email` · `POST /auth/resend-verification` | public / session | email verification (72 h single-use token); required for billing, staff invites, Google connect |
| `POST /tenants` | session | onboarding: create business (+Owner membership, trial subscription) |
| `GET/PATCH /tenant` | S / A | business profile, AI tone & instructions |
| `POST /tenant/complete-onboarding` | A | requires ≥1 location |
| `GET /staff` · `POST /staff/invitations` · `DELETE /staff/invitations/{id}` | S / A / A | team & invitations (only Owner invites admins) |
| `PATCH /staff/{user_id}` · `DELETE /staff/{user_id}` | O / A | change role / remove (last owner protected) |
| `POST /invitations/accept` | session | accept invite (email must match) |
| `GET/POST /locations` · `GET/PATCH/DELETE /locations/{id}` | S / A / S / A / O | locations; `review_url` must be `https` Google host; delete = deactivate |
| `GET /cards` · `PATCH /cards/{id}` | S / A | own cards; label, re-point to own location |
| `POST /cards/{id}/deactivate|activate|report-lost` · `GET /cards/{id}/qr.png|svg` | A | lifecycle; QR download |
| `GET/POST /admin/batches` · `GET /admin/batches/{id}/export.zip|sheet` | PA | create batches; ZIP (PNG+SVG+manifest.csv); printable sheet |
| `GET /admin/cards` · `GET /admin/cards/{id}` | PA | inventory (search `search=FQR-00`, `status`, `batch_id`, `tenant_id`), history |
| `POST /admin/cards/{id}/assign|unassign|status` · `GET .../qr.png|svg` | PA | assignment (location must belong to tenant), status |
| `GET /admin/tenants` · `/admin/tenants/{id}/locations` · `/admin/stats` | PA | platform overview |
| `GET /public/c/{token}` | public (60/min/IP) | resolve card → landing data; records `scan` |
| `POST /public/c/{token}/event` | public | `landing_view` \| `copy` \| `google_click` |
| `POST /public/c/{token}/assist` | public (6/10 min/IP+card, tenant quota) | polish the customer's own text; `503` when AI is not configured |
| `GET /google/status` | S | `configured`, connections |
| `POST /google/connect` | A | returns `auth_url`; `503 google_config_pending` if credentials missing |
| `GET /google/callback` | browser redirect | validates state+nonce+session+role, stores encrypted tokens, discovers locations |
| `GET /google/connections/{id}/locations` · `POST .../refresh-locations` · `PUT .../selection` | S / A / A | list, rediscover, choose & map locations (triggers sync) |
| `POST /google/sync` · `DELETE /google/connections/{id}` | A | sync now; disconnect (revokes at Google, wipes tokens) |
| `GET /reviews` | S | filters: `location_id`, `rating`, `reply_state` (none/draft/approved/failed/published), `search`, paging |
| `GET /reviews/{id}` | S | review, drafts, publish log |
| `POST /reviews/{id}/drafts/generate` · `POST /reviews/{id}/drafts` | S | AI draft / manual draft |
| `PATCH /reply-drafts/{id}` · `DELETE /reply-drafts/{id}` | S | edit (voids approval) / discard |
| `POST /reply-drafts/{id}/approve` | A | body `{acknowledge_flags}`; `409 flags_need_acknowledgement` for flagged reviews |
| `POST /reply-drafts/{id}/publish?replace_existing=` | A | calls Google; `published` only on success, else `failed` with reason (retry = call again) |
| `GET /analytics/overview?from=&to=&location_id=` | S | reviews, engagement funnel + definitions, per card/location, AI usage, sync status |
| `GET /api/health` | public | liveness + DB check |

## Billing (Razorpay) — `/billing`
| Method & path | Who | Purpose |
|---|---|---|
| `GET /billing/plans` | public | plans (INR paise), trial days, `billing.configured/mode`, card price |
| `GET /billing/subscription` | S | status, entitlements (`active`, `inactive_reason`), limits, live usage, trial/grace dates |
| `POST /billing/subscription/checkout` `{plan}` | O (verified) | creates/reuses a Razorpay subscription (idempotent per tenant+plan; first charge deferred to end of trial). `503 billing_config_pending` without keys |
| `POST /billing/subscription/verify` | O | checkout callback: verifies HMAC signature, then **fetches the real status from Razorpay** before changing anything |
| `POST /billing/subscription/cancel` `{at_cycle_end}` | O | cancel via Razorpay; local flag set only after Razorpay accepts |
| `POST /billing/subscription/change-plan` `{plan}` | O | upgrade now / downgrade at cycle end; downgrade blocked if usage exceeds the smaller plan |
| `GET /billing/payments?kind=` | S | payment/invoice history (`subscription` and `card_order` are separate kinds) |
| `GET/POST /billing/card-orders` · `POST /billing/card-orders/verify` | S / O | physical card purchase via Razorpay Orders (`Idempotency-Key` header supported) |
| `POST /billing/razorpay/webhook` | Razorpay | `X-Razorpay-Signature` HMAC over the raw body; `X-Razorpay-Event-Id` stored for idempotency; non-2xx on processing error so Razorpay retries |

## Google Business Profile management — `/gbp/{google_location_id}` (plan-gated, tenant-scoped)
`GET|PATCH /info` (description, hours, primary category, phone, website) · `GET /categories?q=` · `GET|POST|DELETE /posts` · `GET|POST|DELETE /media` · `GET /performance?from&to`. Responses always reflect what Google returned; Google errors map to 403/409/429/502 with "nothing was changed".

## Insights
`GET /analytics/insights?from&to&location_id` — sentiment mix and recurring topics (keyword heuristic; plan feature `insights`).

## Platform admin additions — `/admin` (PA only)
`GET /admin/tenants` (search/status, paged `{total,items}`) · `GET /admin/tenants/{id}` · `POST .../suspend|unsuspend` · `PATCH .../support` · `POST .../subscription` (manual override, reason required) · `PATCH /admin/users/{id}` (deactivate + kill sessions) · `GET /admin/subscriptions|payments|card-orders|ai-usage|audit|stats` · `PATCH /admin/card-orders/{id}` (fulfilment; refuses unpaid orders).

## Phase 2 additions (plans, usage, finance, readiness)

Roles: S = any member of the business, A = owner or admin, O = owner, PA = platform admin. Plan features are enforced here, not in the browser: a route whose feature is not in the plan answers `402 {"code": "plan_upgrade_required", "feature": "...", "message": "<Feature name> isn't included in your current plan..."}`.

| Method & path | Who | Purpose |
|---|---|---|
| `GET /api/ready` | public | readiness: database, Redis and migration revision. `200` or `503`; statuses only, no detail. The worker heartbeat is deliberately excluded. |
| `GET /billing/plans` | public | the confirmed plans (Starter, Growth, Pro) with `review_generations` and `review_replies` allowances, the card bundles (`card_offers`) and the one-time-purchase note |
| `GET /billing/subscription` | S | plan, status, limits (`review_generations`, `review_replies`, locations, staff, features) and usage for both allowances; `promo` is the active free card month, if any |
| `GET /billing/subscription/history` | A | everything that happened to the subscription: trial, activation, plan changes, failed payments, cancellation, refunds, free months |
| `POST /billing/card-orders` | O | `quantity` 1 or 2 are the ₹800 / ₹1,000 bundles; 10 to 1000 is a bulk order at `CARD_PRICE_PAISE` (if set). A paid order grants one free Growth month (see settings) |
| `GET /workspace/getting-started` | S | the onboarding checklist, computed from real records |
| `GET /admin/plans` | PA | plans, pending owner configuration, assumptions, promotion settings |
| `PUT /admin/plans/{code}/limits` | PA | approve or clear the map allowances (all three, or none); audited with a note; `apply_to_existing` |
| `GET /admin/costs?month=YYYY-MM&top=` | PA | AI and Google/Places usage and cost, by feature, operation and business; unpriced calls are counted, never priced at zero |
| `GET /admin/finance?month=YYYY-MM` | PA | MRR, one-time card revenue, costs and unit economics; every figure is `actual`, `estimated` or `missing` |
| `GET` / `PUT /admin/tenants/{id}/budgets` | PA | one business's AI dollar budget and Places search ceiling; audited |
| `GET /admin/release-gates` | PA | the release ladder and its evidence (never computed) |
| `POST /billing/razorpay/webhook` | signed | now also handles `refund.processed`, `refund.created`, `payment.refunded` (idempotent; a refund never cancels a subscription by itself) |
