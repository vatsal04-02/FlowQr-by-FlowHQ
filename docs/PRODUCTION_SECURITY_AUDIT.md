# Production security audit (pre-deployment)

**Scope and honesty.** This extends `docs/PHASE_2_SECURITY_AUDIT.md` (an internal review of the whole application: authentication, sessions, OAuth, token protection, tenant isolation, roles, admin, rate limits, CSRF, secrets, logs, background jobs, autonomy) to the **production topology**: the site on Vercel and the API on a shared VPS. **No live server has been audited, because none is deployed.** This is an internal review and tests, not an independent penetration test. Statuses: PASS, FAIL, BLOCKED, NOT TESTED.

## New findings from the production design (all fixed, all with regression tests)

| # | Severity | Finding | Fix | Test |
|---|---|---|---|---|
| P1 | **High (functional, would have logged everyone out in production)** | `COOKIE_DOMAIN` was **not passed through Docker Compose**, so the documented setting did nothing: the session cookie would have been host-only on `api.flowqr.site` and the site on `flowqr.site` would never have been signed in. `SUPPORT_EMAIL`, `LEGAL_COMPANY_NAME` and `SESSION_TTL_HOURS` had the same gap | passed through in `docker-compose.yml` | `deploy/vps` overlay renders it; the strict guard (P3) |
| P2 | Medium | With the site and API on different hosts the browser **hides every custom response header** unless the API exposes it. The "not for print", "scannable" and file-name signals on QR downloads would have silently disappeared | `expose_headers` in the CORS middleware | `test_cross_origin_browser_calls_work_for_the_site_and_only_the_site` (also fails if a new `X-FlowQR-*` header is added without being exposed) and `e2e/split-host.js` |
| P3 | Medium | Nothing stopped a production start with a mismatched cookie domain or a `CORS_ORIGINS` that omits the site | the strict config guard now **refuses to start** in those cases | `test_split_host_production_refuses_settings_that_would_log_everyone_out_or_block_every_request` and the boot test |
| P4 | Low | The frontend assumed a same-origin API (relative URLs in 14 places) | one configurable API origin (`NEXT_PUBLIC_API_URL`); empty keeps development unchanged | `e2e/split-host.js`; the Vercel build |

## Controls verified for the cross-origin design

| Control | Result |
|---|---|
| CORS: only `https://flowqr.site` and `https://www.flowqr.site` (explicit, credentialed); `https://evil.example`, a lookalike (`flowqr.site.evil.example`), `http://flowqr.site` and the API's own origin are refused | **PASS** (unit test over the real middleware settings) |
| Session cookie `HttpOnly`, `Secure` (required by the guard), `SameSite=Lax`, `Domain=.flowqr.site`; unreadable by JavaScript | **PASS locally** (browser test, host-only variant); **NOT TESTED** over TLS on the real domains |
| CSRF: a cookie-authenticated mutating call without the `X-CSRF-Token` header is refused across origins, accepted with it | **PASS** (browser test and the whole-API sweep from Phase 2) |
| Logout revokes the server-side session; replay of the old cookie is refused | **PASS** |
| Rate limits see the real client address (the browser talks to the API directly, not through a proxy that would hide it) | **PASS in design**; **NOT TESTED** on the VPS. The API trusts `X-Forwarded-For` (`--forwarded-allow-ips=*`): safe only while the API is reachable solely through Caddy. In the overlay it is published on `127.0.0.1` only, so **other applications on the same server could reach it directly**: keep them off it, and do not publish the port publicly |
| PostgreSQL and Redis not published; worker and beat publish nothing; no reverse proxy added | **PASS in design** (`docker compose config`); **NOT TESTED** on the server |
| Strict production guard (secrets, Fernet key, secure cookies, https URLs, real SMTP, verified email, admin list, no test payment keys) | **PASS** with a production-shaped environment |
| API documentation and OpenAPI schema disabled in production | **PASS** (checked on local staging) |
| Vercel: Deployment Protection on; preview builds cannot call the API (their origin is not allowed) | **PASS / by design**. A **protection-bypass secret was created by the Vercel CLI**: revoke it |
| No secret in the frontend bundle or Vercel variables (`NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_SITE_URL` only) | **PASS** |
| Google OAuth: state, nonce, PKCE, verified email, token encryption, refresh-token handling | **PASS** (Phase 2 audit, tests with doubles); **NOT TESTED** on the production redirect URIs, which must be registered exactly as `https://api.flowqr.site/api/v1/google/callback` and `https://api.flowqr.site/api/v1/auth/google/callback` in a Google Cloud OAuth client whose consent screen includes the real users |

## Still open (carried over, still true)

* **Second factor for administrators** (owner decision); **independent penetration test** of the deployed server and TLS; **real SMTP** (the guard requires it); **`SENTRY_DSN`** for error monitoring; rotate the Places key that was pasted into chat; set the administrator password with `set-admin-password`.
* **Autonomy and automatic replies are on by default** for every business (owner decision, 2026-11-15) while the live Google write validation is incomplete (stage 1 done; stages 2 to 4 not). For production, either finish the validation first or start with `AUTONOMY_EMERGENCY_STOP=true`.
* Server hardening of the VPS itself (SSH, firewall, updates, who else can reach loopback ports) is **NOT AUDITED**.
