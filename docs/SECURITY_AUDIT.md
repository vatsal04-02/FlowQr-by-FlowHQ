# Security audit: 2026-11-14

Scope: backend API, tenancy, uploads, AI paths, dependencies, headers and deploy config. Method: attack tests that run against the real app and a real PostgreSQL 16 (`backend/tests/test_security_audit.py`), plus code and config review. Google and AI are test doubles in these tests, so they prove FlowQr's own enforcement, not Google's.

Round 2 (2026-11-15) re-ran everything below on the final code, reassessed every accepted item and added the autonomous-agent and operations code. Nothing was committed or deployed. No secrets were printed or rotated.

## Findings

| # | Severity | Finding | Where | Status |
|---|---|---|---|---|
| 1 | Medium | A tiny PNG that declares a 30000×30000 canvas (decompression bomb) crashed the photo upload with an uncaught error (HTTP 500) and would have decoded a huge image in memory | `backend/app/services/media.py` | **Fixed.** Pixel cap of 50 MP checked from the header before any pixel is decoded; Pillow's own bomb error is caught. Now a clean 422 |
| 2 | Low | `%` and `_` typed into the command-palette search and the admin user search acted as SQL LIKE wildcards. Still tenant-scoped (no cross-tenant leak), but `%%` matched everything | `backend/app/api/v1/notifications.py`, `admin_users.py` | **Fixed.** Wildcards are escaped and treated as literal text |
| 3 | Medium | PyJWT 2.10.1 had several published advisories (fixed in 2.13 to 2.15). Used only to verify Google ID tokens (RS256) | `backend/requirements.txt` | **Fixed.** Pinned 2.15.1; 40 sign-in tests pass; `pip-audit` reports no known vulnerabilities |
| 4 | Low | No Content-Security-Policy header | `frontend/next.config.mjs`, `backend/app/main.py` | **Partly fixed; reassessed, acceptable for launch.** Added the safe subset: `base-uri`, `object-src`, `frame-ancestors`, `form-action` on the app, and `default-src 'none'` on the API. A `script-src` policy needs per-request nonces in Next.js and was not attempted | Reassessed: the app has exactly two inline scripts (static JSON-LD and the theme boot script), renders no user HTML (`dangerouslySetInnerHTML` appears only in those two places) and React escapes everything else, so the missing `script-src` is defence in depth, not an open hole. Plan: nonce-based `script-src` after launch.
| 5 | Low | npm audit: postcss bundled inside Next.js (4 advisories, now rated high by npm), build-time only | `frontend/package.json` | **Fixed (2026-11-15).** `overrides` makes Next use the patched postcss 8.5.32; `npm audit` reports 0 vulnerabilities; production build passes |
| 6 | Medium | No error monitoring | whole app | **Built, needs your DSN.** Sentry reporting for API, worker and beat plus a browser crash relay; request bodies, cookies, headers and local variables are stripped (tested). The Operations page shows "critical" until `SENTRY_DSN` is set in production |
| 7 | Medium | A Google Places API key was pasted into the chat to enable Local ranking, so it must be treated as exposed | `.env` (gitignored) | **Open, yours to do.** Create a new key restricted to Places API (New) and the server IP, set a quota cap and budget alert, delete the pasted one. The app keeps the key server-side, sends it only as a request header, strips it from error messages and never returns it (tested) |
| 8 | Medium | The platform admin password was issued in chat | production database | **Open, yours to do.** `python -m app.cli set-admin-password --email <you>` (typed twice, never echoed, signs the account out everywhere). Tested |
| 9 | Info | Operations page and `/admin/ops` could leak configuration | `backend/app/api/v1/ops.py` | **Checked.** Platform-admin only (owners get 403, anonymous 401); returns counts, timestamps and setting names, never keys, DSN or passwords (tested with secrets set) |
| 10 | Info | The app's database role can now read `alembic_version` (migration 0024) | PostgreSQL | **Accepted.** Read-only (`SELECT` only; an UPDATE is refused, tested). Needed so the Operations page can prove the database matches the code |

No critical or high findings.

## What was attacked and held

- **Every API route called with no login**: all refuse (401/403) except a reviewed public list (auth flows, token-addressed public card and review pages, Razorpay webhook which is signature-checked, Google OAuth callback which is state-cookie checked, health).
- **Every mutating route called with a valid session cookie but no CSRF header**: all refuse.
- **Cross-tenant (IDOR)** against photos, request templates, the profile optimizer, keywords, notifications and search: tenant B gets 403/404 and sees nothing of tenant A; A's data is unchanged afterwards. PostgreSQL row-level security backs the API checks.
- **Location-restricted staff** cannot reach other locations through the new endpoints; staff cannot approve, cancel, edit settings, use admin tools or preview voice.
- **Business owners** cannot use the admin user lookup, list or edit.
- **Uploads**: script and PHP disguised as photos, SVG with script, oversize, decompression bomb and an injected category string are all refused; an image with trailing script bytes is only ever served as an image type.
- **AI**: review text is fenced as data inside the prompt and labelled "DATA, not instructions"; an injection attempt did not change the output; drafts with invented claims (guaranteed cures, prices, discounts) are blocked before a person sees them; nothing is published without approval.
- **Config review**: session and CSRF cookies are `HttpOnly` (session) with `Secure` and `SameSite=Lax`; the OAuth flow signs its state and checks it against a per-browser nonce cookie; CORS allows only configured origins and an explicit header list; the production config guard refuses dev secrets, insecure cookies and localhost URLs; no secrets are tracked in git; tokens are encrypted at rest; logs do not include tokens or passwords (searched).

## Not tested here (needs your environment)

- Penetration test of the deployed server, TLS configuration and WAF.
- Backup restore from off-site storage.
- Real Google write calls (see `PRODUCTION_READINESS.md`).
- Rate limits under real traffic (unit-level limits are covered by tests).
