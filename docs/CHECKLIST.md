# Implementation progress

Honest status. ✅ = built **and** verified as stated. 🟡 = built, with a stated verification gap. ⬜ = not built.

## Milestone 1 — foundation, auth, tenancy
- ✅ Monorepo, Docker Compose (+prod overlay with Caddy), PostgreSQL, Redis, FastAPI, Next.js, Alembic migrations (applied from scratch in every test run)
- ✅ Registration, login, logout, Argon2id, sessions, CSRF, profile, change password
- ✅ Password-reset flow (token architecture + SMTP sender) 🟡 SMTP delivery not exercised against a real mail server
- ✅ Tenant creation, onboarding wizard (business → location → Google-or-manual), staff invitations/roles
- ✅ Cross-tenant isolation tests + RLS tests (58 backend tests passing)

## Milestone 2 — locations & card engine
- ✅ Locations CRUD (plan limit), editable Google review URL (host-validated)
- ✅ Batches, unique `FQR-####` codes (DB sequence), 144-bit tokens, QR PNG/SVG (error correction H, quiet zone), **decode round-trip verified with OpenCV**
- ✅ ZIP export (PNG+SVG+manifest.csv), printable A4 sheet, inventory search/filter, assign/reassign/unassign/status, assignment history
- ✅ Public resolve: active check, scan event, fallback pages for unassigned/inactive/unknown, history survives reassignment, rate limit, bot filter
- 🟡 NFC: the same URL is what you write to NTAG tags (instructions in the UI); no NFC hardware was available to test writing.

## Milestone 3 — public page & AI assistant
- ✅ Mobile-first landing page (browser-tested at 390 px), copy, continue-to-Google, honest fallbacks, EN/HI/Hinglish copy and detection
- ✅ AI assist with anti-fabrication prompt, length guard, no sentiment gating, per-IP + per-tenant limits, usage log
- 🟡 **Gemini provider has not been called against the real API (no key).** Tested with a labelled stub; with no key the UI honestly says writing help is unavailable.

## Milestone 4 — Google
- ✅ Server-side OAuth with signed state + nonce cookie, encrypted tokens, discovery, location selection/mapping, disconnect, revoked handling, "configuration pending" state
- ✅ Sync: idempotent upsert, update tracking, backoff/rate-limit/revocation handling, status display, Celery worker + beat (a real worker consumed a task from Redis)
- ✅ Reviews inbox with filters; AI reply drafts; sensitive-content flags; edit voids approval; approve (+ack) → publish → logs → retry; "published" only after provider success
- 🟡 **`HttpGoogleProvider` has never talked to Google** (no credentials / API approval). Endpoints follow Google's documented v1/v4 shapes; expect to adjust field names on first contact. All logic was tested with a labelled fake provider.
- ⬜ Google push notifications for reviews (design leaves room; polling only)

## Milestone 5 — analytics & hardening
- ✅ Dashboard + card analytics: date range, location filter, accessible charts, funnel definitions, response-time & reply-rate
- ✅ Security headers, rate limits, production config guard, audit logs, backups scripts, deployment guide
- 🟡 Dockerfiles/Compose **not built or run** (no Docker daemon in the authoring sandbox); `docker compose config` passes for base and prod
- ⬜ Frontend unit/component tests (only the Playwright smoke test and TypeScript/`next build` checks)
- ⬜ Razorpay/billing (by design: `Subscription` entity only)

## Known limitations / next tasks
1. Staging deploy with real Docker + a real domain; fix whatever the first build reveals.
2. Obtain Google OAuth credentials + Business Profile API approval; run the connect → sync → reply flow for real; adjust the provider.
3. Provide `GEMINI_API_KEY`; review output quality in Hindi/Hinglish with native speakers.
4. Card self-activation (claim code printed under the QR) so owners can activate cards without FlowHQ staff.
5. Email verification, MFA, privacy policy/terms pages, data-retention job for `scan_events`.
6. Component tests for forms; CI pipeline (pytest, tsc, build, audit).
