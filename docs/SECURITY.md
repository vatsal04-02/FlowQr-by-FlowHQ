# Security checklist

Legend: ✅ implemented & covered by a test · 🟡 implemented, not automatically tested · ⬜ not done / out of scope for MVP

## Authentication & sessions
- ✅ Passwords hashed with **Argon2id**; transparent rehash on login; constant-time dummy verify for unknown users.
- ✅ Opaque server-side sessions; only SHA-256 of the token stored; HTTP-only, `SameSite=Lax`, `Secure` when `COOKIE_SECURE`; logout revokes server-side.
- ✅ **CSRF**: header token must equal the token bound to the session on every unsafe method; OAuth callback protected by signed state + nonce cookie.
- ✅ Login limited per IP and per email; registration/reset per IP (Redis fixed window, in-memory fallback).
- ✅ Password policy (≥10 chars, mixed case); reset tokens single-use, 30 min, revoke all sessions; request endpoint never reveals account existence.
- 🟡 Registration returns 409 for an existing email (account enumeration trade-off for UX).
- ⬜ MFA, device list UI, email verification on registration.

## Tenant isolation
- ✅ Tenant derived server-side; `X-Tenant-Id` only selects among the user's memberships.
- ✅ Every query is tenant-filtered **and** PostgreSQL RLS (FORCE, non-superuser role, default deny) is a second layer. Tests: cross-tenant read/update/delete on locations, cards, reviews, drafts, Google connections, analytics; raw-SQL RLS test.
- ✅ Role checks: Staff cannot manage locations/settings/Google/approve/publish.
- ✅ Audit log for logins, tenant/location changes, staff changes, card operations, Google connect/disconnect/selection, reply approve/publish attempts; append-only for the app role.

## Secrets & Google tokens
- ✅ Refresh/access tokens **Fernet-encrypted at rest**; never returned by any endpoint (tested); never logged; not stored in the browser.
- ✅ Disconnect revokes at Google (best effort) and wipes local tokens. Revoked/`invalid_grant` → connection marked `revoked`, UI asks to reconnect.
- ✅ Least-privilege scope: only `business.manage` (+ `openid email` to display the connected account).
- ✅ Gemini key in a header (not URL); `.env` git-ignored; backend refuses unsafe production config (tested).

## Public surface
- ✅ Card tokens 144-bit random; public payload exposes no internal IDs (tested); unknown tokens aren't stored; per-IP limits on resolve (60/min), events (120/min), AI (6/10 min per IP+card, 30/h per IP) plus per-tenant monthly AI quota.
- ✅ Bot filtering (UA heuristics) excluded from analytics; 20 s scan dedupe.
- ✅ Review links must be `https` on Google domains (prevents open-redirect/phishing use of cards) (tested).
- ✅ AI: customer text delimited as data, anti-fabrication prompt, output-length guard; usage logs store sizes only.
- 🟡 Rate limiting trusts `X-Forwarded-For` from Caddy→Next→API; keep API/Next unpublished (the prod overlay does).
- ⬜ CAPTCHA/proof-of-work on `assist`; WAF.

## Transport & headers
- ✅ Caddy automatic HTTPS + HSTS; `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`; API `Cache-Control: no-store`; printable sheet served with a restrictive CSP.
- ✅ CORS allow-list with credentials; unhandled errors return a generic message (details only in server logs); OpenAPI disabled in production.
- ⬜ Full CSP for the Next.js app (needs nonces for Next inline scripts).

## Input & data
- ✅ Pydantic validation everywhere; SQLAlchemy parameterised queries only; no file uploads (logo is an https URL).
- ✅ Phone/time zone/language validated; Indian numbers normalised to `+91 XXXXX XXXXX`.

## Pre-launch checklist
1. `APP_ENV=production`, strong `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY` backed up offline, `COOKIE_SECURE=true`.
2. Confirm the API connects as `flowqr_app`: `SELECT current_user, rolsuper, rolbypassrls FROM pg_roles WHERE rolname=current_user;` → `flowqr_app | f | f`.
3. Postgres/Redis not publicly exposed; only Caddy publishes 80/443.
4. SMTP configured and invitation + reset flows tried end to end.
5. Backups scheduled, off-site copy, **restore rehearsed**.
6. Privacy policy + terms published (required for Google OAuth verification); data-retention decision for `scan_events`.
7. Review Google's Business Profile policies; never add incentives or review gating (also forbidden by this product's design).
8. Run `pytest`, the smoke test, and a dependency audit (`pip-audit`, `npm audit`) on the release commit.
