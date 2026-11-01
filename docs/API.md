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
| `POST /tenants` | session | onboarding: create business (+Owner membership, trial subscription) |
| `GET/PATCH /tenant` | S / A | business profile, AI tone & instructions |
| `POST /tenant/complete-onboarding` | A | requires ≥1 location |
| `GET /tenant/subscription` | S | plan, quotas (no billing yet) |
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
